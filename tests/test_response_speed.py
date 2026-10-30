import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app import response_trace as trace, conversation, rag_service, query_language, llm_provider, main

def test_clear_school_query_skips_classifier(monkeypatch):
    monkeypatch.setattr(conversation,'classify_social',lambda *a:pytest.fail('extra classifier call'))
    monkeypatch.setattr(rag_service,'answer_documents',lambda *a:{'answer':'답변','sources':[]})
    result=rag_service.answer_question('장학금 신청 기간 알려줘')
    assert 'total' in result['debug_info']['timings_ms']

def test_translation_routes_once(monkeypatch):
    monkeypatch.setattr(query_language,'generate_answer',lambda *a:'{"query":"장학금 신청 기간 알려줘","route":"retrieve"}')
    monkeypatch.setattr(conversation,'classify_social',lambda *a:pytest.fail('extra classifier'))
    monkeypatch.setattr(rag_service,'answer_documents',lambda *a:{'answer':'Answer','sources':[]})
    assert rag_service.answer_question('When can I apply for a scholarship?')['answer']=='Answer'

def test_paragraphs_buffer_invalid_citations_and_retry_reset():
    events=[]; token=trace.SINK.set(events.append)
    try:
        sink=trace.CitedParagraphs(2)
        sink('Valid [1'); assert not events
        sink('].\n\nInvalid [99].\n\n')
        assert len(events)==1 and events[0]['text']=='Valid [1].\n\n'
        sink('More [2].\n\n');assert len(events)==1
    finally:trace.SINK.reset(token)

def test_gemini_stream_ignores_thoughts_and_requires_completion(monkeypatch):
    chunks=[{'candidates':[{'content':{'parts':[{'text':'hidden','thought':True},{'text':'Answer [1].\n\n'}]}}]}, {'candidates':[{'finishReason':'STOP','content':{'parts':[]}}]}]
    transport=httpx.MockTransport(lambda req:httpx.Response(200,text=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)))
    original=httpx.Client
    monkeypatch.setattr(llm_provider.httpx,'Client',lambda **kw:original(transport=transport,**kw))
    received=[]
    answer=llm_provider.Provider('gemini')._stream_gemini('https://example.com',{}, {},received.append,5)
    assert answer=='Answer [1].' and ''.join(received)=='Answer [1].\n\n'
    chunks.pop()
    with pytest.raises(llm_provider.LLMError,match='incomplete_response'):
        llm_provider.Provider('gemini')._stream_gemini('https://example.com',{}, {},received.append,5)

def test_stream_endpoint_events_and_slot_release(monkeypatch):
    def answer(*a):
        trace.emit('answer_delta',text='Answer [1].\n\n')
        return {'answer':'Answer [1].','sources':[]}
    monkeypatch.setattr(main,'answer_question',answer)
    client=TestClient(main.app)
    response=client.post('/api/v1/ask/stream',json={'question':'hello'})
    events=[json.loads(line) for line in response.text.splitlines()]
    assert events[0]['type']=='answer_delta' and events[-1]['type']=='result'
    assert response.headers['x-accel-buffering']=='no'
    assert main.ask_slots.acquire(blocking=False)
    main.ask_slots.release()


def test_grouped_citations_do_not_trigger_retry(monkeypatch):
    calls = []
    def generate(*args):
        calls.append(1)
        return '시험은 오후입니다 [1, 2].'
    monkeypatch.setattr(rag_service, 'generate_answer', generate)
    assert rag_service.grounded_answer('', '', 2, 'ko')[1] == 'ok'
    assert len(calls) == 1
    monkeypatch.setattr(rag_service, 'generate_answer', lambda *args: '시험입니다 [1, 99].')
    assert rag_service.grounded_answer('', '', 2, 'ko')[1] == 'unverified_answer'


def test_api_preserves_exam_context():
    value = main.AskRequest(question='02분반은?', conversation_context={'exam_question':'컴공 운영체제 중간고사'})
    assert value.conversation_context.exam_question == '컴공 운영체제 중간고사'


@pytest.mark.parametrize('code,expected_calls', [('provider_unavailable',2),('quota_exceeded',1),('authentication_failed',1),('incomplete_response',1)])
def test_stream_retry_only_transient_http_errors(monkeypatch, code, expected_calls):
    monkeypatch.setenv('GEMINI_API_KEY','test-key')
    monkeypatch.setattr(llm_provider.time,'sleep',lambda _:None)
    calls = []
    def stream(self, url, headers, payload, consumer, timeout):
        calls.append(timeout)
        raise llm_provider.LLMError(code)
    monkeypatch.setattr(llm_provider.Provider,'_stream_gemini',stream)
    token = trace.TOKENS.set(lambda _: None)
    try:
        with pytest.raises(llm_provider.LLMError,match=code):
            llm_provider.Provider('gemini').generate_answer('','')
    finally:
        trace.TOKENS.reset(token)
    assert len(calls) == expected_calls
    if len(calls) == 2: assert calls[1] <= calls[0]


def test_stream_recovers_after_one_temporary_error(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','test-key')
    monkeypatch.setattr(llm_provider.time,'sleep',lambda _:None)
    calls=[]
    def stream(self,*args):
        calls.append(1)
        if len(calls)==1: raise llm_provider.LLMError('provider_unavailable')
        return 'Answer [1].'
    monkeypatch.setattr(llm_provider.Provider,'_stream_gemini',stream)
    token=trace.TOKENS.set(lambda _:None)
    try:
        assert llm_provider.Provider('gemini').generate_answer('','') == 'Answer [1].'
    finally:trace.TOKENS.reset(token)
    assert len(calls)==2
