"""Date-keyed cafeteria menus. No embeddings or inferred future menus."""
import calendar
import json
import logging
import threading
import time
import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Column, Date, DateTime, String, Text, select, text
from . import db
from .crawl_common import Fetcher

KST = timezone(timedelta(hours=9))
CAMPUS = {'2':'승학', '1':'구덕·부민'}
BASE_URL = 'https://www.donga.ac.kr/community/life-info/menu'
log = logging.getLogger(__name__)


def today():
    return datetime.now(KST).date()


def source_url(day, campus):
    # The public page now contains all dates and both campus widgets.
    # Its robots policy disallows query URLs; do not invent legacy parameters.
    return BASE_URL


class MealFetcher(Fetcher):
    def _get(self, url):
        delay = max([10] + [r.crawl_delay(self.agent) or r.crawl_delay('*') or 0 for r in self.robots.values()])
        time.sleep(max(0, delay - (time.monotonic() - self.last_request)))
        return super()._get(url)


def parse_current_page(soup):
    """Trust explicit campus metadata and date panels, never tab positions."""
    import re
    result, seen_campuses = {}, set()
    labels = {'승학캠퍼스':'2', '구덕/부민캠퍼스':'1'}
    for widget in soup.select('[data-cms-widget-key="content.calendar"]'):
        try:
            props = json.loads(widget.get('data-cms-widget-props', '{}'))
        except ValueError:
            raise ValueError('menu_widget_invalid') from None
        if not isinstance(props, dict) or props.get('dataSource') != 'diet':
            continue
        campus = labels.get(re.sub(r'\s+', '', str(props.get('campus', ''))))
        if not campus or campus in seen_campuses:
            raise ValueError('menu_campus_mismatch')
        seen_campuses.add(campus)
        panels = widget.select('[data-widget-role="diet-day-panel"][data-date]')
        if not panels:
            raise ValueError('menu_dates_missing')
        for panel in panels:
            raw_day = panel.get('data-date', '')
            if not re.fullmatch(r'20\d{2}-\d{2}-\d{2}', raw_day):
                raise ValueError('menu_date_mismatch')
            day = date.fromisoformat(raw_day)
            if (day, campus) in result:
                raise ValueError('menu_date_duplicate')
            table = panel.select_one('table.cal-diet-day-table')
            if table is None:
                raise ValueError('menu_table_missing')
            headers = [h.get_text(' ', strip=True) for h in table.select('thead th')]
            if len(headers) < 2 or headers[0] != '구분' or any(not h for h in headers):
                raise ValueError('menu_cafeterias_missing')
            rows, menus = table.select('tbody tr'), []
            if not rows:
                raise ValueError('menu_rows_missing')
            for row in rows:
                cells = row.find_all('td', recursive=False)
                if len(rows) == 1 and len(cells) == 1 and 'cal-noday' in cells[0].get('class', []):
                    if int(cells[0].get('colspan', '0')) != len(headers) or cells[0].get_text(strip=True) != '해당 날짜의 식단 정보가 없습니다.':
                        raise ValueError('menu_empty_marker_changed')
                    continue
                label = row.find('th', recursive=False)
                if label is None or len(cells) != len(headers)-1:
                    raise ValueError('menu_columns_changed')
                for cafeteria, cell in zip(headers[1:], cells):
                    content = cell.get_text('\n', strip=True)
                    if not content or content == '-':
                        continue
                    menus.append({'cafeteria':cafeteria, 'type':label.get_text(' ',strip=True), 'text':content})
            result[day, campus] = menus
    if seen_campuses != set(CAMPUS):
        raise ValueError('menu_campuses_missing')
    return result


class MealDay(db.Base):
    __tablename__ = 'meal_days'
    day = Column(Date, primary_key=True)
    campus = Column(String(2), primary_key=True)
    menus = Column(Text, nullable=False)
    checked_at = Column(DateTime, nullable=False)


class MealSync(db.Base):
    __tablename__ = 'meal_sync'
    key = Column(String(20), primary_key=True)
    success_day = Column(Date)
    attempted_at = Column(DateTime)
    status = Column(String(20), nullable=False, default='waiting')


