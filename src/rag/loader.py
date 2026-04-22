"""문서 로딩 및 청킹

1) data/samples/**/*.md 를 Document 로 로드 (source=파일명)
2) Markdown 헤더 기준 1차 분할로 섹션 경로(section_path) 메타데이터 부여
3) RecursiveCharacterTextSplitter 로 2차 분할 (chunk_size=1000, overlap=150)

한국어는 토큰/문자 밀도가 영어보다 높고 세법 문서는 조·호·목 단위로
문단이 길어서 500/50 으로 자르면 문맥이 끊어지는 경우가 많다. 1000/150
으로 늘리고 섹션 경로를 메타데이터로 보존해 검색 결과에 맥락을 덧붙인다.
"""
from pathlib import Path

from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

_HEADERS_TO_SPLIT_ON = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
    ("####", "h4"),
]


def load_documents(data_dir: str = "data/samples") -> list[Document]:
    """data_dir 하위의 모든 Markdown 문서를 로드한다."""
    data_path = Path(data_dir)
    if not data_path.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    docs: list[Document] = []
    for path in sorted(data_path.rglob("*.md")):
        loader = TextLoader(str(path), encoding="utf-8")
        loaded = loader.load()
        for d in loaded:
            d.metadata["source"] = path.name
        docs.extend(loaded)
    return docs


def split_documents(
    docs: list[Document],
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> list[Document]:
    """헤더 → 문자 2 단계로 분할하고 섹션 경로 메타데이터를 추가한다."""
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADERS_TO_SPLIT_ON,
        strip_headers=False,
    )
    char_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    all_chunks: list[Document] = []
    for doc in docs:
        header_chunks = md_splitter.split_text(doc.page_content)
        # MarkdownHeaderTextSplitter 는 새 Document 를 만들면서 원본
        # metadata(source 등) 를 잃어버리므로 직접 병합.
        for hc in header_chunks:
            hc.metadata = {**doc.metadata, **hc.metadata}

        sub_chunks = char_splitter.split_documents(header_chunks)
        for sc in sub_chunks:
            sections = [sc.metadata.get(k) for k in ("h1", "h2", "h3", "h4")]
            sections = [s for s in sections if s]
            if sections:
                sc.metadata["section_path"] = " > ".join(sections)
        all_chunks.extend(sub_chunks)
    return all_chunks
