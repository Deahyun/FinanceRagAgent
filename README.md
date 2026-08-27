# Finance RAG Agent

**LangGraph 기반 Agentic RAG** 시스템 — 국세청 공식 신고안내 PDF(법인세·부가가치세·연말정산) 를 소스로 한 한국 세무 도메인 Q&A 에이전트.

단순 "검색 → 생성" 의 1-step RAG 가 아닌, **질문 분류 → 검색 → 답변 생성 → 근거 검증 → 재검색 루프** 의 다단계 워크플로우를 LangGraph `StateGraph` 와 조건부 엣지로 구현했습니다. 모델이 컨텍스트 부족으로 환각을 일으키지 않도록 자체 검증(grounding check)을 거치고, 근거가 부족하면 쿼리를 재작성해 다시 검색합니다.

---

## Architecture

```
           ┌──────────────────┐
           │  User Question   │
           └────────┬─────────┘
                    ▼
            ┌───────────────┐
            │   classify    │
            └───┬───────┬───┘
      general  │       │  rag
                ▼       ▼
         ┌─────────┐  ┌──────────┐
         │ general │  │ retrieve │◀───────────┐
         └────┬────┘  └────┬─────┘            │
              │            ▼                  │
              │       ┌──────────┐            │
              │       │ generate │            │
              │       └────┬─────┘            │
              │            ▼                  │
              │       ┌──────────┐            │
              │       │  verify  │            │
              │       └────┬─────┘            │
              │   grounded │  ungrounded      │
              │            │  (attempts left) │
              │            │                  │
              │            │            ┌─────┴────┐
              │            │            │ rewrite  │
              │            │            └──────────┘
              │            │
              ▼            ▼
           ┌───────────────────┐
           │       END         │
           └───────────────────┘
```

**핵심 설계 포인트**

- `StateGraph(AgentState)` 로 전체 워크플로우 정의
- `add_conditional_edges` 로 2개의 분기점 구현 (질문 유형 / 근거 검증 결과)
- `verify` 가 "찾을 수 없음" 응답까지 ungrounded 로 처리해 **rewrite 루프를 최소 1회 유도** → 첫 검색 실패에도 동의어 쿼리로 재시도
- 재검색 루프에 반복 상한(`MAX_REWRITES=2`) 을 둬서 무한 루프 방지
- 각 노드는 순수 함수 → 단위 테스트 용이
- ChromaDB 로컬 영속화로 별도 DB 서버 불필요
- Docker / docker-compose 로 원클릭 배포

---

## Tech Stack

| 영역 | 기술 |
|------|------|
| Language | Python 3.10+ |
| LLM Framework | LangChain, **LangGraph** |
| LLM | OpenAI `gpt-4o-mini` (교체 가능) |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector DB | **ChromaDB** (로컬 영속화) |
| PDF → MD | **pymupdf4llm** + PyMuPDF (원문자 폰트 디코딩 패치 포함) |
| API | FastAPI + Uvicorn |
| Packaging | Docker + docker-compose |
| Config | pydantic-settings |

---

## Data Pipeline

본 프로젝트는 **국세청 홈택스 공식 PDF 3건**을 소스로 사용합니다.

| 파일 | 페이지 | 변환 후 MD |
|---|---|---|
| `2025_법인세_신고안내.pdf` | 744p | ~720 KB |
| `2025_1기확정_부가가치세_신고안내매뉴얼.pdf` | 128p | ~150 KB |
| `원천징수의무자를위한_연말정산_신고안내.pdf` | 26p | ~36 KB |

