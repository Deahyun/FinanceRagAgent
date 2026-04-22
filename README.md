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
  -d '{"question": "이월결손금은 몇 년까지 공제할 수 있어?"}'
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

실제 테스트 시 정상 답변되는 질문 예시:

- "이월결손금은 몇 년까지 공제할 수 있어?" → 15년/10년/5년 구분 답변
- "전자세금계산서 가산세는 얼마야?" → 미발급 2%, 지연 1%, 미전송 0.5% 등 구조적 답변
- "간이과세자와 일반과세자 차이는?" → 세액 계산·공제·적용대상 비교
- "연말정산에서 인적공제 기본공제 대상자 요건이 뭐야?" → 소득금액 100만원 등 요건 답변
- "안녕하세요" → `general` 분기로 라우팅되어 간단 인사 응답

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
