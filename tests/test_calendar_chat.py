from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from app import db, rag_service
from app.calendar_chat import answer_calendar, intent, rows
from app.exam_calendar import URL, LEGACY_URL, extract_calendar, refresh

NOW = datetime(2026, 10, 21, tzinfo=ZoneInfo('Asia/Seoul'))
CONTENT = """2026학년도 학사일정
1학기 | 제1학기 수강신청 | 2026. 2. 4.(수)~2. 6.(금)
1학기 | 제1학기 개강 | 2026. 3. 3.(화)
1학기 | 제1학기 기말시험 | 2026. 6. 13.(토)~6. 19.(금)
1학기 | 하계방학 | 2026. 6. 20.(토)~8. 31.(월)
2학기 | 제2학기 등록 | 2026. 8. 24.(월)~8. 27.(목)
2학기 | 제2학기 개강 | 2026. 9. 1.(화)
2학기 | 제2학기 중간시험 | 2026. 10. 20.(화)~10. 26.(일)
2학기 | 제2학기 기말시험 | 2026. 12. 12.(토)~12. 18.(금)
2학기 | 성적공시 및 정정 | 2026. 12. 29.(화)~2027. 1. 4.(월)
2학기 | 동계방학 | 2026. 12. 19.(토)~2027. 2. 28.(일)
"""


@pytest.fixture(autouse=True)
def database(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool)
    monkeypatch.setattr(db, 'engine', lambda: engine)
    db.init_db()
    yield
    engine.dispose()


def seed(content=CONTENT, url=URL):
    db.save_notice(source='공식 홈페이지', source_type='static', category='학사안내',
                   title='학사일정', content=content, url=url)


def test_general_final_period_no_department_and_no_generation(monkeypatch):
    seed()
    monkeypatch.setattr(rag_service, 'generate_answer', lambda *_: pytest.fail('Unexpected LLM call'))
    result = rag_service.answer_question('2026 동아대 기말고사 기간 언제임?')
    assert result['debug_info']['retrieval_mode'] == 'academic_calendar'
    assert '2026-06-13' in result['answer'] and '2026-12-18' in result['answer']
    assert result['debug_info']['llm_calls'] == 0
    assert result['sources'][0]['url'] == URL


@pytest.mark.parametrize('q,expected', [
    ('2026년 1학기 수강신청 언제야?', '2026-02-04'),
    ('2026년 2학기 개강 언제야?', '2026-09-01'),
    ('2026년 겨울방학 기간 알려줘', '2027-02-28'),
    ('2026년 여름방학 기간 알려줘', '2026-06-20'),
    ('2026년 2학기 성적공시 언제야?', '2027-01-04'),
    ('2026년 2학기 등록금 납부 기간 알려줘', '2026-08-24'),
    ('기말고사 언제야?', '2026-12-12'),
    ('2026년 2학기 학사일정 알려줘', '2026-09-01'),
])
def test_calendar_events(q, expected):
    seed()
    result = answer_calendar(q, now=NOW)
    assert result and expected in result['answer']


@pytest.mark.parametrize('q', [
    '전기공학과 교류기기 기말고사 언제야?',
    '운영체제 기말고사 기간 언제야?', '컴공 중간고사 시간표 알려줘',
    '수강신청 어떻게 해?', '수강신청 취소 언제까지 돼?', '계절학기 수강신청 기간 알려줘',
    '신입생 수강신청 언제야?', '대학원 기말고사 언제야?', '개강하기 싫다',
    '오늘 식단 알려줘', '기말고사 공부 방법 알려줘',
])
def test_personal_procedures_and_other_topics_not_hijacked(q):
    assert intent(q) is None


def test_no_other_year_substitution_and_missing_data():
    seed()
    result = answer_calendar('2027년 2학기 기말고사 기간 언제야?', now=NOW)
    assert result['debug_info']['status'] == 'calendar_not_collected'
    assert result['sources'] == []
    assert '2026-12-12' not in result['answer']


def test_followup_and_stale_department_context():
    seed()
    first = answer_calendar('2026년 2학기 기말고사 기간 언제야?', context={'department':'간호학과'}, now=NOW)
    assert '어느 학과' not in first['answer']
    followup = answer_calendar('그럼 1학기는?', context=first['conversation_context'], now=NOW)
    assert '2026-06-13' in followup['answer'] and '2026-12-12' not in followup['answer']
    assert answer_calendar('그럼 1학기는?', context={**first['conversation_context'], 'last_route':'chat'}, now=NOW) is None
    vacation = answer_calendar('그럼 방학은?', context=first['conversation_context'], now=NOW)
    assert '2027-02-28' in vacation['answer'] and '기말시험:' not in vacation['answer']


