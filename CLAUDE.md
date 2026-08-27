# CLAUDE.md — Finance RAG Agent 프로젝트 분석

> 본 문서는 `FinanceRagAgent/` 디렉터리 분석 결과를 정리한 것으로, 향후 Claude 가 이 프로젝트에서 작업할 때 빠르게 컨텍스트를 얻기 위한 레퍼런스다.

---

## 1. 프로젝트 개요

- **이름**: Finance RAG Agent
- **목적**: **데모용 RAG 시스템**. 한국 금융/세무 도메인 문서 Q&A 에이전트.
- **성격**: 포트폴리오/학습용 데모 (실제 세무 판단용이 아님, README "Notes" 섹션 명시).
- **핵심 차별점**: 단일 `retrieve → generate` 1-step RAG 가 아니라, **LangGraph StateGraph** 로 구성한 **Agentic RAG** —
  `classify → retrieve → generate → verify → (ungrounded 시) rewrite → retrieve` 의 재검색 루프를 가진 다단계 워크플로우.
- **환각 억제 전략**: `verify` 노드가 생성 답변이 참고 문서에 근거하는지 LLM 으로 판정, 근거 부족 시 쿼리 재작성 후 재검색. 무한 루프 방지를 위해 `MAX_REWRITES=2` 상한.

---

## 2. 기술 스택

| 영역 | 기술 |
|------|------|
| Language | Python 3.11+ |
| LLM Framework | LangChain, **LangGraph** (`>=0.2.0`) |
| LLM | OpenAI `gpt-4o-mini` (환경변수로 교체 가능) |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector DB | **ChromaDB** (로컬 영속화, `./chroma_db/`) |
| API | FastAPI + Uvicorn |
| Packaging | Docker + docker-compose |
| Config | pydantic-settings (`.env` 로딩) |
| Test | pytest (smoke 수준) |

---

## 3. 디렉터리 구조

```
FinanceRagAgent/
├── src/
│   ├── __init__.py
│   ├── config.py               # pydantic-settings (Settings 싱글톤)
│   ├── rag/
│   │   ├── loader.py           # Markdown 로딩 + RecursiveCharacterTextSplitter (500/50)
│   │   └── vectorstore.py      # Chroma 래퍼 (get_vectorstore / get_embeddings)
│   ├── agent/
│   │   ├── state.py            # AgentState (TypedDict)
│   │   ├── nodes.py            # 6개 노드 + 라우터 2개
│   │   └── graph.py            # StateGraph 조립 (build_graph, agent_graph)
│   ├── api/
│   │   ├── main.py             # FastAPI app (/health, /chat)
│   │   └── schemas.py          # ChatRequest / ChatResponse / SourceItem
│   └── scripts/
│       ├── ingest.py           # 샘플 문서 인덱싱 엔트리포인트
│       └── chat_cli.py         # 대화형 CLI 클라이언트
├── data/samples/
│   ├── 2025_법인세_신고안내.md                    # 국세청 법인세 신고안내 (~720KB, 744p)
│   ├── 2025_1기확정_부가가치세_신고안내매뉴얼.md   # 부가세 신고안내 (~150KB, 128p)
│   └── 원천징수의무자를위한_연말정산_신고안내.md    # 연말정산 (~36KB, 26p)
├── data/raw/                   # 원본 PDF (pdf_to_md.py 입력)
├── data/legacy_samples/        # 초기 데모용 MD (vat_guide, corporate_tax)
├── tests/
│   └── test_agent.py           # smoke: 그래프 컴파일 + 분류 테스트 (API 키 없으면 skip)
├── Dockerfile                  # python:3.11-slim, uvicorn CMD
├── docker-compose.yml          # agent 서비스, 8000 포트, chroma_db/data 볼륨
├── requirements.txt
├── .env.example                # OPENAI_API_KEY / MODEL / CHROMA 설정
├── .env_pwd.example            # PAID_MODEL_PASSWORD (실제 .env_pwd 는 gitignore)
├── .dockerignore               # 시크릿(.env/.env_pwd)·chroma_db·data/raw 제외
├── .gitignore
├── LICENSE (MIT)
└── README.md
```

---

## 4. LangGraph 워크플로우

### 노드 (src/agent/nodes.py)

