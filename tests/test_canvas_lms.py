import json
from datetime import datetime
import httpx
import pytest
from app import canvas_lms as canvas, rag_service, db

ORIGIN = 'https://canvas.donga.ac.kr'  # Synthetic test host, not a verified production address.
TOKEN = 'test-personal-token'


def response(data, **kwargs):
    return httpx.Response(200,json=data,**kwargs)


def client(handler):
    return canvas.CanvasClient(ORIGIN,TOKEN,transport=httpx.MockTransport(handler))


def course():
    return {'id':'12','name':'테스트 과목','course_code':'TEST','term':{'name':'테스트 학기'}}


def fixture_handler(request):
    assert request.method == 'GET'
    assert request.headers['Authorization'] == 'Bearer '+TOKEN
    assert TOKEN not in str(request.url)
    if request.url.path == '/api/v1/courses':
        assert request.url.params['enrollment_type']=='student'
        return response([course()])
    if request.url.path == '/api/v1/announcements':
        assert request.url.params['context_codes[]']=='course_12'
        assert 'start_date' in request.url.params
        return response([{'id':'7','context_code':'course_12','title':'시험 안내','message':'<p>테스트 시험 범위는 1장입니다.</p>',
            'posted_at':'2026-09-16T23:00:00Z','author':{'display_name':'Not retained'}}])
    if request.url.path == '/api/v1/courses/12/assignments':
        assert request.url.params['include[]']=='submission'
        return response([{'id':'4','course_id':'12','name':'첫 과제','description':'<p>테스트 보고서 제출</p><script>bad()</script>',
            'due_at':'2026-09-20T14:59:00Z','submission':{'workflow_state':'submitted','submitted_at':'2026-09-17T00:00:00Z',
            'score':99,'grade':'A','user_id':'456','submission_comments':['private']},'html_url':'https://evil.example/'}])
    raise AssertionError('Unexpected endpoint')


def test_course_data_is_read_only_sanitized_and_korea_time():
    api=client(fixture_handler)
    try:
        data=api.course_data('12')
        assert data['coverage']=={'announcements':'complete','assignments':'complete'}
        item=data['assignments'][0]
        assert item['due_at']=='2026-09-20T23:59:00+09:00'
        assert item['submission_state']=='submitted'
        assert item['url']==ORIGIN+'/courses/12/assignments/4'
        assert 'bad()' not in item['text']
        assert all(s not in json.dumps(data) for s in [TOKEN,'submission_comments','score','grade','Not retained','evil.example'])
    finally:api.close()


def test_profile_output_does_not_expose_email_or_login():
    api=client(lambda r:response({'id':'123','name':'Private name','primary_email':'private@example.org','login_id':'student'}))
    try:assert api.check()=={'status':'connected','canvas_user_id':'123','mode':'personal_cli_read_only'}
    finally:api.close()


def test_pagination_follows_same_endpoint_and_keeps_all_rows():
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.params.get('page')=='2':return response([{'id':'13','name':'두 번째'}])
        return response([course()],headers={'Link':f'<{ORIGIN}/api/v1/courses?page=2>; rel="next"'})
    api=client(handler)
    try:
        result=api.courses()
        assert len(result['courses'])==2 and result['complete']
        assert len(calls)==2
    finally:api.close()


@pytest.mark.parametrize('next_url',['https://evil.example/api/v1/courses?page=2',ORIGIN+'/api/v1/users/self/profile',ORIGIN+'/api/v1/courses?access_token=echo'])
def test_pagination_does_not_leak_token_or_switch_endpoint(next_url):
    calls=[]
    def handler(request):
        calls.append(request)
        return response([course()],headers={'Link':f'<{next_url}>; rel="next"'})
    api=client(handler)
    try:
        with pytest.raises(canvas.CanvasError,match='unsafe_pagination'):api.courses()
        assert len(calls)==1
    finally:api.close()


@pytest.mark.parametrize('status,code',[(302,'redirect_blocked'),(401,'authentication_failed'),(403,'permission_denied'),(404,'not_found'),(429,'rate_limited'),(500,'upstream_error')])
def test_errors_do_not_include_upstream_secrets(status,code):
    api=client(lambda r:httpx.Response(status,text=TOKEN,headers={'Location':'https://evil.example'}))
    try:
        with pytest.raises(canvas.CanvasError) as exc:api.check()
        assert str(exc.value)==code and TOKEN not in str(exc.value)
    finally:api.close()


def test_partial_failure_is_not_reported_as_no_announcements():
    api=client(lambda r:httpx.Response(403) if r.url.path=='/api/v1/announcements' else fixture_handler(r))
    try:
        result=api.course_data('12')
        assert result['coverage']['announcements']=='permission_denied'
        assert result['assignments']
    finally:api.close()


def test_other_course_is_not_fetched():
    calls=[]
    def handler(r):calls.append(r);return response([course()])
    api=client(handler)
    try:
        with pytest.raises(canvas.CanvasError,match='course_not_available'):api.course_data('99')
        assert len(calls)==1
    finally:api.close()


@pytest.mark.parametrize('origin',['http://canvas.donga.ac.kr','https://canvas.donga.ac.kr.evil.example','https://user:secret@canvas.donga.ac.kr','https://canvas.donga.ac.kr/profile','https://canvas.donga.ac.kr?token=secret'])
def test_base_url_is_an_official_https_origin(origin):
    with pytest.raises(canvas.CanvasError,match='invalid_base_url'):canvas.base_url(origin)


def test_missing_token_is_actionable():
    with pytest.raises(canvas.CanvasError,match='missing_token'):canvas.CanvasClient(ORIGIN,'')


def test_personal_answer_uses_body_without_shared_database(monkeypatch):
    api=client(fixture_handler)
    try:snapshot=api.course_data('12')
    finally:api.close()
    monkeypatch.setattr(db,'session_scope',lambda:pytest.fail('Personal data reached shared DB'))
    def generate(system,user):
        payload=json.loads(user)
        assert TOKEN not in user
        source=next(d for d in payload['documents'] if '테스트 보고서 제출' in d['text'])
        return f'보고서를 제출하는 과제입니다. [{source["source"]}]'
    monkeypatch.setattr(rag_service,'generate_answer',generate)
    result=canvas.answer(snapshot,'과제 뭐 해야 해?')
    assert result['status']=='ok' and '보고서' in result['answer']


def test_context_limit_is_explicit():
    api=client(fixture_handler)
    try:snapshot=api.course_data('12')
    finally:api.close()
    snapshot['assignments']*=200
    docs,sources=canvas.evidence(snapshot,'과제',max_chars=4000)
    inventory=json.loads(docs[0]['text'])
    assert inventory['inventory_truncated'] is True
    assert sum(len(d['text']) for d in docs)<=4000


def test_page_limit_and_html_response(monkeypatch):
    monkeypatch.setattr(canvas,'MAX_PAGES',1)
    api=client(lambda r:response([course()],headers={'Link':f'<{ORIGIN}/api/v1/courses?page=2>; rel="next"'}))
    try:assert api.courses()['complete'] is False
    finally:api.close()
    api=client(lambda r:httpx.Response(200,text='<html>Login</html>',headers={'Content-Type':'text/html'}))
    try:
        with pytest.raises(canvas.CanvasError,match='unexpected_response'):api.check()
    finally:api.close()