def test_next_semester_and_relative_year_never_reuse_old_dates():
    seed()
    result = answer_calendar('다음 학기 수강신청 언제야?', now=NOW)
    assert result['debug_info']['year'] == 2027
    assert result['debug_info']['term'] == 1
    assert result['debug_info']['status'] == 'calendar_not_collected'
    january = datetime(2027, 1, 10, tzinfo=ZoneInfo('Asia/Seoul'))
    result = answer_calendar('올해 기말고사 언제야?', now=january)
    assert result['debug_info']['year'] == 2027
    assert result['debug_info']['status'] == 'calendar_not_collected'


@pytest.mark.parametrize('lang,q,label', [
    ('en', 'When are the final exams in 2026?', 'final exams'),
    ('ja', '2026年の期末試験はいつですか？', '期末試験'),
    ('zh', '2026年期末考试时间是什么时候？', '期末考试'),
])
def test_multilingual_no_translation_api(monkeypatch, lang, q, label):
    seed()
    from app import query_language
    monkeypatch.setattr(query_language, 'korean_search_query', lambda *_: pytest.fail('Unexpected translation API'))
    result = rag_service.answer_question(q, language=lang)
    assert label in result['answer'] and '2026-12-18' in result['answer']


def test_old_date_column_order_and_legacy_url_remain_readable():
    seed('2026학년도 학사일정\n2학기 | 2026. 12. 12.(토)~12. 18.(금) | 제2학기 기말시험', LEGACY_URL)
    result = answer_calendar('2026년 2학기 기말고사 언제야?', now=NOW)
    assert '2026-12-12' in result['answer']
    assert result['sources'][0]['url'] == LEGACY_URL


@pytest.mark.parametrize('language,question,expected', [
    ('ko', '2026학년도 2학기 동아대학교 기말시험 기간 알려줘', '2026-12-12'),
    ('en', 'When are the university-wide final exams at Dong-A University for the second semester of 2026?', '2026-12-12'),
    ('ja', '東亜大学の2026年度2学期の期末試験期間はいつですか？', '2026-12-12'),
    ('zh', '东亚大学2026学年第二学期的期末考试时间是什么时候？', '2026-12-12'),
    ('zh', '东亚大学2026学年第一学期的期末考试时间是什么时候？', '2026-06-13'),
])
def test_natural_academic_year_and_semester_phrases(monkeypatch, language, question, expected):
    seed()
    from app import query_language
    monkeypatch.setattr(query_language, 'korean_search_query', lambda *_: pytest.fail('Unexpected translation API'))
    result = rag_service.answer_question(question, language='auto')
    assert expected in result['answer']
    assert result['answer_language'] == language
    assert result['debug_info']['llm_calls'] == 0


def test_confirmed_future_calendar_does_not_request_department_or_guess():
    seed()
    result = answer_calendar('2035학년도 2학기 동아대학교 기말시험 확정 날짜 알려줘', now=NOW)
    assert result['debug_info']['status'] == 'calendar_not_collected'
    assert result['sources'] == [] and '2026-12-12' not in result['answer']


@pytest.mark.parametrize('question', [
    'When is the Computer Architecture final exam in the second semester of 2026?',
    '2026年度2学期のコンピュータ構造の期末試験はいつですか？',
    '2026学年第二学期计算机组成原理期末考试是什么时候？',
])
def test_course_questions_not_mistaken_for_university_calendar(question):
    assert intent(question) is None


def test_new_html_rowspan_and_wrong_weekday_do_not_change_dates():
    html = """<main><h3>2026학년도 학사일정</h3>
    <table><thead><tr><th>학기</th><th>업무</th><th>기간</th></tr></thead>
    <tbody><tr><th rowspan="2">2학기</th><td>제2학기 중간시험</td><td>2026. 10. 20.(화)~10. 26.(일)</td></tr>
    <tr><td>제2학기 기말시험</td><td>2026. 12. 12.(토)~12. 18.(금)</td></tr></tbody></table>
    <h3>2026학년도 지정보강일</h3><table><tr><td>Not an academic event row</td></tr></table></main>"""
    content = extract_calendar(BeautifulSoup(html, 'html.parser'))
    parsed = rows(content)
    assert len(parsed) == 2 and all(r['term'] == 2 for r in parsed)
    seed(content)
    result = answer_calendar('2026년 2학기 중간고사 기간 언제야?', now=NOW)
    assert '2026-10-26' in result['answer'] and '(일)' not in result['answer']


def test_refresh_rejects_non_calendar_and_preserves_previous():
    seed()
    class Fetcher:
        def fetch(self, url):
            assert url == URL
            return BeautifulSoup('<div id="cont">서비스를 잠시 이용할 수 없습니다.</div>', 'html.parser'), url
    with pytest.raises(ValueError):
        refresh(Fetcher())
    assert '2026-12-18' in answer_calendar('2026년 기말고사 언제야?', now=NOW)['answer']
