"""Owner-only localhost demo. Personal token never participates in OAuth routes."""
import os
import secrets
import threading
import time
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .canvas_lms import CanvasClient, CanvasError, answer, base_url
from .canvas_oauth import PrivateQuestion
from .db import digest

router = APIRouter(prefix='/api/v1/personal-canvas')
COOKIE = 'donga_personal_demo'
COOKIE_PATH = '/api/v1/personal-canvas'
ORIGIN = 'http://localhost:8080'
sessions = {}
lock = threading.Lock()
slots = threading.BoundedSemaphore(1)


def configuration(request):
    # This demonstration deliberately cannot be used through a public tunnel.
    if request.headers.get('host') != 'localhost:8080':
        raise HTTPException(403, '본인 데모는 PC의 http://localhost:8080 에서만 사용합니다.')
    if request.method != 'GET' and request.headers.get('origin') != ORIGIN:
        raise HTTPException(403, '로컬 화면에서 다시 요청해 주세요.')
    key = os.getenv('CANVAS_DEMO_PASSWORD', '')
    token = os.getenv('CANVAS_API_TOKEN', '')
    if os.getenv('CANVAS_PERSONAL_DEMO_ENABLED', 'false').lower() != 'true' or len(key)<16 or not token:
        raise HTTPException(503, '본인 LMS 데모가 비활성 상태이거나 설정이 부족합니다.')
    try:
        origin=base_url(os.getenv('CANVAS_BASE_URL',''))
    except CanvasError:
        raise HTTPException(503, 'Canvas 주소 설정을 확인해 주세요.') from None
    return key, origin, token


def authenticated(request, key):
    cookie=request.cookies.get(COOKIE,'')
    if len(cookie)>200:
        raise HTTPException(401,'데모에 로그인해 주세요.')
    with lock:
        item=sessions.get(digest(cookie))
        if not item or item[0]<=time.monotonic() or item[1]!=digest(key):
            raise HTTPException(401, '데모 로그인이 필요하거나 만료되었습니다.')


@router.get('/status')
def status(request: Request):
    try:
        key,_,_=configuration(request)
    except HTTPException as exc:
        if exc.status_code==403:raise
        return {'configured':False,'authenticated':False,'mode':'personal_demo'}
    try:
        authenticated(request,key)
        signed_in=True
    except HTTPException:
        signed_in=False
    return {'configured':True,'authenticated':signed_in,'mode':'personal_demo'}


class Login(BaseModel):
    admin_key: str = Field(min_length=1,max_length=1000)


@router.post('/login')
def login(request: Request, body: Login):
    key,_,_=configuration(request)
    if not secrets.compare_digest(key.encode(),body.admin_key.encode()):
        raise HTTPException(401, '발표용 비밀번호가 맞지 않습니다.')
    cookie=secrets.token_urlsafe(32)
    with lock:
        # Only one presenter session remains valid at a time.
        sessions.clear()
        sessions[digest(cookie)]=(time.monotonic()+3600,digest(key))
    response=JSONResponse({'authenticated':True,'mode':'personal_demo'})
    response.set_cookie(COOKIE,cookie,max_age=3600,httponly=True,samesite='strict',secure=False,path=COOKIE_PATH)
    return response


@router.post('/logout')
def logout(request: Request):
    configuration(request)
    with lock:sessions.pop(digest(request.cookies.get(COOKIE,'')),None)
    response=JSONResponse({'logged_out':True})
    response.delete_cookie(COOKIE,path=COOKIE_PATH,httponly=True,samesite='strict')
    return response


def read(request, action):
    key,origin,token=configuration(request)
    authenticated(request,key)
    client=CanvasClient(origin,token)
    try:
        return action(client)
    except CanvasError:
        raise HTTPException(502,'개인 Canvas 조회에 실패했습니다. 토큰 만료 또는 과목 접근 권한을 확인해 주세요.') from None
    finally:
        client.close()


@router.get('/courses')
def courses(request: Request):
    return read(request,lambda client:client.courses())


@router.get('/brief')
def brief(request: Request):
    from .personal_brief import briefing
    if not slots.acquire(blocking=False):
        raise HTTPException(429, 'LMS 조회 중입니다. 잠시 후 다시 시도해 주세요.')
    try:
        return read(request, briefing)
    finally:
        slots.release()


@router.post('/ask')
def ask(request: Request, body: PrivateQuestion):
    key,_,_=configuration(request);authenticated(request,key)
    if not body.consent_to_llm or not body.question.strip():
        raise HTTPException(422,'질문과 AI 전송 동의를 확인해 주세요.')
    if not slots.acquire(blocking=False):
        raise HTTPException(429,'이전 답변이 끝난 뒤 다시 질문해 주세요.')
    try:
        return read(request,lambda client:answer(client.course_data(body.course_id),body.question))
    finally:
        slots.release()