> **Note**: 원본 PDF(총 ~36MB)는 저장소 용량 절감을 위해 Git 에 포함하지 않습니다. 변환된 `data/samples/*.md` 만 포함되므로 인덱싱·챗봇 실행은 PDF 없이 바로 가능합니다. PDF 를 다시 변환해보고 싶다면 [국세청 세무 서식·자료실](https://www.nts.go.kr) 에서 해당 연도 『법인세 신고안내』, 『부가가치세 신고안내 매뉴얼』, 『원천징수의무자를 위한 연말정산 신고안내』 를 내려받아 `data/raw/` 에 넣어주세요.

### 오프라인 변환 (`src/scripts/pdf_to_md.py`)

국세청 PDF 는 **커스텀 폰트로 인코딩된 원문자(㉑~㉛)** 와 표지/디자인 페이지의 **PUA 문자** 때문에 일반 추출 도구로는 텍스트가 깨집니다. 이를 해결하기 위해 다음 전략으로 변환합니다:

1. **표지/디자인 페이지 스킵** — 비 ASCII/한글 비율이 30% 초과인 페이지는 건너뜀
2. **페이지별 `pymupdf4llm` Markdown 추출**
3. **U+FFFD 감지 시 raw 텍스트로 폴백** — pymupdf4llm 이 원문자를 `�` 로 치환하는 문제 회피
4. **원문자 매핑 적용** — 커스텀 폰트가 쓰는 한글 프록시(`쇭쇶` 등 14개 시퀀스) 를 `⑳·㉑~㉛` 로 변환
5. **그림·벡터그래픽 플레이스홀더 제거** — 임베딩 노이즈 억제

실행:
```bash
python -m src.scripts.pdf_to_md --overwrite
# data/raw/*.pdf → data/samples/*.md
```

### 청킹 (`src/rag/loader.py`)

- **1차 분할**: `MarkdownHeaderTextSplitter` (h1~h4) 로 헤더 단위 분할 + `section_path` 메타데이터 자동 부여
- **2차 분할**: `RecursiveCharacterTextSplitter` 로 `chunk_size=1000, chunk_overlap=150` 적용

결과: **총 2,287 청크**, 99.8% 가 `section_path` 메타데이터 보유 → 검색 결과에 `법인세 > 가. 이월결손금` 같은 컨텍스트 표시.

---

## Quick Start

### 1. Local 실행

```bash
git clone https://github.com/<your-id>/finance-rag-agent.git
cd finance-rag-agent

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env 파일을 열고 OPENAI_API_KEY 를 설정하세요.

# (선택) PDF → Markdown 변환 — data/samples/*.md 가 없는 경우에만
python -m src.scripts.pdf_to_md --overwrite

# 1) ChromaDB 에 인덱싱 (최초 1회 / 청크 파라미터 변경 시 --reset)
python -m src.scripts.ingest --reset

# 2a) CLI 챗
python -m src.scripts.chat_cli

# 2b) 또는 FastAPI 서버 + Swagger UI
uvicorn src.api.main:app --reload --port 8000
# 브라우저로 http://localhost:8000/docs 접속
```

### 2. Docker 실행

```bash
echo "OPENAI_API_KEY=sk-..." > .env

# /chat 보호 비밀번호 (설정하지 않으면 /chat 은 503 으로 잠깁니다)
cp .env_pwd.example .env_pwd
# .env_pwd 를 열어 PAID_MODEL_PASSWORD 를 실제 값으로 바꾸세요

docker compose up --build -d

# 컨테이너 내부에서 최초 인덱싱
docker compose exec agent python -m src.scripts.ingest --reset

# 헬스체크
curl http://localhost:8000/health
```

### 3. API 호출 예시

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "이월결손금은 몇 년까지 공제할 수 있어?", "password": "<비밀번호>"}'
```

응답:

```json
{
  "answer": "이월결손금은 각 사업연도 개시일 전 15년 이내에 발생한 결손금에 대해 공제할 수 있습니다. 단, 2019.12.31. 이전에 개시한 사업연도에서 발생한 결손금은 10년, 2008.12.31. 이전에 개시한 사업연도에서 발생한 결손금은 5년으로 제한됩니다.",
  "query_type": "rag",
  "grounded": true,
  "rewrite_count": 0,
  "sources": [
    {
      "source": "2025_법인세_신고안내.md",
      "section_path": "가. 이월결손금",
      "snippet": "각 사업연도 개시일 전 15년 이내에 개시한 사업연도에서 발생한 결손금 ..."
    }
  ]
}
```

Swagger UI (`http://localhost:8000/docs`) 에서 `Try it out` 으로 대화형 테스트도 가능합니다.

### 4. 유료 API 보호 (비밀번호)

`/chat` 은 호출 한 번마다 **임베딩(검색) + LLM(생성)** 으로 실제 요금이 청구됩니다.
데모 서버를 LAN/인터넷에 열어 두면 누구나 크레딧을 소진시킬 수 있으므로, 질의는
비밀번호를 통과해야만 실행됩니다. 검증은 프론트엔드가 아니라 **서버에서** 수행합니다.

```bash
cp .env_pwd.example .env_pwd
# PAID_MODEL_PASSWORD=<원하는 비밀번호>   ← .example 이 아니라 .env_pwd 를 고칠 것
docker compose up -d agent
```

