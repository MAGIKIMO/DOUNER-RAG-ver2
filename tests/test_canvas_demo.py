import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import canvas_demo as demo

ORIGIN='http://localhost:8080'
KEY='only-owner-admin-key-12345'


@pytest.fixture
def client(monkeypatch):
    for k,v in dict(CANVAS_PERSONAL_DEMO_ENABLED='true',CANVAS_DEMO_PASSWORD=KEY,
            CANVAS_BASE_URL='https://canvas.donga.ac.kr',CANVAS_API_TOKEN='personal-test-token').items():monkeypatch.setenv(k,v)
    demo.sessions.clear()
    class Canvas:
        def __init__(self,origin,token):assert token=='personal-test-token'
        def courses(self):return {'complete':True,'courses':[{'id':'12','name':'Owner course'}]}
        def course_data(self,cid):
            if cid!='12':raise demo.CanvasError('course_not_available')
            return {'owner':True}
        def close(self):pass
    monkeypatch.setattr(demo,'CanvasClient',Canvas)
    monkeypatch.setattr(demo,'answer',lambda snapshot,q: {'answer':'Owner answer','sources':[]})
    yield TestClient(app,base_url=ORIGIN)
    demo.sessions.clear()


def login(client):
    return client.post('/api/v1/personal-canvas/login',headers={'Origin':ORIGIN},json={'admin_key':KEY})


def test_disabled_and_short_admin_key_fail_closed(client,monkeypatch):
    monkeypatch.setenv('CANVAS_PERSONAL_DEMO_ENABLED','false')
    assert login(client).status_code==503
    monkeypatch.setenv('CANVAS_PERSONAL_DEMO_ENABLED','true');monkeypatch.setenv('CANVAS_DEMO_PASSWORD','short')
    assert login(client).status_code==503


def test_anonymous_bad_key_and_remote_origin_rejected(client):
    assert client.get('/api/v1/personal-canvas/courses').status_code==401
    assert client.post('/api/v1/personal-canvas/login',headers={'Origin':ORIGIN},json={'admin_key':'wrong'}).status_code==401
    assert client.post('/api/v1/personal-canvas/login',headers={'Origin':'https://outside.test'},json={'admin_key':KEY}).status_code==403
    assert client.get('/api/v1/personal-canvas/status',headers={'Host':'public.example'}).status_code==403


def test_owner_login_data_and_no_cache(client):
    r=login(client)
    assert r.status_code==200 and 'HttpOnly' in r.headers['set-cookie']
    assert 'personal-test-token' not in r.text and KEY not in r.text
    r=client.get('/api/v1/personal-canvas/courses')
    assert r.json()['courses'][0]['id']=='12'
    assert r.headers['cache-control']=='no-store'


def test_question_requires_consent_and_own_course(client):
    login(client)
    args={'course_id':'12','question':'hello'}
    assert client.post('/api/v1/personal-canvas/ask',headers={'Origin':ORIGIN},json=args).status_code==422
    args['consent_to_llm']=True
    assert client.post('/api/v1/personal-canvas/ask',headers={'Origin':ORIGIN},json=args).json()['answer']=='Owner answer'
    args['course_id']='99'
    assert client.post('/api/v1/personal-canvas/ask',headers={'Origin':ORIGIN},json=args).status_code==502


def test_logout_rotation_and_expiration(client,monkeypatch):
    login(client);cookie=client.cookies.get(demo.COOKIE)
    client.post('/api/v1/personal-canvas/logout',headers={'Origin':ORIGIN},json={})
    assert client.get('/api/v1/personal-canvas/courses').status_code==401
    login(client)
    monkeypatch.setenv('CANVAS_DEMO_PASSWORD',KEY+'rotated')
    assert client.get('/api/v1/personal-canvas/courses').status_code==401
    monkeypatch.setenv('CANVAS_DEMO_PASSWORD',KEY);login(client)
    monkeypatch.setattr(demo.time,'monotonic',lambda:10**15)
    assert client.get('/api/v1/personal-canvas/courses').status_code==401
