import os


def integer(name, default, minimum=1, maximum=1000):
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"Invalid {name}")
    return value


COLLECTION = os.getenv("CHROMA_COLLECTION", "donga_rag_collection")
MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
REVISION = os.getenv("EMBEDDING_REVISION", "bf3bf13ab40c3157080a7ab344c831b9ad18b5eb")
CHUNK_SIZE = 400
CHUNK_OVERLAP = 50
