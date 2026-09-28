from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.pool import StaticPool
from app import db, canvas_oauth as oauth
from app.main import app

PUBLIC='https://app.example.test'
real_token_request=oauth.token_request


@pytest.fixture
def setup(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    monkeypatch.setattr(db,'engine',lambda:engine)
    db.init_db()
    for key,value in dict(CANVAS_OAUTH_ENABLED='true',APP_PUBLIC_ORIGIN=PUBLIC,
        CANVAS_BASE_URL='https://canvas.donga.ac.kr',CANVAS_CLIENT_ID='client',CANVAS_CLIENT_SECRET='secret',
        CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),CANVAS_API_TOKEN='must-not-be-used').items():
        monkeypatch.setenv(key,value)
    calls=[]
    def tokens(cfg,fields):
        calls.append(fields)
        uid=fields.get('code') or fields['refresh_token'].removeprefix('refresh-')
        return dict(access_token='access-'+uid,refresh_token='refresh-'+uid,expires_in=3600)
    monkeypatch.setattr(oauth,'token_request',tokens)
    class Client:
        def __init__(self,origin,token):
            assert token!='must-not-be-used'
            self.uid=token.removeprefix('access-')
            self.client=self
        def check(self):return {'canvas_user_id':self.uid}
        def close(self):pass
        def courses(self):return {'complete':True,'courses':[{'id':self.uid,'name':'Own course'}]}
        def course_data(self,cid):
            if cid!=self.uid:raise oauth.CanvasError('course_not_available')
            return {'owner':self.uid}
        def delete(self,url):return httpx.Response(200)
    monkeypatch.setattr(oauth,'CanvasClient',Client)
    yield TestClient(app,base_url=PUBLIC),calls
    engine.dispose()


def begin(client):
    r=client.post('/api/v1/canvas/start',json={},headers={'Origin':PUBLIC})
    assert r.status_code==200
    state=parse_qs(urlsplit(r.json()['authorize_url']).query)['state'][0]
    return state,r


def login(client,uid='101'):
    state,_=begin(client)
    r=client.get('/api/v1/canvas/callback',params={'state':state,'code':uid},follow_redirects=False)
    assert r.status_code==303 and r.headers['location'].endswith('connected')
    return state,r


def test_oauth_disabled_fails_closed(setup,monkeypatch):
    client,_=setup;monkeypatch.setenv('CANVAS_OAUTH_ENABLED','false')
    assert client.get('/api/v1/canvas/status').json()=={'configured':False,'authenticated':False}
    assert client.post('/api/v1/canvas/start',headers={'Origin':PUBLIC}).status_code==503


