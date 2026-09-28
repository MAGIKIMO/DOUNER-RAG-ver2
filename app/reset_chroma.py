import argparse

from .config import COLLECTION
from .db import maintenance_lock
from .ingest_context_to_chroma import chroma_client, ingest_vectors


def main():
    parser = argparse.ArgumentParser(description="Rebuild only the project's Chroma collection from MySQL.")
    parser.add_argument("--yes", action="store_true", help="Confirm replacement of the vector index")
    args = parser.parse_args()
    if not args.yes:
        parser.error("Pass --yes to replace the vector index. MySQL records are preserved.")
    from chromadb.errors import NotFoundError
    with maintenance_lock():
        try:
            chroma_client().delete_collection(COLLECTION)
        except NotFoundError:
            pass
        print(ingest_vectors())


if __name__ == "__main__":
    main()
