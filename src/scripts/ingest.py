"""샘플 문서를 ChromaDB 에 인덱싱

Usage:
    python -m src.scripts.ingest               # 기존 컬렉션에 추가 업서트
    python -m src.scripts.ingest --reset       # 컬렉션 비우고 새로 적재
"""
import argparse
import logging

from src.config import settings
from src.rag.loader import load_documents, split_documents
from src.rag.vectorstore import get_vectorstore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="인덱싱 전에 기존 컬렉션을 비운다(청크 파라미터 바꿀 때 필수)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=settings.log_level)

    print("[1/3] Loading documents from data/samples ...")
    docs = load_documents("data/samples")
    print(f"      Loaded {len(docs)} document(s)")

    print("[2/3] Splitting into chunks ...")
    chunks = split_documents(docs)
    print(f"      Produced {len(chunks)} chunk(s)")
    if chunks:
        avg_len = sum(len(c.page_content) for c in chunks) // len(chunks)
        sections = sum(1 for c in chunks if c.metadata.get("section_path"))
        print(f"      avg chunk length: {avg_len} chars, section-tagged: {sections}/{len(chunks)}")

    print(f"[3/3] Upserting into ChromaDB at {settings.chroma_persist_dir} ...")
    vs = get_vectorstore()
    if args.reset:
        existing = vs._collection.count()
        if existing:
            print(f"      --reset: deleting {existing} existing vectors ...")
            # chromadb >=1.0 은 빈 where 필터를 거부하므로 전체 ID 를 뽑아 삭제.
            ids = vs._collection.get(include=[])["ids"]
            if ids:
                vs._collection.delete(ids=ids)
    vs.add_documents(chunks)
    print(f"      Done. Collection now has {vs._collection.count()} vectors.")


if __name__ == "__main__":
    main()