| Node | 역할 | 핵심 로직 |
|------|------|----------|
| `classify_node` | 질문 분류 | LLM 으로 `rag` / `general` 이진 분류, `"rag" in raw` 로 느슨하게 파싱 |
| `retrieve_node` | 벡터 검색 | `rewritten_query` 우선, 없으면 원 질문으로 `similarity_search(k=10)` — 큰 PDF 커버리지 확보. MMR 은 한국어 세무 문서에서 핵심 청크를 밀어내는 부작용으로 사용 안 함 |
| `generate_node` | 답변 생성 | 검색 문서 없으면 즉시 "찾을 수 없습니다" 반환, 있으면 context 기반 생성. 프롬프트에서 외부 지식/추측 금지 명시 |
| `verify_node` | 근거 검증 | LLM 이 `grounded`/`ungrounded` 판정. "찾을 수 없습니다" 답변은 **`ungrounded`** 로 처리해 rewrite 루프를 한 번은 유도 (무한 루프는 `MAX_REWRITES=2` 로 차단). 문서가 없으면 자동 `grounded=False` |
| `rewrite_node` | 쿼리 재작성 | 동의어/상위·하위 개념 활용 재작성, `rewrite_count` 증가 |
| `general_node` | 일반 대화 | 인사·잡담 간결 응답, `grounded=True` 고정 |

### 라우터

- `route_by_type(state)` → `"retrieve"` 또는 `"general"` (classify 뒤 분기)
- `route_after_verify(state)` → `grounded` 이면 end, 아니면 `rewrite_count >= MAX_REWRITES(=2)` 일 때 end, 그 외 `rewrite`

### 그래프 조립 (src/agent/graph.py)

```
entry: classify
classify --[general]--> general --> END
classify --[rag]-----> retrieve --> generate --> verify
                          ^                        |
                          |                        v
                          +-- rewrite <--[ungrounded & attempts left]
                                          [grounded or max reached]--> END
```

- 전역에서 `agent_graph = build_graph()` 로 compiled 인스턴스 재사용.

### State 스키마 (src/agent/state.py)

```python
class AgentState(TypedDict, total=False):
    question: str
    query_type: Literal["rag", "general"]
    rewritten_query: str
    retrieved_docs: list[Document]
    answer: str
    grounded: bool
    rewrite_count: int
```

---

## 5. 설정 (src/config.py)

`Settings(BaseSettings)` — `.env` 자동 로딩, `extra="ignore"`.

| 키 | 기본값 |
|---|---|
| `OPENAI_API_KEY` | (필수) |
| `OPENAI_MODEL` | `gpt-4o-mini` |
| `EMBEDDING_MODEL` | `text-embedding-3-small` |
| `CHROMA_PERSIST_DIR` | `./chroma_db` |
| `COLLECTION_NAME` | `finance_docs` |
| `LOG_LEVEL` | `INFO` |
| `PAID_MODEL_PASSWORD` | `""` (빈 값 = `/chat` 차단) |
| `PAID_SESSION_MINUTES` | `60` |

LLM 은 `temperature=0` 으로 고정 (결정론적 동작 목적).

---

## 6. 데이터 파이프라인

### 인덱싱 (`src/scripts/ingest.py`)

1. `load_documents("data/samples")` — `data/samples/**/*.md` 재귀 로딩. `metadata["source"]=파일명` 과
   함께, Markdown 헤더 기준 1차 분할로 `metadata["section_path"]`(예: `가. 이월결손금`) 를 부여한다.
2. `split_documents(docs)` — `RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50, separators=["\n\n","\n",". "," ",""])`.
3. `get_vectorstore().add_documents(chunks)` — ChromaDB 영속 컬렉션에 업서트.

최초 1회 실행 필요 (`python -m src.scripts.ingest`).

### 샘플 문서

실제 인덱싱 대상은 `data/samples/` 의 **국세청 신고안내 매뉴얼 3종**이다 (총 2,287 청크).

| 문서 | 청크 | 내용 |
|---|---|---|
| `2025_법인세_신고안내.md` | 1,926 (84%) | 법인세율표, 최저한세, 이월결손금 공제 한도, 세액공제 적용 오류 사례, 외국납부세액공제, 가산세 |
| `2025_1기확정_부가가치세_신고안내매뉴얼.md` | 284 (12%) | 신고·납부 절차, 간이과세자 업종별 부가가치율, 환급, 기한 후 신고, 납부기한 연장, 가산세, 세법 해석사례 |
| `원천징수의무자를위한_연말정산_신고안내.md` | 77 (3%) | 원천징수의무자 정의, 연말정산 일정, 지급명세서 제출·가산세, 주택자금공제 |

