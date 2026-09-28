"""Canvas OAuth membership and private, session-bound LMS access."""
import json
import os
import secrets
import threading
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, delete, select
from sqlalchemy.exc import IntegrityError
from .db import Base, digest, session_scope, utcnow
from .canvas_lms import CanvasClient, CanvasError, answer, base_url

router = APIRouter(prefix='/api/v1/canvas')
SESSION_COOKIE = '__Host-donga_session'
STATE_COOKIE = '__Host-donga_oauth'
CALLBACK = '/api/v1/canvas/callback'
SCOPES = ['url:GET|/api/v1/users/:user_id/profile', 'url:GET|/api/v1/courses',
          'url:GET|/api/v1/announcements', 'url:GET|/api/v1/courses/:course_id/assignments']
slots = threading.BoundedSemaphore(2)


class CanvasAccount(Base):
    __tablename__ = 'canvas_accounts'
    __table_args__ = (UniqueConstraint('origin', 'canvas_id'),)
    id = Column(Integer, primary_key=True)
    origin = Column(String(255), nullable=False)
    canvas_id = Column(String(100), nullable=False)
    access = Column(Text, nullable=False)
    refresh = Column(Text, nullable=False)
    expires = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class CanvasSession(Base):
    __tablename__ = 'canvas_sessions'
    token_hash = Column(String(64), primary_key=True)
    account_id = Column(Integer, ForeignKey('canvas_accounts.id'), nullable=False)
    expires = Column(DateTime, nullable=False)


class OAuthAttempt(Base):
    __tablename__ = 'canvas_oauth_attempts'
    state_hash = Column(String(64), primary_key=True)
    browser_hash = Column(String(64), nullable=False)
    expires = Column(DateTime, nullable=False)


def configuration():
    try:
        if os.getenv('CANVAS_OAUTH_ENABLED', 'false').lower() != 'true':
            raise ValueError()
        public = os.environ['APP_PUBLIC_ORIGIN'].rstrip('/')
        p = urlsplit(public)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.path or p.query or p.fragment:
            raise ValueError()
        origin = base_url(os.environ['CANVAS_BASE_URL'])
        client_id, secret = os.environ['CANVAS_CLIENT_ID'], os.environ['CANVAS_CLIENT_SECRET']
        if not client_id.strip() or not secret.strip():
            raise ValueError()
        cipher = Fernet(os.environ['CANVAS_TOKEN_ENCRYPTION_KEY'].encode())
        return dict(public=public, origin=origin, client_id=client_id, secret=secret, cipher=cipher,
                    callback=public+CALLBACK)
    except (KeyError, ValueError, CanvasError):
        raise HTTPException(503, 'Canvas 연동 준비 중입니다. 학교 앱 승인과 HTTPS 설정이 필요합니다.') from None


def same_origin(request, cfg):
    if request.headers.get('origin') != cfg['public']:
        raise HTTPException(403, '요청 출처를 확인하지 못했습니다.')


def token_request(cfg, fields):
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            with client.stream('POST', cfg['origin']+'/login/oauth2/token', data={
                    'client_id': cfg['client_id'], 'client_secret': cfg['secret'], **fields}) as r:
                if r.status_code != 200:
                    raise ValueError()
                data = bytearray()
                for part in r.iter_bytes():
                    data.extend(part)
                    if len(data) > 65536:
                        raise ValueError()
                result = json.loads(data)
        if not isinstance(result, dict) or not isinstance(result.get('access_token'), str) or not result['access_token']:
            raise ValueError()
        lifetime = int(result['expires_in'])
        if not 0 < lifetime <= 86400:
            raise ValueError()
        return result
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, 'Canvas 인증을 완료하지 못했습니다. 다시 연결해 주세요.') from None


def encrypt(cfg, account_key, value):
    return cfg['cipher'].encrypt(json.dumps([account_key, value]).encode()).decode()


