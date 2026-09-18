# `src/rag/` — 문서를 자르고 저장하고 찾기

RAG 의 “R”(찾기)을 담당합니다.
인덱싱(`ingest.py`)과 질문 중 검색(`retrieve_node`)이 **같은** `get_vectorstore()` 를 씁니다.
저장 위치와 임베딩 모델이 다르면 검색이 빗나갑니다.

---

## `loader.py` — Markdown 을 검색 가능한 조각으로

역할은 두 함수뿐입니다. LLM 을 부르지 않습니다.

### `_HEADERS_TO_SPLIT_ON`

```python
_HEADERS_TO_SPLIT_ON = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
    ("####", "h4"),
]
```

Markdown 제목 기호를 메타데이터 키 `h1`~`h4` 에 넣으라는 규칙입니다.
나중에 `section_path` 를 만들 때 이 키를 순서대로 이어 붙입니다.

### `load_documents(data_dir="data/samples")`

1. 폴더가 없으면 `FileNotFoundError`
2. `**/*.md` 를 이름순으로 찾음 (`rglob`)
3. 각 파일을 UTF-8 `TextLoader` 로 읽어 `Document` 목록으로 만듦
4. `metadata["source"]` 에 **파일 이름만** 넣음 (전체 경로가 아님)

하위 폴더의 md 도 포함하지만, 현재 쓰는 것은 `data/samples/` 바로 아래 3개입니다.
`legacy_samples/` 는 이 함수의 기본 경로 밖이라 인덱싱되지 않습니다.

반환값은 파일당 문서 1개에 가깝습니다. 아직 자르기 전 긴 글입니다.

### `split_documents(docs, chunk_size=1000, chunk_overlap=150)`

한 파일을 두 번 자릅니다.

**1차 — 헤더 단위** `MarkdownHeaderTextSplitter`

- `#` ~ `####` 를 만나면 새 조각
- `strip_headers=False` 라 제목 줄이 본문에 남음 (검색에 제목 단어가 도움이 됨)
- 이 splitter 는 새 `Document` 를 만들면서 **원본 metadata 를 버립니다.**  
  그래서 코드가 `hc.metadata = {**doc.metadata, **hc.metadata}` 로 `source` 를 다시 붙입니다.

**2차 — 길이 단위** `RecursiveCharacterTextSplitter`

- 목표 길이 1000자, 앞 조각과 150자 겹침
- 자르는 우선순위: 빈 줄 → 줄바꿈 → `". "` → 공백 → 글자
- 한국어 세법 문장은 조·호가 길어서, 예전의 500/50 은 문맥이 자주 끊겼습니다.

**섹션 경로**

```python
sections = [sc.metadata.get(k) for k in ("h1", "h2", "h3", "h4")]
sections = [s for s in sections if s]
if sections:
    sc.metadata["section_path"] = " > ".join(sections)
```

CLI/API 에 `2025_법인세_신고안내.md — 가. 이월결손금` 처럼 보여 주기 위한 칸입니다.
헤더가 전혀 없는 조각은 `section_path` 가 없을 수 있습니다. README 기준으로는 청크의 약 99.8% 에 붙습니다.

OpenAI 호출은 이 파일에 없습니다. 글자만 자릅니다.

---

## `vectorstore.py` — ChromaDB 래퍼

파일은 함수 두 개입니다.

### `get_embeddings()`

```python
return OpenAIEmbeddings(
    model=settings.embedding_model,
    api_key=settings.openai_api_key,
)
```

글을 숫자 벡터로 바꿉니다. 인덱싱 때 청크마다, 질문 때 질의문마다 과금됩니다.

### `get_vectorstore()`

```python
return Chroma(
    collection_name=settings.collection_name,
    embedding_function=get_embeddings(),
    persist_directory=settings.chroma_persist_dir,
)
```

- `collection_name` 기본값 `finance_docs`
- `persist_directory` 기본값 `./chroma_db` — 서버를 꺼도 디스크에 남음
- Docker 에서는 compose 가 `CHROMA_PERSIST_DIR=/app/chroma_db` 로 바꾸고, 호스트의 `./chroma_db` 를 그 경로에 붙입니다.

같은 설정으로:

- `ingest.py` → `vs.add_documents(chunks)`
- `retrieve_node` → `vs.similarity_search(query, k=10)`

컬렉션 이름을 한쪽만 바꾸면 빈 DB 를 검색하게 됩니다.

---

## 데이터가 흐르는 방향

```
data/samples/*.md
        │  load_documents
        ▼
  Document (파일 단위, source=파일명)
        │  split_documents
        ▼
  Document 여러 개 (1000자, section_path)
        │  add_documents  → embedding API
        ▼
  chroma_db / finance_docs
        │  similarity_search  → embedding API (질문 1회)
        ▼
  retrieve_node 의 retrieved_docs
```

청크 크기(`1000/150`)를 코드에서 바꾸면 **반드시** `python -m src.scripts.ingest --reset` 을 다시 해야 합니다.
리셋 없이 추가만 하면 옛 조각과 새 조각이 섞입니다.
