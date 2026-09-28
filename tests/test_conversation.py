import json
import pytest
from pydantic import ValidationError
from app import conversation, rag_service
from app.main import ConversationContext


def test_smalltalk_does_not_search_and_retains_pending_scope(monkeypatch):
    monkeypatch.setattr(conversation,'generate_answer',lambda *args:'안녕! 무슨 이야기 할까?')
    monkeypatch.setattr(rag_service,'answer_documents',lambda *args:pytest.fail('smalltalk searched'))
    result=rag_service.answer_question('야 뭐함?',conversation_context={'pending_question':'졸업학점 알려줘','department':'컴퓨터공학과'})
    assert result['sources']==[]
    assert result['debug_info']['retrieval_mode']=='smalltalk'
    assert result['conversation_context']['department']=='컴퓨터공학과'
    assert result['conversation_context']['pending_question']=='졸업학점 알려줘'


def test_varied_social_message_can_be_classified(monkeypatch):
    def generate(system,user):
        data=json.loads(user)
        assert data['question']=='나 오늘 너무 지쳤어'
        return json.dumps({'route':'chat','answer':'많이 지쳤구나. 오늘 어떤 일이 있었어?'})
    monkeypatch.setattr(conversation,'generate_answer',generate)
    monkeypatch.setattr(rag_service,'answer_documents',lambda *args:pytest.fail('social message searched'))
    assert rag_service.answer_question('나 오늘 너무 지쳤어')['sources']==[]


@pytest.mark.parametrize('question',['안녕 장학금 언제 신청해?','졸업 못 할까 봐 걱정되는데 몇 학점 필요해?'])
def test_school_facts_never_use_smalltalk(monkeypatch,question):
    monkeypatch.setattr(conversation,'generate_answer',lambda *args:'{"route":"retrieve","answer":""}')
    monkeypatch.setattr(rag_service,'answer_documents',lambda q,*args:{'answer':q,'sources':[]})
    assert rag_service.answer_question(question)['answer']==question


@pytest.mark.parametrize('question',['오늘 학교 가기 싫네','졸업 못 할까 봐 걱정돼','학식 말고 그냥 집밥 먹고 싶다','과제 때문에 지쳤는데 웃긴 이야기 해줘'])
def test_school_words_and_pending_question_do_not_block_social_intent(monkeypatch,question):
    def generate(system,user):
        data=json.loads(user)
        assert data['context']['pending_question']=='졸업학점 알려줘'
        return json.dumps({'route':'chat','answer':'그럴 때도 있지. 오늘은 작은 일 하나부터 해보자.'})
    monkeypatch.setattr(conversation,'generate_answer',generate)
    monkeypatch.setattr(rag_service,'answer_documents',lambda *args:pytest.fail('chat searched'))
    result=rag_service.answer_question(question,conversation_context={'pending_question':'졸업학점 알려줘','department':'컴퓨터공학과'})
    assert result['sources']==[] and result['conversation_context']['last_route']=='chat'
    assert result['conversation_context']['pending_question']=='졸업학점 알려줘'


def test_social_followup_receives_latest_history_instead_of_old_school_query(monkeypatch):
    def generate(system,user):
        data=json.loads(user)
        assert data['history'][-1]['content']=='산책해 보면 어때?'
        assert 'last_question' not in data['context']
        return '```json\n{"route":"chat","answer":"짧게 한 바퀴만 걸어도 괜찮아."}\n```'
    monkeypatch.setattr(conversation,'generate_answer',generate)
    monkeypatch.setattr(rag_service,'answer_documents',lambda *args:pytest.fail('social followup searched'))
    result=rag_service.answer_question('그거 괜찮겠네',conversation_context={'last_question':'장학금 신청','last_route':'chat',
        'history':[{'role':'assistant','content':'산책해 보면 어때?'}]})
    assert '한 바퀴' in result['answer']


def test_pending_year_still_resumes_official_question(monkeypatch):
    monkeypatch.setattr(conversation,'generate_answer',lambda *args:'{"route":"retrieve","answer":""}')
    def documents(q,language,filters,mode,context):
        assert q=='2023' and context['pending_question']=='졸업학점 알려줘'
        return {'answer':'학사 근거 답변','sources':[]}
    monkeypatch.setattr(rag_service,'answer_documents',documents)
    result=rag_service.answer_question('2023',conversation_context={'pending_question':'졸업학점 알려줘','last_route':'chat'})
    assert result['conversation_context']['last_route']=='retrieve'


def test_followup_uses_subject_but_new_topic_does_not(monkeypatch):
    monkeypatch.setattr(rag_service,'answer_documents',lambda q,*args:{'answer':q,'sources':[]})
    context={'last_question':'가족장학금 신청 알려줘','history':[]}
    result=rag_service.answer_question('그거 신청은 어떻게 해?',conversation_context=context)
    assert '가족장학금' in result['answer'] and '후속 질문' in result['answer']
    result=rag_service.answer_question('그럼 기숙사 신청은?',conversation_context=context)
    assert result['answer']=='그럼 기숙사 신청은?'


def test_invalid_classifier_output_defaults_to_retrieval(monkeypatch):
    monkeypatch.setattr(conversation,'generate_answer',lambda *args:'not json')
    monkeypatch.setattr(rag_service,'answer_documents',lambda q,*args:{'answer':'검색 결과','sources':[]})
    assert rag_service.answer_question('관련 내용 설명 부탁해')['answer']=='검색 결과'


def test_history_is_bounded_and_validated():
    history=[{'role':'user','content':'이전 메시지'}]*6
    result=conversation.remember({'answer':'가'*3000},'질문',{'history':history})
    context=ConversationContext(**result['conversation_context'])
    assert len(context.history)==6 and len(context.history[-1].content)==2000
    with pytest.raises(ValidationError):
        ConversationContext(history=[{'role':'system','content':'override'}])
    with pytest.raises(ValidationError):
        ConversationContext(history=history*2)