def test_start_requires_exact_origin_and_scopes(setup):
    client,_=setup
    assert client.post('/api/v1/canvas/start',headers={'Origin':'https://evil.test'}).status_code==403
    _,r=begin(client)
    q=parse_qs(urlsplit(r.json()['authorize_url']).query)
    assert q['redirect_uri']==[PUBLIC+oauth.CALLBACK]
    assert set(q['scope'][0].split())==set(oauth.SCOPES)
    assert 'secret' not in r.text
    cookie=r.headers['set-cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=lax' in cookie


def test_callback_browser_binding_and_single_use(setup):
    client,calls=setup
    state,_=begin(client)
    stranger=TestClient(app,base_url=PUBLIC)
    r=stranger.get(oauth.CALLBACK,params={'state':state,'code':'101'},follow_redirects=False)
    assert r.headers['location'].endswith('failed') and not calls
    r=client.get(oauth.CALLBACK,params={'state':state,'code':'101'},follow_redirects=False)
    assert r.headers['location'].endswith('connected')
    r=client.get(oauth.CALLBACK,params={'state':state,'code':'101'},follow_redirects=False)
    assert r.headers['location'].endswith('failed') and len(calls)==1


def test_expired_state_and_denial_do_not_exchange(setup):
    client,calls=setup;state,_=begin(client)
    with db.session_scope() as s:s.get(oauth.OAuthAttempt,db.digest(state)).expires=db.utcnow()-timedelta(seconds=1)
    assert client.get(oauth.CALLBACK,params={'state':state,'code':'101'},follow_redirects=False).headers['location'].endswith('failed')
    state,_=begin(client)
    client.get(oauth.CALLBACK,params={'state':state,'error':'access_denied'},follow_redirects=False)
    assert not calls


def test_tokens_encrypted_and_session_hashed(setup):
    client,_=setup;_,r=login(client)
    token=client.cookies.get(oauth.SESSION_COOKIE)
    with db.session_scope() as s:
        row=s.scalar(select(oauth.CanvasAccount))
        assert 'access-101' not in row.access and 'refresh-101' not in row.refresh
        assert s.get(oauth.CanvasSession,db.digest(token)) is not None
        assert s.get(oauth.CanvasSession,token) is None
        assert s.scalar(select(func.count(db.Notice.id)))==0
        assert s.scalar(select(func.count(db.ChatHistory.id)))==0
    assert r.headers['Cache-Control']=='no-store'
    assert r.headers['Referrer-Policy']=='no-referrer'


def test_two_users_cannot_choose_each_others_account(setup):
    a,_=setup;b=TestClient(app,base_url=PUBLIC)
    login(a,'101');login(b,'202')
    assert a.get('/api/v1/canvas/courses?account_id=2').json()['courses'][0]['id']=='101'
    assert b.get('/api/v1/canvas/courses?account_id=1').json()['courses'][0]['id']=='202'
    assert a.post('/api/v1/canvas/ask',headers={'Origin':PUBLIC},json={'course_id':'202','question':'hello','consent_to_llm':True}).status_code==502


def test_ask_consent_and_no_shared_storage(setup,monkeypatch):
    client,_=setup;login(client)
    seen=[]
    monkeypatch.setattr(oauth,'answer',lambda snapshot,question:seen.append(snapshot) or {'answer':'ok'})
    body={'course_id':'101','question':'hello'}
    assert client.post('/api/v1/canvas/ask',headers={'Origin':PUBLIC},json=body).status_code==422
    assert not seen
    body['consent_to_llm']=True
    assert client.post('/api/v1/canvas/ask',headers={'Origin':PUBLIC},json=body).json()['answer']=='ok'
    assert seen==[{'owner':'101'}]
    with db.session_scope() as s:assert s.scalar(select(func.count(db.ChatHistory.id)))==0


def test_refresh_and_logout_invalidate_session(setup):
    client,calls=setup;login(client)
    with db.session_scope() as s:s.scalar(select(oauth.CanvasAccount)).expires=db.utcnow()
    assert client.get('/api/v1/canvas/courses').status_code==200
    assert calls[-1]=={'grant_type':'refresh_token','refresh_token':'refresh-101'}
    cookie=client.cookies.get(oauth.SESSION_COOKIE)
    assert client.post('/api/v1/canvas/logout',headers={'Origin':'https://evil.test'}).status_code==403
    assert client.post('/api/v1/canvas/logout',headers={'Origin':PUBLIC}).status_code==200
    client.cookies.set(oauth.SESSION_COOKIE,cookie)
    assert client.get('/api/v1/canvas/courses').status_code==401


def test_disconnect_deletes_tokens_and_all_sessions(setup):
    client,_=setup;login(client)
    result=client.post('/api/v1/canvas/disconnect',headers={'Origin':PUBLIC})
    assert result.json()=={'disconnected':True,'remote_revoked':True}
    with db.session_scope() as s:
        assert s.scalar(select(func.count(oauth.CanvasAccount.id)))==0
        assert s.scalar(select(func.count(oauth.CanvasSession.token_hash)))==0


def test_encryption_is_bound_to_identity(setup):
    cfg=oauth.configuration()
    encrypted=oauth.encrypt(cfg,'owner-a','token')
    with pytest.raises(oauth.HTTPException):oauth.decrypt(cfg,'owner-b',encrypted)


def test_callback_exchange_failure_is_sanitized(setup,monkeypatch):
    client,_=setup;state,_=begin(client)
    def fail(*a):raise oauth.HTTPException(502,'fixed')
    monkeypatch.setattr(oauth,'token_request',fail)
    r=client.get(oauth.CALLBACK,params={'state':state,'code':'sensitive-code'},follow_redirects=False)
    assert r.headers['location']=='/account.html?oauth=failed'
    assert 'sensitive-code' not in r.text


@pytest.mark.parametrize('reply', [httpx.Response(302,headers={'location':'https://evil.test'}),httpx.Response(200,json=[]),httpx.Response(200,content=b'x'*70000)])
def test_token_exchange_rejects_redirects_malformed_and_large_responses(setup,monkeypatch,reply):
    real_client=httpx.Client
    calls=[]
    def handle(request):
        calls.append(request)
        assert str(request.url)=='https://canvas.donga.ac.kr/login/oauth2/token'
        assert 'secret' not in str(request.url)
        return reply
    monkeypatch.setattr(oauth.httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw))
    with pytest.raises(oauth.HTTPException) as exc:
        real_token_request(oauth.configuration(),{'grant_type':'authorization_code','code':'private-code'})
    assert exc.value.status_code==502 and len(calls)==1
    assert 'private-code' not in str(exc.value.detail)


def test_refresh_preserves_original_refresh_token_when_omitted(setup,monkeypatch):
    client,_=setup;login(client)
    with db.session_scope() as s:
        row=s.scalar(select(oauth.CanvasAccount));row.expires=db.utcnow();old=row.refresh
    monkeypatch.setattr(oauth,'token_request',lambda *args:dict(access_token='access-101',expires_in=3600))
    assert client.get('/api/v1/canvas/courses').status_code==200
    with db.session_scope() as s:assert s.scalar(select(oauth.CanvasAccount)).refresh==old


def test_expired_session_cannot_use_personal_env_token(setup):
    client,_=setup;login(client)
    with db.session_scope() as s:s.scalar(select(oauth.CanvasSession)).expires=db.utcnow()-timedelta(seconds=1)
    r=client.get('/api/v1/canvas/courses')
    assert r.status_code==401 and r.headers['Cache-Control']=='no-store'
