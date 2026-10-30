from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
import pytest
from app import db, rag_service
from app.exam_chat import answer_exam

@pytest.fixture(autouse=True)
def database(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool)
    monkeypatch.setattr(db, 'engine', lambda: engine)
    db.init_db()
    yield
    engine.dispose()

@pytest.mark.parametrize('question', ['중간고사 시간표 어캐됨?', '중간고사 관련', '중간고사', '중간 고사 알려줘', '시간표 알려줘 중간고사'])
def test_short_question_clarifies_department(question):
    result = answer_exam(question)
    assert result['debug_info']['status'] == 'clarification_required'
    assert result['conversation_context']['pending_question']

def test_scope_and_followup(monkeypatch):
    for title, category in [('2026학년도 2학기 중간고사 시간표', '컴퓨터공학과'),
                            ('2025학년도 2학기 중간고사 시간표', '컴퓨터공학과'),
                            ('2026학년도 2학기 중간고사 시간표', 'AI학과')]:
        db.save_notice(source='test', source_type='notice', title=title, category=category,
                       content='시험 시간표 원본 내용', url='https://example.com/'+title+category)
    def compose(q, docs, language, debug):
        assert len(docs) == 1
        assert docs[0].category == '컴퓨터공학과'
        assert '2026' in docs[0].title
        return {'answer': 'ok', 'sources': [], 'debug_info': debug}
    monkeypatch.setattr(rag_service, 'compose_answer', compose)
    result = answer_exam('컴공', context={'pending_question':'2026년 2학기 중간고사 시간표 어캐됨?'})
    assert result['answer'] == 'ok'
    assert 'pending_question' not in result['conversation_context']

def test_missing_data_and_unrelated_chat():
    assert answer_exam('오늘 학교가기 싫다') is None
    assert answer_exam('중간고사 망했어') is None
    result = answer_exam('2026년 2학기 컴공 중간고사 언제야?')
    assert result['debug_info']['status'] == 'exam_not_collected'


@pytest.mark.parametrize('department', ['간호학과', '경영학과', '기계공학과'])
def test_department_without_notice_answers_common_calendar(monkeypatch, department):
    from app.exam_calendar import URL
    db.save_notice(source='동아대학교 공식홈페이지', source_type='static', title='학사일정',
                   category='학사안내', content='2026학년도 학사일정\n2학기 | 2026. 10. 20.(화)~10. 26.(월) | 제2학기 중간시험', url=URL)
    def compose(question, docs, language, debug):
        assert len(docs) == 1
        assert '10. 20.' in docs[0].chunk_text
        assert '확정 시간표라고 단정하지' in question
        assert debug['coverage'] == 'university_calendar_only'
        return {'answer':'공통 기간', 'debug_info':debug}
    monkeypatch.setattr(rag_service, 'compose_answer', compose)
    result = answer_exam(f'2026년 2학기 {department} 중간고사 정보알려줘')
    assert result['answer'] == '공통 기간'
    assert result['conversation_context']['department'] == department


def test_calendar_never_uses_other_year_or_term():
    from app.exam_calendar import URL, evidence
    db.save_notice(source='동아대학교 공식홈페이지', source_type='static', title='학사일정',
                   category='학사안내', content='2025학년도 학사일정\n2학기 | 2025. 10. 20. | 제2학기 중간시험', url=URL)
    assert evidence('2026', '2', '중간고사') is None
    assert evidence('2025', '1', '중간고사') is None
    assert evidence('2025', '2', '기말고사') is None


def test_exam_followup_retains_course_and_ignores_changed_topic(monkeypatch):
    db.save_notice(source='test', source_type='notice', category='컴퓨터공학과',
                   title='2026학년도 2학기 중간고사 시간표', content='시험 정보', url='https://example.com/exam')
    questions = []
    def compose(question, docs, language, debug):
        questions.append(question)
        return {'answer':'ok', 'sources':[], 'debug_info':debug}
    monkeypatch.setattr(rag_service, 'compose_answer', compose)
    first = answer_exam('2026년 2학기 컴공 운영체제 중간고사 언제야?')
    state = first['conversation_context']
    followup = answer_exam('그럼 02분반 강의실은?', context=state)
    assert followup['answer'] == 'ok'
    assert '운영체제' in questions[-1] and '02분반' in questions[-1]
    assert answer_exam('오늘 식단 언제야?', context=state) is None
    assert answer_exam('강의실은?', context={**state, 'last_route':'chat'}) is None


def test_followup_department_change_drops_previous_course(monkeypatch):
    for department in ['컴퓨터공학과', '간호학과']:
        db.save_notice(source='test', source_type='notice', category=department,
                       title='2026학년도 2학기 중간고사 시간표', content='시험 정보', url='https://example.com/'+department)
    captured = []
    def compose(question, docs, language, debug):
        captured.append((question, docs))
        return {'answer':'ok', 'sources':[], 'debug_info':debug}
    monkeypatch.setattr(rag_service, 'compose_answer', compose)
    first = answer_exam('2026년 2학기 컴공 운영체제 중간고사 언제야?')
    answer_exam('간호학과는?', context=first['conversation_context'])
    question, docs = captured[-1]
    assert '운영체제' not in question
    assert all(d.category == '간호학과' for d in docs)
