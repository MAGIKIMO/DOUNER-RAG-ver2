from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from app import db
from app.public_catalog import canonical, public_url, menu_entries
from app.crawl_public import crawl_one, register, PublicSource
from app.rag_service import latest_notices


@pytest.fixture(autouse=True)
def database(monkeypatch):
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    monkeypatch.setattr(db,"engine",lambda:engine)
    db.init_db()
    yield
    engine.dispose()


def test_public_boundaries():
    assert public_url("https://computer.donga.ac.kr/computer/Main.do")
    for url in ["https://eclass.donga.ac.kr/", "https://donga.ac.kr.evil.test/", "https://127.0.0.1/", "https://dx.donga.ac.kr/", "https://x.donga.ac.kr/login.do"]:
        assert not public_url(url)


def test_query_dedup_preserves_page_identity():
    assert canonical("https://www.donga.ac.kr/kor/CMS/Board/Board.do?mCode=MN170&page=2") == canonical("https://www.donga.ac.kr/kor/CMS/Board/Board.do?mCode=MN170")
    assert canonical("https://about.donga.ac.kr/about/CMS/Contents/Contents.do?mCode=MN044&dept_cd=1") != canonical("https://about.donga.ac.kr/about/CMS/Contents/Contents.do?mCode=MN044&dept_cd=2")


def test_menu_scope_does_not_import_other_department():
    soup=BeautifulSoup('<a href="/computer/CMS/Board/Board.do?mCode=MN044">공지사항</a><a href="/kor/CMS/Contents/Contents.do?mCode=MN137">졸업기준</a>',"html.parser")
    entries=menu_entries(soup,"https://www.donga.ac.kr/computer/Main.do","컴퓨터공학과")
    assert len(entries)==1
    assert entries[0]["category"]=="컴퓨터공학과"


def test_registry_keeps_previous_outcome_on_reregister():
    item={"department":"컴퓨터공학과","url":"https://computer.donga.ac.kr/computer/CMS/Board/Board.do?mCode=MN044","title":"공지사항","category":"컴퓨터공학과","kind":"board"}
    register({"sources":[item]})
    key=db.digest(item['department']+'|'+item['url'])
    with db.session_scope() as session: session.get(PublicSource,key).status="success"
    register({"sources":[item]})
    with db.session_scope() as session: assert session.get(PublicSource,key).status=="success"


def test_latest_sorted_by_date_and_scope():
    now=datetime.now()
    for title,category,age in [("new","A학과",1),("old","A학과",3),("other","B학과",0),("archived","A학과",500)]:
        db.save_notice(source=category,source_type="notice",category=category,title=title,content="본문",url="https://www.donga.ac.kr/"+title,published_at=now-timedelta(days=age))
    result=latest_notices("ko","A학과")
    assert [x['title'] for x in result['sources']]==['new','old']


def test_listing_failure_is_not_complete():
    class Fetch:
        def fetch(self,url): raise ValueError("changed HTML")
    source=SimpleNamespace(kind="board",url="https://www.donga.ac.kr/kor/CMS/Board/Board.do?mCode=MN171")
    status,pages,count,message=crawl_one(source,Fetch(),datetime.now()-timedelta(days=365),10)
    assert status=="failed"
    assert 'changed HTML' in message


def test_small_catalog_does_not_recrawl_unrelated_sources(monkeypatch):
    import json
    from app import crawl_public
    first = dict(title='Target', url='https://www.donga.ac.kr/target', category='A', department='', kind='static')
    other = dict(first, title='Other', url='https://www.donga.ac.kr/other')
    register({'sources': [other]})
    monkeypatch.setattr(crawl_public, 'Path', lambda p: SimpleNamespace(read_text=lambda encoding: json.dumps({'sources': [first]})))
    monkeypatch.setattr(crawl_public, 'PublicFetcher', lambda: SimpleNamespace(close=lambda: None))
    seen = []
    def crawl(source, *args):
        seen.append(source.url)
        return 'success', 1, 1, ''
    monkeypatch.setattr(crawl_public, 'crawl_one', crawl)
    crawl_public.run('unused')
    assert seen == [first['url']]