| 설정 (`.env_pwd`) | 기본값 | 설명 |
| --- | --- | --- |
| `PAID_MODEL_PASSWORD` | (빈 값) | `/chat` 호출 비밀번호. **비워 두면 `/chat` 은 아예 차단**(503) |
| `PAID_SESSION_MINUTES` | `60` | 한 번 인증한 뒤 재입력 없이 쓸 수 있는 시간(분) |

동작:

- **fail-closed** — 비밀번호가 설정되지 않으면 `/chat` 은 열리지 않고 `503` 을 반환합니다.
- **세션 쿠키** — `POST /unlock` 또는 첫 성공한 `/chat` 호출 시 서명된 HttpOnly 쿠키를
  발급해, 이후 `PAID_SESSION_MINUTES` 분간은 비밀번호 없이 질의할 수 있습니다.
  `POST /lock` 으로 즉시 해제합니다.
- **쿠키 위조 불가** — HMAC-SHA256 서명이며, 서명 키에 비밀번호가 포함되어 있어
  **비밀번호를 바꾸면 기존 쿠키가 모두 무효**가 됩니다.
- **무차별 대입 완화** — 같은 IP 에서 5회 틀리면 5분간 `429` 로 차단됩니다.
- `/health` 와 `/docs` 는 과금이 없어 계속 공개됩니다. `/health` 는 비밀번호 설정 여부와
  남은 세션 시간만 알려주고, 비밀번호 자체는 절대 노출하지 않습니다.

브라우저(`/docs`)에서 쓰는 순서:

1. `POST /unlock` → `Try it out` → `{"password": "<비밀번호>"}` → `Execute`
2. 이후 `POST /chat` 은 `password` 없이 `{"question": "..."}` 만으로 호출됩니다.

```bash
# 터미널 — 매 호출에 password 를 넣거나
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"question": "부가가치세 세율은?", "password": "<비밀번호>"}'

# 쿠키를 저장해 재사용
curl -c jar.txt -X POST http://localhost:8000/unlock \
  -H "Content-Type: application/json" -d '{"password": "<비밀번호>"}'
curl -b jar.txt -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" -d '{"question": "부가가치세 세율은?"}'
```

> **⚠️ 나중에 비밀번호를 바꿀 때:** `env_file` 값은 컨테이너가 **생성될 때** 주입되어 그대로 굳습니다.
> `restart` 로는 반영되지 않으니 반드시 **재생성**하세요.
>
> ```bash
> docker compose up -d --force-recreate agent
> # 반영 확인 (컨테이너가 실제로 들고 있는 값)
> docker compose exec agent printenv PAID_MODEL_PASSWORD
> ```
>
> 비밀번호를 바꾸면 기존 인증 쿠키는 모두 무효가 되므로 브라우저에서 다시 입력해야 합니다.
> 옛 비밀번호로 5회 이상 시도했다면 해당 IP 가 5분간 차단(429)된 상태일 수 있습니다 —
> 기다리거나 위 재생성 명령으로 초기화됩니다.

> CLI(`python -m src.scripts.chat_cli`)와 인덱싱 스크립트는 그래프를 직접 호출하므로
> 비밀번호가 필요 없습니다. 이 보호는 **외부에 노출되는 HTTP 표면**만을 대상으로 합니다.

---

## Project Structure