`section_path` 보유 청크는 2,282 / 2,287 (99.8%).

> **주의 — 코퍼스 성격**: 세 문서 모두 **실무 신고 매뉴얼**이라 기본 개념을 평문으로 서술하지 않는다.
> 예를 들어 부가가치세 매뉴얼에는 "세율은 10%" 라는 문장이 없어, `"부가가치세 세율은 얼마인가요?"` 는
> 재작성 2회 후 정직한 거절로 끝난다(문서 안의 `10%` 는 전부 간이과세자 부가가치율·가산세 등 다른 항목).
> **"세율이 얼마냐"는 사전식 질문에 약하고, "어떤 경우에 / 어떻게 / 무슨 오류" 같은 절차 질문에 강하다.**
> 검증된 질문 목록은 README 의 Sample Questions 참조.

`data/legacy_samples/` 의 `vat_guide.md` / `corporate_tax.md` 는 초기 데모용 요약본으로,
**인덱싱 대상이 아니다.** 이 파일들 기준으로 질문을 만들면 코퍼스에 없는 내용을 묻게 된다.

---

## 7. API (src/api/main.py, schemas.py)

### 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | `status` / `model` / `password_required` / `password_configured` / `unlock_remaining_sec` |
| POST | `/unlock` | 비밀번호 검증 → 서명 HttpOnly 쿠키 발급 |
| POST | `/lock` | 인증 쿠키 삭제 |
| POST | `/chat` | 질문 → 에이전트 실행 → 응답. **비밀번호 또는 유효 쿠키 필요** |

### `ChatRequest`

```json
{ "question": "...", "password": "..." }   // password 는 /unlock 후 생략 가능
```

### `ChatResponse`

```json
{
  "answer": "...",
  "query_type": "rag" | "general",
  "grounded": true,
  "rewrite_count": 0,
  "sources": [{"source": "vat_guide.md", "snippet": "... (첫 160자)"}]
}
```

- `agent_graph.invoke({"question": ..., "rewrite_count": 0})` 단발 호출. 멀티턴 미지원 (Roadmap 에 명시).
- `retrieved_docs` 의 각 문서를 `SourceItem(source, snippet)` 으로 매핑해 반환.

---

## 7-1. 유료 API 접근 제어 (`src/api/main.py`)

`/chat` 은 호출마다 임베딩 + LLM 으로 실제 과금되므로, 공개 배포 시 비밀번호로 잠근다.
LiteLLM_Demo 의 `5fe0e8d` 패턴을 이식한 것이되, **이 프로젝트에는 무료 티어가 없어서**
모델 패턴 매칭(`PROTECTED_MODELS`) 없이 `/chat` 엔드포인트 전체를 보호한다.

| 요소 | 구현 |
|---|---|
| 비밀번호 출처 | `.env_pwd` 의 `PAID_MODEL_PASSWORD` (gitignore + dockerignore). compose 가 `env_file: {path: ./.env_pwd, required: false}` 로 주입 |
| fail-closed | 비밀번호 미설정 시 `/chat`·`/unlock` 모두 `503` — 실수로 열리지 않음 |
| 세션 | `_issue_session` 이 `exp.HMAC-SHA256(exp)` 형태 서명 쿠키(`paid_session`, HttpOnly, SameSite=Lax) 발급 |
| 서명 키 | `_session_secret()` = `paid_model_password + "|" + openai_api_key` — **비밀번호 변경 시 기존 쿠키 자동 무효** |
| 비교 | `secrets.compare_digest` (타이밍 공격 완화) |
| 무차별 대입 | `_fail_state[ip]`, 5회 실패 시 300초 `429`. 프로세스 메모리라 재시작 시 초기화 |
| 검증 위치 | 서버 (`_verify_paid_access`) — 프론트/Swagger 검사는 보호 수단이 아님 |

주의:
- `_fail_state` 는 `request.client.host` 기준. **리버스 프록시 뒤에 두면 모든 요청이 같은 IP 로 보여**
  스로틀이 전역 차단처럼 동작한다. 그 구성에선 `X-Forwarded-For` 처리(`--proxy-headers`)가 필요하다.