def parse_menu(soup, expected_day, campus):
    import re
    period = soup.select_one('#dietSearchForm .period .start')
    category = soup.select_one('#searchDietCategory')
    match = re.search(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일', period.get_text(' ',strip=True) if period else '')
    if not match or date(*map(int,match.groups())) != expected_day:
        raise ValueError('menu_date_mismatch')
    if category is None or category.get('value') != campus:
        raise ValueError('menu_campus_mismatch')
    table = soup.select_one('#cafeteria-menu table')
    if table is None:
        raise ValueError('menu_table_missing')
    headings = [h.get_text(' ',strip=True) for h in table.select('thead th')][1:]
    if not headings:
        raise ValueError('menu_cafeterias_missing')
    menus = []
    rows = table.select('tbody tr')
    if not rows:
        raise ValueError('menu_rows_missing')
    for row in rows:
        label = row.find('th')
        cells = row.find_all('td',recursive=False)
        if len(cells)==1 and cells[0].select_one('.no-data') and int(cells[0].get('colspan','1')) >= len(headings):
            continue
        if not label or len(cells) != len(headings):
            raise ValueError('menu_columns_changed')
        for cafeteria, cell in zip(headings,cells):
            if cell.select_one('.no-data'):
                continue
            content = cell.get_text('\n',strip=True)
            if content:
                menus.append({'cafeteria':cafeteria,'type':label.get_text(' ',strip=True),'text':content})
    return menus


def save_day(day, campus, menus):
    with db.session_scope() as session:
        row = session.get(MealDay,(day,campus))
        if row is None:
            row = MealDay(day=day,campus=campus)
            session.add(row)
        row.menus = json.dumps(menus,ensure_ascii=False)
        row.checked_at = db.utcnow()


@contextmanager
def sync_lock():
    with db.engine().connect() as connection:
        mysql = connection.dialect.name == 'mysql'
        if mysql and connection.scalar(text("SELECT GET_LOCK('donga_meals_refresh', 0)")) != 1:
            raise RuntimeError('meal_sync_busy')
        try:
            yield
        finally:
            if mysql:
                connection.execute(text("SELECT RELEASE_LOCK('donga_meals_refresh')"))


def refresh_month(stop=None, fetcher=None):
    day = today()
    with sync_lock():
        with db.session_scope() as session:
            state = session.get(MealSync,'daily')
            if state is None:
                state = MealSync(key='daily')
                session.add(state)
            state.attempted_at = db.utcnow()
            state.status = 'running'
        owned = fetcher is None
        fetcher = fetcher or MealFetcher()
        failed = 0
        completed = 0
        try:
            records = parse_current_page(fetcher.fetch(BASE_URL))
            if any((day, campus) not in records for campus in CAMPUS):
                raise ValueError('menu_today_missing')
            # One page fetch covers both campuses and only explicitly supplied dates.
            # Validate the complete page before replacing any previous menu data.
            for (target, campus), menus in sorted(records.items(), key=lambda x:(x[0][0] != day, abs((x[0][0]-day).days))):
                if stop and stop.is_set():
                    failed += 1
                    break
                save_day(target,campus,menus)
                completed += 1
        except Exception as exc:
            failed += 1
            log.warning('meal_fetch_failed type=%s', type(exc).__name__)
        finally:
            if owned:
                fetcher.close()
            with db.session_scope() as session:
                state = session.get(MealSync,'daily')
                state.status = 'partial' if failed else 'ok'
                if not failed:
                    state.success_day = day
        return {'completed':completed,'failed':failed}


def refresh_due(state, now, startup=False):
    if state is None:
        return True
    if state.attempted_at and (now.astimezone(timezone.utc).replace(tzinfo=None)-state.attempted_at).total_seconds() < 1800:
        return False
    if state.status != 'ok':
        return True
    local = now.astimezone(KST)
    if not (startup or local.hour >= 6):
        return False
    age = (now.astimezone(timezone.utc).replace(tzinfo=None)-state.attempted_at).total_seconds() if state.attempted_at else float('inf')
    return state.success_day != local.date() or age >= 4*3600


def start_worker():
    stop = threading.Event()
    def run():
        startup = True
        while not stop.is_set():
            try:
                with db.session_scope() as session:
                    state = session.get(MealSync,'daily')
                if refresh_due(state,datetime.now(KST),startup):
                    refresh_month(stop)
            except Exception as exc:
                log.warning('meal_worker_failed type=%s',type(exc).__name__)
            startup = False
            stop.wait(60)
    thread = threading.Thread(target=run,name='meal-refresh',daemon=True)
    thread.start()
    return stop, thread


def month_data(month, campus):
    import re
    if campus not in CAMPUS or not re.fullmatch(r'20\d{2}-(?:0[1-9]|1[0-2])',month):
        raise ValueError('invalid_month_or_campus')
    year,number = map(int,month.split('-'))
    first = date(year,number,1)
    last = date(year,number,calendar.monthrange(year,number)[1])
    with db.session_scope() as session:
        rows = {r.day:r for r in session.scalars(select(MealDay).where(MealDay.day>=first,MealDay.day<=last,MealDay.campus==campus))}
        state = session.get(MealSync,'daily')
    days=[]
    for n in range(1,last.day+1):
        target=date(year,number,n)
        row=rows.get(target)
        menus=json.loads(row.menus) if row else []
        stale=bool(row and row.checked_at.replace(tzinfo=timezone.utc).astimezone(KST).date()<min(today(),target))
        days.append({'date':target.isoformat(),'menus':menus,
            'status':'not_collected' if row is None else 'published' if menus else 'not_published',
            'stale':stale,'checked_at':row.checked_at.isoformat()+'Z' if row else None,
            'url':source_url(target,campus)})
    return {'month':month,'campus':campus,'campus_name':CAMPUS[campus],'today':today().isoformat(),
            'sync_status':state.status if state else 'waiting',
            'sync_attempted_at':state.attempted_at.isoformat()+'Z' if state and state.attempted_at else None,
            'auto_refresh':os.getenv('MEALS_AUTO_REFRESH','true').lower()=='true','days':days}


if __name__ == '__main__':
    db.init_db()
    result = refresh_month()
    print(result)
    raise SystemExit(1 if result['failed'] else 0)
