from app import query_language, rag_service

def test_english_exam_normalized(monkeypatch):
    monkeypatch.setattr(query_language,'generate_answer',lambda *args:'{"query":"2026년 2학기 컴퓨터공학과 컴퓨터네트워크 중간고사 언제야?"}')
    query=query_language.korean_search_query('When is the Computer Networks midterm for Computer Science in fall 2026?')
    from app.exam_chat import INTENT
    assert INTENT.search(query) and '2026' in query and '컴퓨터네트워크' in query

def test_skip_korean_smalltalk_and_preserve_failed_translation(monkeypatch):
    def fail(*args): raise RuntimeError('unavailable')
    monkeypatch.setattr(query_language,'generate_answer',fail)
    for q in ['중간고사 관련','hello','When is my exam?']:
        assert query_language.korean_search_query(q)==q

def test_answer_language_and_original_history_preserved(monkeypatch):
    monkeypatch.setattr(query_language,'korean_search_query',lambda q:'승학 오늘 식단 알려줘')
    def answer(q,language,*args):
        assert q=='승학 오늘 식단 알려줘' and language=='en'
        return {'answer':'Menu', 'conversation_context':{'history':[{'role':'user','content':q},{'role':'assistant','content':'Menu'}]}}
    monkeypatch.setattr(rag_service,'_answer_question',answer)
    result=rag_service.answer_question('What is on the menu at Seunghak today?', 'en')
    assert result['conversation_context']['history'][0]['content'].startswith('What')