- CLI(`chat_cli.py`)·`ingest.py` 는 그래프를 직접 호출하므로 게이트를 거치지 않는다 (의도된 동작).
- `env_file` 값은 컨테이너 **생성 시점**에 굳는다. 비밀번호 변경 후 `restart` 는 무효, `up -d --force-recreate` 필요.

## 8. 실행 방법

### 로컬

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # OPENAI_API_KEY 설정
python -m src.scripts.ingest      # 최초 1회
python -m src.scripts.chat_cli    # CLI
# 또는
uvicorn src.api.main:app --reload --port 8000
```

### Docker

```bash
echo "OPENAI_API_KEY=sk-..." > .env
docker compose up --build -d
docker compose exec agent python -m src.scripts.ingest
curl http://localhost:8000/health
```

- `docker-compose.yml` 은 `./chroma_db` 와 `./data` 를 호스트 볼륨으로 마운트하므로 컨테이너 재기동 후에도 인덱스 유지.

---

## 9. 테스트 (tests/test_agent.py)

- `test_graph_compiles` — OpenAI/Chroma 호출 없이 순수 컴파일만 확인. CI 에서 항상 실행 가능.
- `test_general_greeting` / `test_rag_question_classification` — `OPENAI_API_KEY` 없으면 자동 skip.
- 현재 수준: smoke 테스트만. 단위 테스트/RAGAS 평가는 Roadmap.

---

## 10. 주요 설계 포인트 / 관찰 사항

1. **노드는 순수 함수**: `AgentState` 일부를 읽고 업데이트 dict 를 반환 → 단위 테스트 용이.
2. **루프 상한**: `MAX_REWRITES=2` — 무한 루프 방지 가드.
3. **정직한 거절**: context 에 답이 없으면 "제공된 문서에서 해당 내용을 찾을 수 없습니다." 반환, `verify` 가 이 응답을 자동 `grounded=True` 처리해 루프 방지.
4. **분류기 파싱이 느슨함**: `"rag" in raw.lower()` 방식이라 LLM 이 "rag 입니다" 같이 답해도 통과. 단, "general rag 아님" 같은 출력은 false positive 가 될 수 있음 — 현재는 `temperature=0` 이므로 실무상 문제 낮음.
5. **LLM 인스턴스 단일화**: `nodes.py` 모듈 로드 시점에 `llm` 전역 생성. 모든 노드가 공유.
6. **전역 compiled graph**: `agent_graph = build_graph()` 를 모듈 로드 시 1회 컴파일해 재사용 (FastAPI/CLI 공통).
7. **메타데이터**: `source`(파일명) + `section_path`(Markdown 헤더 경로). 페이지 번호 단위는 없음.
   API 응답의 `sources[].section_path` 로 노출되어 근거 위치를 보여준다.
8. **청크 크기 500/50**: Markdown 기준 비교적 작음. 한국어 토큰 특성상 적절한 편.

---

## 11. Roadmap (README 기준)

- 멀티턴 대화 (MessagesState + 체크포인터)
- Tool 노드 추가 (VAT 계산기, 법인세 시뮬레이터)
- SSE 스트리밍 응답
- RAGAS 자동 평가 파이프라인
- 하이브리드 검색 (BM25 + 벡터)

---

## 12. 수정 시 유의 사항

- `AgentState` 스키마를 변경하면 `nodes.py`, `graph.py`, `api/main.py`, `api/schemas.py`, CLI 출력 모두에 파급.
- `route_after_verify` 의 종료 조건 변경 시 `MAX_REWRITES` 와 연동.
- Chroma persist 디렉터리를 바꾸면 Docker 볼륨 매핑(`docker-compose.yml`) 도 수정 필요.
- 새 문서 타입(PDF 등) 추가 시 `loader.py` 의 `rglob("*.md")` 및 로더 교체 필요.
- `PAID_MODEL_PASSWORD` 를 바꾸면 기존 인증 쿠키가 전부 무효화된다(서명 키에 포함). 컨테이너 재생성 필요.
- `/chat` 에 게이트가 걸려 있으므로, 이 엔드포인트를 호출하는 새 클라이언트/테스트는 `password` 또는 `/unlock` 쿠키를 넣어야 한다.
- 샘플 데이터는 학습용 요약이며 법적 근거로 쓸 수 없다는 디스클레이머는 README 에만 있음 — API 응답에는 포함되지 않음.
