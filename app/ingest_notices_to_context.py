from sqlalchemy import delete, select

from .config import CHUNK_OVERLAP, CHUNK_SIZE
from .db import ContextChunk, Notice, digest, init_db, maintenance_lock, session_scope


def chunk_text(content, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Invalid chunk size/overlap")
    for start in range(0, len(content), size - overlap):
        value = content[start:start + size]
        if value.strip():
            yield value
        if start + size >= len(content):
            break


def ingest_chunks():
    changed = skipped = total = 0
    with session_scope() as session:
        ids = list(session.scalars(select(Notice.id)))
    for notice_id in ids:
        # One document replacement is atomic. A failed run can safely be retried.
        with session_scope() as session:
            notice = session.get(Notice, notice_id)
            if notice is None:
                continue
            existing = list(session.scalars(select(ContextChunk).where(ContextChunk.source_id == notice.id).order_by(ContextChunk.chunk_index)))
            parts = list(chunk_text(notice.content))
            if len(existing) == len(parts) and all(c.document_hash == notice.content_hash and c.chunk_text == part for c, part in zip(existing, parts)):
                skipped += 1
                continue
            session.execute(delete(ContextChunk).where(ContextChunk.source_id == notice.id))
            for index, part in enumerate(parts):
                session.add(ContextChunk(source_type=notice.source_type, source_id=notice.id,
                    category=notice.category, title=notice.title, chunk_text=part, chunk_index=index,
                    url=notice.url, published_at=notice.published_at, content_hash=digest(part),
                    document_hash=notice.content_hash))
            changed += 1
            total += len(parts)
    return {"changed_documents": changed, "unchanged_documents": skipped, "created_chunks": total}


if __name__ == "__main__":
    init_db()
    with maintenance_lock():
        print(ingest_chunks())
