import logging
import os
import secrets
import threading
import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text

from .crawler import crawl_notices
from .db import ChatHistory, ContextChunk, Notice, init_db, maintenance_lock, session_scope
from .ingest_context_to_chroma import chroma_client, get_collection, ingest_vectors
from .ingest_notices_to_context import ingest_chunks
from .rag_service import answer_question
from .static_page_crawler import crawl_static
from .crawl_public import PublicSource
from . import meals
from . import feedback
from . import canvas_oauth
from . import canvas_demo
from . import notice_recommendations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)
ask_slots = threading.BoundedSemaphore(2)


@asynccontextmanager
async def lifespan(app):
    init_db()
    worker = meals.start_worker() if os.getenv('MEALS_AUTO_REFRESH','true').lower() == 'true' else None
    try:
        yield
    finally:
        if worker:
            worker[0].set()
            await asyncio.to_thread(worker[1].join, 3)


app = FastAPI(title="Dong-A RAG v2", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(feedback.router)
app.include_router(canvas_oauth.router)
app.include_router(canvas_demo.router)
app.include_router(notice_recommendations.router)


@app.middleware('http')
async def private_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(('/api/v1/canvas/', '/api/v1/personal-canvas/')):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def require_admin(x_admin_key: str = Header(default="")):
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or not secrets.compare_digest(expected.encode(), x_admin_key.encode()):
        raise HTTPException(401, "관리자 인증이 필요합니다.")


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ConversationContext(BaseModel):
    pending_question: str | None = Field(default=None, max_length=2000)
    department: str | None = Field(default=None, max_length=100)
    admission_year: int | None = Field(default=None, ge=1970, le=2100)
    last_question: str | None = Field(default=None, max_length=2000)
    last_route: Literal['chat', 'retrieve'] | None = None
    history: list[HistoryMessage] = Field(default_factory=list, max_length=6)
    meal_campus: Literal['1','2'] | None = None
    pending_meal: str | None = Field(default=None, max_length=2000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: Literal["ko", "ja", "en", "zh"] = "ko"
    category: str | None = Field(default=None, max_length=100)
    search_mode: Literal["auto", "semantic", "latest"] = "auto"
    conversation_context: ConversationContext | None = None

    @field_validator("question")
    @classmethod
    def strip_question(cls, value):
        if not value.strip():
            raise ValueError("질문을 입력해 주세요.")
        return value.strip()


@app.get("/api/v1/heartbeat")
def heartbeat():
    state = {"api": "ok", "mysql": "unavailable", "chroma": "unavailable", "index": "unknown"}
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
        state["mysql"] = "ok"
    except Exception:
        pass
    try:
        chroma_client().heartbeat()
        state["chroma"] = "ok"
        try:
            state["index"] = "ready" if get_collection().count() else "empty"
        except Exception as exc:
            state["index"] = "empty" if type(exc).__name__ == "NotFoundError" else "error"
    except Exception:
        pass
    # Liveness returns 200 even when dependencies are degraded; readiness is in JSON.
    return {"status": "ok" if state["mysql"] == state["chroma"] == "ok" and state["index"] == "ready" else "degraded", "components": state}


@app.get('/api/v1/meals')
def meal_calendar(month: str | None = None, campus: Literal['1','2'] = '2'):
    try:
        return meals.month_data(month or meals.today().strftime('%Y-%m'),campus)
    except ValueError:
        raise HTTPException(422,'월은 YYYY-MM 형식으로 입력해 주세요.') from None


@app.post("/api/v1/ask")
def ask(request: AskRequest):
    if not ask_slots.acquire(blocking=False):
        raise HTTPException(429, "요청이 많습니다. 잠시 후 다시 시도해 주세요.")
    try:
        if request.category:
            with session_scope() as session:
                known = session.scalar(select(Notice.id).where(Notice.category == request.category).limit(1))
            if known is None:
                raise HTTPException(422, "수집된 학과·분류를 선택해 주세요.")
        if request.conversation_context is not None:
            result = answer_question(request.question, request.language,
                {"category":request.category} if request.category else None, request.search_mode,
                request.conversation_context.model_dump(exclude_none=True))
        elif request.category or request.search_mode != "auto":
            result = answer_question(request.question, request.language,
                {"category": request.category} if request.category else None, request.search_mode)
        else:
            result = answer_question(request.question, request.language)
        if os.getenv("SAVE_CHAT_HISTORY", "false").lower() == "true":
            try:
                with session_scope() as session:
                    session.add(ChatHistory(question=request.question, answer=result["answer"], language=request.language))
            except Exception:
                log.warning("chat_history_write_failed")
        return result
    finally:
        ask_slots.release()


def run_maintenance(job):
    try:
        with maintenance_lock():
            return job()
    except RuntimeError as exc:
        if str(exc) == "maintenance_busy":
            raise HTTPException(409, "다른 수집 또는 색인 작업이 진행 중입니다.") from None
        log.error("maintenance_failed type=%s", type(exc).__name__)
        raise HTTPException(503, "작업에 실패했습니다. 서버 로그를 확인하고 다시 실행해 주세요.") from None
    except Exception as exc:
        log.error("maintenance_failed type=%s", type(exc).__name__)
        raise HTTPException(503, "작업에 실패했습니다. 서버 로그를 확인하고 다시 실행해 주세요.") from None


@app.post("/api/v1/crawl/static", dependencies=[Depends(require_admin)])
def static():
    return {"results": run_maintenance(crawl_static)}


@app.post("/api/v1/crawl/notices", dependencies=[Depends(require_admin)])
def notices():
    return {"results": run_maintenance(crawl_notices)}


@app.post("/api/v1/ingest", dependencies=[Depends(require_admin)])
def ingest():
    def job():
        return {"chunks": ingest_chunks(), "vectors": ingest_vectors()}
    return run_maintenance(job)


@app.get("/api/v1/debug/sources", dependencies=[Depends(require_admin)])
def sources():
    with session_scope() as session:
        rows = session.execute(select(Notice.source, Notice.category, func.count(Notice.id), func.max(Notice.crawled_at)).group_by(Notice.source, Notice.category))
        return {"sources": [{"source": s, "category": c, "count": n, "last_crawled_at": at} for s, c, n, at in rows]}


@app.get("/api/v1/debug/chunks", dependencies=[Depends(require_admin)])
def chunks():
    with session_scope() as session:
        return {"count": session.scalar(select(func.count(ContextChunk.id)))}


@app.get("/api/v1/categories")
def categories():
    with session_scope() as session:
        rows = session.execute(select(Notice.category,func.count(Notice.id)).group_by(Notice.category).order_by(Notice.category))
        return {"categories":[{"name":name,"count":count} for name,count in rows]}


@app.get("/api/v1/debug/coverage", dependencies=[Depends(require_admin)])
def coverage():
    with session_scope() as session:
        rows = list(session.scalars(select(PublicSource).order_by(PublicSource.department,PublicSource.title)))
        return {"sources":[{"title":r.title,"url":r.url,"department":r.department,"category":r.category,"kind":r.kind,
                           "status":r.status,"pages_scanned":r.pages_scanned,"documents_saved":r.documents_saved,
                           "last_attempt":r.last_attempt,"message":r.message} for r in rows]}


@app.get('/api/v1/admin/feedback',dependencies=[Depends(require_admin)])
def list_feedback():
    with session_scope() as session:
        rows=list(session.scalars(select(feedback.Feedback).order_by(feedback.Feedback.id.desc()).limit(100)))
    return {'reports':[{'id':r.id,'question':r.question,'answer':r.answer,'reason':r.reason,
                       'comment':r.comment,'sources':r.sources,'created_at':r.created_at.isoformat()+'Z'} for r in rows]}


@app.get('/api/v1/admin/attachments', dependencies=[Depends(require_admin)])
def list_attachments():
    from .db import Attachment
    with session_scope() as session:
        rows = list(session.scalars(select(Attachment).order_by(Attachment.checked_at.desc(), Attachment.id).limit(200)))
        return {'attachments': [{'id': r.id, 'parent_id': r.parent_id, 'filename': r.filename,
                 'url': r.url, 'status': r.status, 'message': r.message, 'checked_at': r.checked_at} for r in rows]}
