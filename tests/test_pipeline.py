from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from app import db, ingest_context_to_chroma as vectors, llm_provider, main, rag_service
from app.crawl_common import clean_text
from app.crawler import parse_detail, parse_listing
from app.ingest_notices_to_context import chunk_text, ingest_chunks
from app.static_page_crawler import extract_static


@pytest.fixture(autouse=True)
def database(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(db, "engine", lambda: test_engine)
    monkeypatch.setenv("ADMIN_API_KEY", "test-only-token")
    db.init_db()
    yield
    test_engine.dispose()


def notice(content="졸업요건을 확인하세요. " * 60, **changes):
    data = dict(source="학사안내", source_type="static", category="졸업", title="졸업기준",
                content=content, url="https://www.donga.ac.kr/test", published_at=datetime(2026, 9, 1))
    data.update(changes)
    return db.save_notice(**data)


def test_cleaning_preserves_table_and_removes_menu():
    html = "<header>메뉴</header><h1>스킵네비게이션</h1><p>본문바로가기</p><script>bad()</script><p>졸업 기준</p><table><tr><th>학점</th><td>130</td></tr></table><p>인쇄</p>"
    assert clean_text(html) == "졸업 기준\n학점 | 130"


def test_static_rejects_whole_page_fallback():
    with pytest.raises(ValueError):
        extract_static(BeautifulSoup("<body><h1>안내페이지</h1>접근 오류</body>", "html.parser"))


def test_board_uses_notice_title_and_canonical_url():
    soup = BeautifulSoup("<table><tr><td class='subject'><a href='?mCode=MN171&mode=view&mgr_seq=1&board_seq=2&page=9'>졸업 안내</a></td><td class='date'>2026.09.01</td></tr></table>", "html.parser")
    item = parse_listing(soup, "https://www.donga.ac.kr/kor/CMS/Board/Board.do?mCode=MN171")[0]
    assert "page=" not in item["url"]
    soup = BeautifulSoup("<h1>스킵네비게이션</h1><div class='bdViewTit'><h3 class='viewTit'>졸업 안내</h3></div><div id='boardContents'>졸업요건은 입학 연도와 소속 학과의 기준을 확인하세요.</div>", "html.parser")
    assert parse_detail(soup, item)["title"] == "졸업 안내"


def test_chunks_exact_overlap_no_tail_duplicate():
    text = "가나다라마바사아자차" * 90
    parts = list(chunk_text(text))
    assert [len(p) for p in parts] == [400, 400, 200]
    assert parts[0][-50:] == parts[1][:50]
    assert parts[0] + "".join(p[50:] for p in parts[1:]) == text
    assert len(list(chunk_text("x" * 400))) == 1
    with pytest.raises(ValueError):
        list(chunk_text("abc", 50, 50))


def test_idempotence_and_metadata_only_change():
    assert notice() == "created"
    assert ingest_chunks()["changed_documents"] == 1
    with db.session_scope() as session:
        before = list(session.scalars(select(db.ContextChunk.id)))
    assert notice() == "unchanged"
    assert ingest_chunks()["unchanged_documents"] == 1
    assert notice(title="수정된 졸업기준") == "updated"
    assert ingest_chunks()["changed_documents"] == 1
    with db.session_scope() as session:
        chunks = list(session.scalars(select(db.ContextChunk)))
    assert all(c.title == "수정된 졸업기준" for c in chunks)
    assert not set(before) & {c.id for c in chunks}


class FakeCollection:
    def __init__(self):
        self.rows = {}
    def get(self, ids=None, limit=1000, offset=0, include=None):
        keys = [i for i in ids if i in self.rows] if ids is not None else list(self.rows)[offset:offset+limit]
        return {"ids": keys, "metadatas": [self.rows[i] for i in keys]}
    def upsert(self, ids, metadatas, **kwargs):
        self.rows.update(zip(ids, metadatas))
    def delete(self, ids):
        for i in ids:
            self.rows.pop(i, None)
    def count(self):
        return len(self.rows)


def test_incremental_embedding_and_stale_cleanup(monkeypatch):
    collection = FakeCollection()
    monkeypatch.setattr(vectors, "get_collection", lambda **kw: collection)
    monkeypatch.setattr(vectors, "embed", lambda texts: [[1.0, 0.0] for _ in texts])
    notice(); ingest_chunks()
    assert vectors.ingest_vectors()["embedded_chunks"] > 0
    assert vectors.ingest_vectors()["embedded_chunks"] == 0
    notice(content="새 졸업 기준입니다. " * 8); ingest_chunks()
    result = vectors.ingest_vectors()
    assert result["embedded_chunks"] == 1
    assert result["deleted_vectors"] > 0
    assert collection.count() == 1


def test_failed_embedding_can_retry(monkeypatch):
    collection = FakeCollection()
    monkeypatch.setattr(vectors, "get_collection", lambda **kw: collection)
    notice(); ingest_chunks()
    monkeypatch.setattr(vectors, "embed", lambda texts: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(RuntimeError):
        vectors.ingest_vectors()
    monkeypatch.setattr(vectors, "embed", lambda texts: [[1.0] for _ in texts])
    assert vectors.ingest_vectors()["embedded_chunks"] > 0


def test_stale_search_result_excluded_before_reingest(monkeypatch):
    notice(); ingest_chunks()
    with db.session_scope() as session:
        chunk = session.scalar(select(db.ContextChunk))
    fake = SimpleNamespace(count=lambda: 1, query=lambda **kw: {"ids": [[str(chunk.id)]], "distances": [[0.1]], "metadatas": [[vectors.metadata(chunk)]]})
    monkeypatch.setattr(rag_service, "get_collection", lambda: fake)
    monkeypatch.setattr(rag_service, "embed", lambda values: [[1.0]])
    assert len(rag_service.retrieve("졸업")[0]) == 1
    notice(content="새 조건입니다. " * 10)
    assert rag_service.retrieve("졸업")[0] == []


@pytest.mark.parametrize("code", ["quota_exceeded", "missing_api_key", "timeout", "unsupported_provider", "provider_error"])
def test_provider_failure_retains_sources(monkeypatch, code):
    notice(); ingest_chunks()
    with db.session_scope() as session:
        chunks = list(session.scalars(select(db.ContextChunk)))
    monkeypatch.setattr(rag_service, "retrieve", lambda *args: (chunks, []))
    def fail(*args):
        raise llm_provider.LLMError(code)
    monkeypatch.setattr(rag_service, "generate_answer", fail)
    result = rag_service.answer_question("졸업?")
    assert result["answer"] == rag_service.FALLBACK
    assert len(result["sources"]) == 1
    assert result["debug_info"]["error_code"] == code


def test_empty_and_unavailable_search(monkeypatch):
    monkeypatch.setattr(rag_service, "retrieve", lambda *args: ([], []))
    assert rag_service.answer_question("질문")["answer"] == "관련 문서를 찾지 못했습니다."
    monkeypatch.setattr(rag_service, "retrieve", lambda *args: (_ for _ in ()).throw(RuntimeError("private-host")))
    result = rag_service.answer_question("질문")
    assert result["debug_info"]["status"] == "retrieval_unavailable"
    assert "private-host" not in result["answer"]


@pytest.mark.parametrize("provider", ["gemini", "openai", "groq"])
def test_provider_success_and_quota(monkeypatch, provider):
    monkeypatch.setenv(provider.upper() + "_API_KEY", "test-only")
    captured = []
    def handler(request):
        captured.append(request)
        if len(captured) == 2:
            return httpx.Response(429)
        if provider == "gemini":
            return httpx.Response(200, json={"candidates":[{"finishReason":"STOP", "content":{"parts":[{"text":"답변 [1]"}]}}]})
        return httpx.Response(200, json={"choices":[{"finish_reason":"stop", "message":{"content":"답변 [1]"}}]})
    client_class = httpx.Client
    monkeypatch.setattr(llm_provider.httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(handler)))
    assert llm_provider.Provider(provider).generate_answer("system", "question") == "답변 [1]"
    with pytest.raises(llm_provider.LLMError, match="quota_exceeded"):
        llm_provider.Provider(provider).generate_answer("system", "question")


def test_missing_key_and_unknown_provider(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(llm_provider.LLMError, match="missing_api_key"):
        llm_provider.Provider("gemini").generate_answer("", "")
    with pytest.raises(llm_provider.LLMError, match="unsupported_provider"):
        llm_provider.Provider("other").generate_answer("", "")


def test_api_validation_authentication_and_languages(monkeypatch):
    monkeypatch.setattr(main, "answer_question", lambda q, lang: {"answer":lang,"sources":[],"debug_info":{}})
    with TestClient(main.app) as client:
        assert client.get("/api/v1/debug/chunks").status_code == 401
        assert client.post("/api/v1/ingest").status_code == 401
        assert client.get("/api/v1/debug/chunks", headers={"X-Admin-Key":"test-only-token"}).json() == {"count":0}
        for language in ["ko", "ja", "en", "zh"]:
            assert client.post("/api/v1/ask", json={"question":"질문", "language":language}).json()["answer"] == language
        for question in ["", "   ", "x" * 2001]:
            assert client.post("/api/v1/ask", json={"question":question}).status_code == 422
        assert client.post("/api/v1/ask", json={"question":"질문", "language":"fr"}).status_code == 422
