from app import query_language, rag_service
import pytest

@pytest.mark.parametrize('question,expected', [('中間試験はいつですか？','ja'),('期中考试什么时候？','zh'),('When is the midterm?','en'),('중간고사 언제야','ko')])
def test_detect_languages(question,expected):
    assert query_language.detect_language(question)==expected

@pytest.mark.parametrize('question', ['コンピュータ工学科の中間試験の日程は？','计算机工程系的期中考试时间表是什么？','計算機工程系的期中考試時間表是什麼？'])
def test_asian_queries_are_translated(monkeypatch,question):
    calls=[]
    def translate(*args):
        calls.append(args)
        return '{"query":"컴퓨터공학과 중간고사 시간표 알려줘"}'
    monkeypatch.setattr(query_language,'generate_answer',translate)
    assert '컴퓨터공학과' in query_language.korean_search_query(question)
    assert len(calls)==1

def test_numeric_followup_keeps_language():
    assert query_language.detect_language('2023',{'history':[{'role':'user','content':'卒業要件は？'}]})=='ja'

@pytest.mark.parametrize('lang', ['ja','zh','en'])
def test_error_responses_localized(monkeypatch,lang):
    monkeypatch.setattr(query_language,'korean_search_query',lambda q:q)
    monkeypatch.setattr(rag_service,'_answer_question',lambda *args:{'answer':'한국어 오류','debug_info':{'status':'no_results'}})
    assert '한국어' not in rag_service.answer_question('test',lang)['answer']

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