def decrypt(cfg, account_key, value):
    try:
        owner, token = json.loads(cfg['cipher'].decrypt(value.encode()))
        if owner != account_key or not isinstance(token, str):
            raise ValueError()
        return token
    except (InvalidToken, ValueError, TypeError):
        raise HTTPException(503, '저장된 연결 정보를 읽지 못했습니다. 운영자에게 문의해 주세요.') from None


def account_id(request):
    token = request.cookies.get(SESSION_COOKIE, '')
    if not token or len(token) > 200:
        raise HTTPException(401, 'Canvas로 로그인해 주세요.')
    with session_scope() as db:
        session = db.get(CanvasSession, digest(token))
        if not session or session.expires <= utcnow():
            raise HTTPException(401, '로그인이 만료되었습니다. 다시 로그인해 주세요.')
        return session.account_id


def private_client(request, cfg):
    owner = account_id(request)
    # Serialize refreshes for the same account across workers (MySQL row lock).
    with session_scope() as db:
        row = db.scalar(select(CanvasAccount).where(CanvasAccount.id == owner).with_for_update())
        if not row or row.origin != cfg['origin']:
            raise HTTPException(401, 'LMS를 다시 연결해 주세요.')
        key = row.origin+'|'+row.canvas_id
        if row.expires <= utcnow()+timedelta(seconds=60):
            result = token_request(cfg, {'grant_type':'refresh_token', 'refresh_token':decrypt(cfg, key, row.refresh)})
            row.access = encrypt(cfg, key, result['access_token'])
            if result.get('refresh_token'):
                row.refresh = encrypt(cfg, key, result['refresh_token'])
            row.expires = utcnow()+timedelta(seconds=int(result['expires_in']))
        token = decrypt(cfg, key, row.access)
    return CanvasClient(cfg['origin'], token)


@router.get('/status')
def status(request: Request):
    try:
        configuration()
    except HTTPException:
        return {'configured':False, 'authenticated':False}
    try:
        account_id(request)
        return {'configured':True, 'authenticated':True}
    except HTTPException:
        return {'configured':True, 'authenticated':False}


@router.post('/start')
def start(request: Request):
    cfg = configuration(); same_origin(request, cfg)
    state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with session_scope() as db:
        db.execute(delete(OAuthAttempt).where(OAuthAttempt.expires <= utcnow()))
        db.execute(delete(CanvasSession).where(CanvasSession.expires <= utcnow()))
        db.add(OAuthAttempt(state_hash=digest(state), browser_hash=digest(browser), expires=utcnow()+timedelta(minutes=10)))
    url = cfg['origin']+'/login/oauth2/auth?'+urlencode(dict(client_id=cfg['client_id'], response_type='code',
               redirect_uri=cfg['callback'], state=state, scope=' '.join(SCOPES)))
    response = JSONResponse({'authorize_url':url})
    response.set_cookie(STATE_COOKIE, browser, max_age=600, secure=True, httponly=True, samesite='lax', path='/')
    return response