```
finance-rag-agent/
├── src/
│   ├── config.py               # pydantic-settings 기반 설정
│   ├── rag/
│   │   ├── loader.py           # MarkdownHeaderTextSplitter + Recursive 2단 분할
│   │   └── vectorstore.py      # ChromaDB wrapper
│   ├── agent/
│   │   ├── state.py            # AgentState TypedDict
│   │   ├── nodes.py            # LangGraph 노드 6개 + 라우터
│   │   └── graph.py            # StateGraph 조립
│   ├── api/
│   │   ├── main.py             # FastAPI app (/health, /chat)
│   │   └── schemas.py          # Pydantic I/O 스키마 (section_path 포함)
│   └── scripts/
│       ├── pdf_to_md.py        # PDF → Markdown 변환 (커스텀 폰트 보정)
│       ├── ingest.py           # --reset 지원 인덱싱 스크립트
│       └── chat_cli.py         # CLI 챗 (소스·섹션경로 노출)
├── data/
│   ├── raw/                    # 국세청 PDF 원본 (pdf_to_md.py 입력)
│   ├── samples/                # 변환된 Markdown (인덱싱 소스)
│   └── legacy_samples/         # 초기 데모용 MD (비활성)
├── tests/                      # pytest smoke 테스트
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## LangGraph Node 설계

| Node | 역할 | 주요 로직 |
|------|------|----------|
| `classify` | 질문 분류 | LLM 으로 `rag` / `general` 이진 분류 |
| `retrieve` | 벡터 검색 | ChromaDB `similarity_search(k=10)` — 2,287 청크 커버리지 확보 |
| `generate` | 답변 생성 | 검색된 컨텍스트만 근거로 LLM 답변 (외부 지식 금지 프롬프트) |
| `verify` | 근거 검증 | 답변이 참고 문서에 근거하는지 LLM 판정. "찾을 수 없음" 응답은 ungrounded 처리해 rewrite 유도 |
| `rewrite` | 쿼리 재작성 | 근거 부족 시 검색어를 동의어/상위 개념으로 재구성 (`MAX_REWRITES=2`) |
| `general` | 일반 응답 | RAG 불필요 질문(인사·잡담) 처리 |

**State 정의 (`src/agent/state.py`)**

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

## Sample Questions

아래는 **실제 인덱스(2,287 청크)로 그래프 전 과정을 돌려 `grounded: true` 를 확인한** 질문들입니다.

| 질문 | rewrite_count |
| --- | --- |
| 간이과세자의 업종별 부가가치율을 알려주세요 | 0 |
| 이월결손금 공제 한도는 어떻게 되나요? | 0 |
| 원천징수의무자란 무엇인가요? | 0 |
| 사업자 미등록 가산세는 몇 퍼센트인가요? | 0 |
| 부가가치세 납부기한 연장이 가능한 경우는? | 0 |
| 고용증대세액공제 적용 시 자주 발생하는 오류는? | 0 |
| 지급명세서를 늦게 제출하면 가산세가 얼마인가요? | 0 |
| 부가가치세 기한 후 신고는 어떻게 하나요? | 0 |
| 법인세율은 과세표준 구간별로 어떻게 되나요? | 0 |
| 최저한세율은 얼마인가요? | 0 |

### 에이전트 동작을 보여주는 질문

| 질문 | 결과 | 보여주는 것 |
| --- | --- | --- |
| 명세서 늦으면 얼마? | `grounded: true`, `rewrite_count: 1` | 구어체 질문 → 1차 검색 실패 → `verify` 가 근거 부족 판정 → `rewrite` 재작성 → 재검색 성공. **재검색 루프** |
| 상속세 세율은 어떻게 되나요? | `grounded: false`, `rewrite_count: 2` | 코퍼스 밖 주제 → 지어내지 않고 **정직한 거절**(재작성 상한 도달) |
| 안녕하세요, 뭘 할 수 있어요? | `query_type: general` | `classify` 분기 → 검색 없이 즉답 |

### 이 코퍼스가 답하지 못하는 질문

인덱싱된 문서는 국세청 **실무 신고 매뉴얼**이라 기본 개념을 평문으로 서술하지 않습니다.

- ❌ **"부가가치세 세율은 얼마인가요?"** — 매뉴얼에 "세율은 10%" 라는 문장이 없습니다.
  문서 안의 `10%` 는 전부 간이과세자 부가가치율·과소신고 가산세 등 다른 항목이라,
  재작성 2회 후 거절로 끝납니다.
- ⚠️ **"미등록하면 얼마 물어?"** — `grounded: true` 가 나오지만 답이 해외금융계좌 미신고
  과태료로 새어나갑니다. 정답처럼 보여 더 위험한 유형입니다.

**"세율이 얼마냐"는 사전식 질문에 약하고, "어떤 경우에 / 어떻게 / 무슨 오류" 같은
절차·사례 질문에 강합니다.**

---

## Roadmap

- [ ] **하이브리드 검색 (BM25 + 벡터)** — 계산식·수치 질의의 청크 파편화 문제 완화
- [ ] 멀티턴 대화 지원 (`MessagesState` 및 체크포인터 연계)
- [ ] Tool 호출 노드 추가 (VAT 계산기, 법인세 시뮬레이터)
- [ ] SSE 기반 스트리밍 응답
- [ ] RAGAS 기반 자동 평가 파이프라인

---

## Notes

- 데이터 소스는 **국세청 홈택스에서 배포한 공개 PDF**(2025년 신고안내 매뉴얼) 이며 학습/데모 목적으로만 사용합니다.
- 세법 문서 특유의 표·수식 구조는 PDF → Markdown 변환 과정에서 일부 파편화되므로, **본 시스템의 답변은 실제 세무 판단의 근거가 될 수 없습니다**. 정확한 세무 자문은 세무사·국세청 공식 안내를 참조하세요.
- 개인 정보·고객사 자료는 포함되어 있지 않습니다.

## License

MIT
