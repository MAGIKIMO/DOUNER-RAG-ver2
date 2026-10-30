from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, select, func
from sqlalchemy.pool import StaticPool
from app import meals, meal_chat, db

TODAY = date(2026, 10, 30)


def page():
    return BeautifulSoup((Path(__file__).parent/'fixtures/meals_current.html').read_text(encoding='utf-8'), 'html.parser')


@pytest.fixture(autouse=True)
def database(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    monkeypatch.setattr(db, 'engine', lambda:engine)
    monkeypatch.setattr(meals, 'today', lambda:TODAY)
    monkeypatch.setattr(meal_chat, 'today', lambda:TODAY)
    db.init_db()
    yield
    engine.dispose()


def test_new_official_page_dates_and_campuses_do_not_mix():
    rows = meals.parse_current_page(page())
    assert len(rows) == 4
    seunghak = rows[TODAY, '2']
    bumin = rows[TODAY, '1']
    assert any('참치김치찌개' in row['text'] for row in seunghak)
    assert any('새우살순두부탕' in row['text'] for row in bumin)
    assert not any('새우살순두부탕' in row['text'] for row in seunghak)
    assert all(row['text'] != '-' for row in seunghak + bumin)
    assert rows[date(2026,10,31),'2'] == []


@pytest.mark.parametrize('mutation', ['missing_campus','unknown_campus','duplicate_day','bad_columns','empty_body'])
def test_layout_changes_are_not_silently_saved_as_no_menu(mutation):
    soup = page()
    widget = soup.select_one('[data-cms-widget-key]')
    if mutation == 'missing_campus': widget.decompose()
    elif mutation == 'unknown_campus': widget['data-cms-widget-props']='{"dataSource":"diet","campus":"unknown"}'
    elif mutation == 'duplicate_day':
        panels = widget.select('[data-date]'); panels[1]['data-date']=panels[0]['data-date']
    elif mutation == 'bad_columns': widget.select_one('tbody td').decompose()
    else: widget.select_one('tbody').clear()
    with pytest.raises(ValueError): meals.parse_current_page(soup)


def test_one_fetch_updates_supplied_days_without_duplicates_or_fabricated_dates():
    calls = []
    class Fetcher:
        def fetch(self, url): calls.append(url); return page()
    assert meals.refresh_month(fetcher=Fetcher()) == {'completed':4,'failed':0}
    assert meals.refresh_month(fetcher=Fetcher()) == {'completed':4,'failed':0}
    assert calls == [meals.BASE_URL]*2 and '?' not in meals.BASE_URL
    with db.session_scope() as s:
        assert s.scalar(select(func.count()).select_from(meals.MealDay)) == 4
        assert s.get(meals.MealSync,'daily').status == 'ok'
    result = meals.month_data('2026-10','2')
    assert result['days'][28]['status'] == 'not_collected'
    assert result['days'][29]['status'] == 'published'
    assert result['days'][30]['status'] == 'not_published'


def test_failed_refresh_preserves_previous_menu_and_records_failure():
    meals.save_day(TODAY,'2',[{'text':'previous menu','type':'정식','cafeteria':'학생회관'}])
    class Broken:
        def fetch(self,url): return BeautifulSoup('<p>maintenance</p>','html.parser')
    assert meals.refresh_month(fetcher=Broken())['failed'] == 1
    data = meals.month_data('2026-10','2')
    assert data['sync_status'] == 'partial' and data['sync_attempted_at']
    assert data['days'][29]['menus'][0]['text'] == 'previous menu'


def test_missing_today_is_not_accepted_as_a_fresh_snapshot():
    soup=page()
    for panel in soup.select('[data-date="2026-10-30"]'): panel.decompose()
    assert meals.refresh_month(fetcher=SimpleNamespace(fetch=lambda _:soup)) == {'completed':0,'failed':1}


def test_old_empty_past_or_today_menu_requires_refresh_instead_of_asserting_absence():
    for day in (TODAY, TODAY-timedelta(days=1)):
        meals.save_day(day,'2',[])
        with db.session_scope() as s:
            s.get(meals.MealDay,(day,'2')).checked_at=datetime(2026,10,11,17)
    data=meals.month_data('2026-10','2')
    assert data['days'][28]['stale'] and data['days'][29]['stale']
    result=meal_chat.answer_meal('오늘 승학 식단','ko',{})
    assert result['debug_info']['status']=='refresh_required'
    assert '이후 등록됐을 수' in result['answer']


def test_four_hour_refresh_and_failure_backoff():
    now=datetime(2026,10,30,10,tzinfo=meals.KST)
    def state(hours,status='ok'):
        return SimpleNamespace(success_day=TODAY,attempted_at=(now-timedelta(hours=hours)).astimezone(meals.timezone.utc).replace(tzinfo=None),status=status)
    assert not meals.refresh_due(state(3),now)
    assert meals.refresh_due(state(4),now)
    assert not meals.refresh_due(state(.1,'partial'),now)
    assert meals.refresh_due(state(.5,'partial'),now)
    assert meals.refresh_due(None,now,startup=True)


def test_morning_refresh_even_if_startup_succeeded_after_midnight():
    now=datetime(2026,10,30,6,tzinfo=meals.KST)
    state=SimpleNamespace(success_day=TODAY,status='ok',attempted_at=datetime(2026,10,29,15))
    assert meals.refresh_due(state,now)