@router.get('/callback')
def callback(request: Request, state: str = '', code: str = '', error: str = ''):
    cfg = configuration()
    response = RedirectResponse('/account.html?oauth=failed', status_code=303)
    response.delete_cookie(STATE_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    browser = request.cookies.get(STATE_COOKIE, '')
    if not state or len(state)>200 or not browser or len(browser)>200:
        return response
    with session_scope() as db:
        used = db.execute(delete(OAuthAttempt).where(OAuthAttempt.state_hash == digest(state),
            OAuthAttempt.browser_hash == digest(browser), OAuthAttempt.expires > utcnow()))
        valid = used.rowcount == 1
    if not valid or error or not code or len(code)>4096:
        return response
    try:
        result = token_request(cfg, {'grant_type':'authorization_code', 'code':code, 'redirect_uri':cfg['callback']})
        if not isinstance(result.get('refresh_token'), str) or not result['refresh_token']:
            return response
        client = CanvasClient(cfg['origin'], result['access_token'])
        try:
            identity = client.check()['canvas_user_id']
        finally:
            client.close()
        if not identity or len(identity)>100:
            return response
        key = cfg['origin']+'|'+identity
        session_token = secrets.token_urlsafe(32)
        with session_scope() as db:
            row = db.scalar(select(CanvasAccount).where(CanvasAccount.origin == cfg['origin'],
                            CanvasAccount.canvas_id == identity).with_for_update())
            if not row:
                row = CanvasAccount(origin=cfg['origin'], canvas_id=identity)
                db.add(row)
            row.access = encrypt(cfg, key, result['access_token'])
            row.refresh = encrypt(cfg, key, result['refresh_token'])
            row.expires = utcnow()+timedelta(seconds=int(result['expires_in']))
            db.flush()
            # A fresh authorization invalidates older local sessions.
            db.execute(delete(CanvasSession).where(CanvasSession.account_id == row.id))
            db.add(CanvasSession(token_hash=digest(session_token), account_id=row.id, expires=utcnow()+timedelta(days=7)))
        response.headers['location'] = '/account.html?oauth=connected'
        response.set_cookie(SESSION_COOKIE, session_token, max_age=604800, secure=True, httponly=True, samesite='lax', path='/')
    except (HTTPException, CanvasError, IntegrityError):
        pass
    return response


@router.post('/logout')
def logout(request: Request):
    cfg=configuration(); same_origin(request,cfg)
    with session_scope() as db:
        db.execute(delete(CanvasSession).where(CanvasSession.token_hash == digest(request.cookies.get(SESSION_COOKIE,''))))
    response=JSONResponse({'logged_out':True})
    response.delete_cookie(SESSION_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    return response


@router.post('/disconnect')
def disconnect(request: Request):
    cfg=configuration(); same_origin(request,cfg)
    owner=account_id(request)
    revoked=False
    try:
        client=private_client(request,cfg)
        try:
            r=client.client.delete(cfg['origin']+'/login/oauth2/token')
            revoked=r.status_code in (200,204)
        finally:
            client.close()
    except (HTTPException, CanvasError, httpx.HTTPError):
        pass
    with session_scope() as db:
        db.execute(delete(CanvasSession).where(CanvasSession.account_id == owner))
        db.execute(delete(CanvasAccount).where(CanvasAccount.id == owner))
    response=JSONResponse({'disconnected':True,'remote_revoked':revoked})
    response.delete_cookie(SESSION_COOKIE, path='/', secure=True, httponly=True, samesite='lax')
    return response


def read_private(request, action):
    cfg=configuration()
    client=private_client(request,cfg)
    try:
        return action(client)
    except CanvasError as exc:
        code=str(exc)
        raise HTTPException(401 if code=='authentication_failed' else 502,
            'LMS 조회에 실패했습니다. 다시 연결하거나 잠시 후 시도해 주세요.') from None
    finally:
        client.close()


@router.get('/courses')
def courses(request: Request):
    return read_private(request, lambda client:client.courses())


class PrivateQuestion(BaseModel):
    course_id: str = Field(pattern=r'^[1-9][0-9]{0,19}$')
    question: str = Field(min_length=1, max_length=2000)
    consent_to_llm: bool = False


@router.post('/ask')
def ask(request: Request, body: PrivateQuestion):
    cfg=configuration(); same_origin(request,cfg)
    if not body.consent_to_llm:
        raise HTTPException(422, '선택한 과목 자료를 AI 제공자에게 전송하는 데 동의해 주세요.')
    if not body.question.strip():
        raise HTTPException(422, '질문을 입력해 주세요.')
    if not slots.acquire(blocking=False):
        raise HTTPException(429, '요청이 많습니다. 잠시 후 다시 시도해 주세요.')
    try:
        return read_private(request, lambda client:answer(client.course_data(body.course_id),body.question))
    finally:
        slots.release()
