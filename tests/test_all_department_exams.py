from datetime import datetime
from types import SimpleNamespace as Obj
import json
from app.exam_matching import matches
from app.exam_context import compact_exam_files
from app.exam_xlsx import header
from app import update_exams


def test_title_variants_and_semester_isolation():
    for title in ['2026-2 중간시험 일정 안내', '2026학년도 2 학기 중간 고사 안내', '중간시험 안내']:
        assert matches(title, '', datetime(2026, 9, 28), 2026, 2, '중간고사')
    assert not matches('2025-2 중간시험 일정', '', datetime(2026, 9, 28), 2026, 2, '중간고사')
    assert not matches('2026학년도 1학기 중간고사 안내', '', datetime(2026, 9, 28), 2026, 2, '중간고사')
    assert not matches('중간시험 안내', '', None, 2026, 2, '중간고사')
    assert not matches('기말시험 안내', '', datetime(2026, 9, 28), 2026, 2, '중간고사')


def test_pdf_exam_evidence_is_not_dropped_and_is_bounded():
    a = Obj(id='pdf', filename='시험.pdf', url='https://example.com/a.pdf', checked_at=None, status='ok')
    r = Obj(id=1, source_type='attachment', category='경영학과', title='중간시험',
            url=a.url, published_at=None, crawled_at=None, content='경영학원론 10월 20일 13:00\n' * 600)
    docs = compact_exam_files([(r, Obj(page_number=1), a)], '경영학과 중간고사', budget=1000)
    assert len(docs) == 1
    assert '13:00' in docs[0].chunk_text
    assert '일부 발췌' in docs[0].chunk_text
    assert len(docs[0].chunk_text) <= 1000


def test_other_department_excel_headers():
    assert header('교과목명') == '강의명'
    assert header('시험 일자') == '요일'
    assert header('시작 시간') == '시험 시작시간'
    assert header('학번') == '학번'  # Never whitelist student records.


def test_all_boards_continue_after_failure(monkeypatch):
    from app import exam_calendar
    monkeypatch.setattr(exam_calendar, 'refresh', lambda _: 'unchanged')
    catalog = {'sources': [dict(department=d, category=d, kind=k, url=u)
                           for d,k,u in [('경영학과','board','https://a?x=1'),
                                         ('기계공학과','board','https://b?x=1'),
                                         ('간호학과','review','https://c')]]}
    class Catalog:
        def read_text(self, **kwargs): return json.dumps(catalog)
    monkeypatch.setattr(update_exams, 'Path', lambda _: Catalog())
    visited = []
    class Fetcher:
        def fetch(self, url):
            visited.append(url)
            if url.startswith('https://a'): raise ValueError('failed')
            return 'listing', url
        def close(self): pass
    monkeypatch.setattr(update_exams, 'PublicFetcher', Fetcher)
    monkeypatch.setattr(update_exams, 'parse_listing', lambda *_: [])
    monkeypatch.setattr(update_exams.db, 'record_crawl', lambda *args: None)
    report = update_exams.update(index=False)
    assert len(visited) == 2
    assert report['경영학과']['status'] == 'partial'
    assert report['기계공학과']['status'] == 'not_found_in_scanned_pages'
    assert report['간호학과']['status'] == 'board_not_registered'
