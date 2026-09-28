import os
import threading
from functools import lru_cache

from sqlalchemy import select

from .config import COLLECTION, MODEL, REVISION, integer
from .db import ContextChunk, Notice, digest, init_db, maintenance_lock, session_scope

_model_lock = threading.Lock()


@lru_cache
def chroma_client():
    import chromadb
    from chromadb.config import Settings
    return chromadb.HttpClient(host=os.getenv("CHROMA_HOST", "vector-db"),
                              port=int(os.getenv("CHROMA_PORT", "8000")),
                              settings=Settings(anonymized_telemetry=False))


def embedding_signature():
    return digest(MODEL + "@" + REVISION + ":normalized:256:v1")


def get_collection(create=False):
    client = chroma_client()
    if create:
        collection = client.get_or_create_collection(COLLECTION, embedding_function=None,
            metadata={"hnsw:space": "cosine", "embedding_signature": embedding_signature()})
    else:
        collection = client.get_collection(COLLECTION, embedding_function=None)
    if (collection.metadata or {}).get("embedding_signature") != embedding_signature():
        raise RuntimeError("embedding_model_mismatch: reset and re-ingest the collection")
    return collection


@lru_cache
def embedding_model():
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(1)
    model = SentenceTransformer(MODEL, revision=REVISION, device="cpu", trust_remote_code=False)
    # 400 characters are not 400 tokens. Increase the default 128-token window.
    model.max_seq_length = 256
    return model


def embed(texts):
    with _model_lock:
        return embedding_model().encode(texts, batch_size=integer("EMBEDDING_BATCH_SIZE", 8, maximum=64),
            normalize_embeddings=True, show_progress_bar=False).tolist()


def metadata(chunk):
    return {"source_type": chunk.source_type, "source_id": chunk.source_id,
            "title": chunk.title, "category": chunk.category, "url": chunk.url,
            "published_at": chunk.published_at.isoformat() if chunk.published_at else "",
            "chunk_index": chunk.chunk_index, "content_hash": chunk.content_hash,
            "document_hash": chunk.document_hash, "embedding_signature": embedding_signature()}


def ingest_vectors():
    collection = get_collection(create=True)
    valid_ids = set()
    embedded = skipped = 0
    last_id = 0
    while True:
        with session_scope() as session:
            chunks = list(session.scalars(select(ContextChunk).join(Notice, Notice.id == ContextChunk.source_id)
                .where(ContextChunk.id > last_id, ContextChunk.document_hash == Notice.content_hash)
                .order_by(ContextChunk.id).limit(64)))
        if not chunks:
            break
        last_id = chunks[-1].id
        ids = [str(chunk.id) for chunk in chunks]
        valid_ids.update(ids)
        stored = collection.get(ids=ids, include=["metadatas"])
        previous = dict(zip(stored["ids"], stored["metadatas"]))
        changed = [chunk for chunk in chunks if previous.get(str(chunk.id)) != metadata(chunk)]
        skipped += len(chunks) - len(changed)
        if changed:
            collection.upsert(ids=[str(c.id) for c in changed], embeddings=embed([c.chunk_text for c in changed]),
                              documents=[c.chunk_text for c in changed], metadatas=[metadata(c) for c in changed])
            embedded += len(changed)
    # Collect stale IDs first: deleting during offset pagination would skip entries.
    stale = []
    offset = 0
    while True:
        page = collection.get(limit=1000, offset=offset, include=[])
        if not page["ids"]:
            break
        stale.extend(i for i in page["ids"] if i not in valid_ids)
        offset += len(page["ids"])
    for start in range(0, len(stale), 500):
        collection.delete(ids=stale[start:start + 500])
    return {"embedded_chunks": embedded, "unchanged_vectors": skipped, "deleted_vectors": len(stale), "total_vectors": collection.count()}


if __name__ == "__main__":
    init_db()
    with maintenance_lock():
        print(ingest_vectors())
