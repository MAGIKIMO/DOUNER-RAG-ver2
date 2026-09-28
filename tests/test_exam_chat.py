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

def test_short_question_clarifies_department():
    result = answer_exam('중간고사 시간표 어캐됨?')
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
    result = answer_exam('2026년 2학기 컴공 중간고사 언제야?')
    assert result['debug_info']['status'] == 'exam_not_collected'
