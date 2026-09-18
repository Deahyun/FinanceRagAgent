# 전체 구조

## 폴더 지도

```
FinanceRagAgent/
├── src/                     실제 프로그램
│   ├── config.py            설정 (.env, .env_pwd 읽기)
│   ├── agent/               질문 처리 그래프 (분류·검색·답변·검증)
│   ├── rag/                 문서를 쪼개고 Vector DB 에 넣고 찾기
│   ├── api/                 HTTP 창구 (FastAPI)
│   └── scripts/             PDF 변환, 인덱싱, 터미널 챗
├── data/
│   ├── raw/                 원본 PDF (Git 에 없음, 직접 넣을 때 사용)
│   ├── samples/             변환된 Markdown — 인덱싱의 진짜 재료
│   └── legacy_samples/      예전 데모용 MD (지금은 쓰지 않음)
├── tests/                   간단한 자동 테스트
├── docs/                    지금 읽고 있는 설명
├── chroma_db/               인덱싱 후 생기는 검색 DB (Git 에 없음)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

`src/` 안의 `__init__.py` 는 “이 폴더는 파이썬 패키지입니다” 라는 표시입니다.

## 큰 그림: 준비 단계와 질문 단계

프로그램은 **두 시기**로 나뉩니다.

```
[준비 — 한 번 또는 문서가 바뀔 때]
  PDF  (선택)     →  Markdown     →  청크     →  ChromaDB
  pdf_to_md.py       data/samples    loader.py    ingest.py

[질문 — 매번]
  사용자 질문  →  LangGraph 에이전트  →  답변 + 근거 출처
```

준비 없이 질문하면 검색할 내용이 없습니다.
처음 한 번은 `python -m src.scripts.ingest --reset` 을 실행해야 합니다.

## 질문이 지나가는 길

```
터미널(chat_cli)  또는  브라우저/curl (FastAPI /chat)
        │
        ▼
  agent_graph.invoke({ question, rewrite_count: 0 })
        │
        ▼
  ┌─────────────┐
  │  classify   │  세무 질문인가, 인사인가?
  └──┬───────┬──┘
     │       │
     │       └──────────► general ──► 끝 (검색 없음)
     │
     ▼
  retrieve  ──►  generate  ──►  verify
     ▲                            │
     │          근거 있음          ├──► 끝
     │          또는 재시도 소진
     │
     └── rewrite ◄── 근거 부족이고 아직 재시도 남음
```

코드는 `src/agent/graph.py` 가 이 상자와 화살표를 조립합니다.

## 각 단계가 하는 일

| 단계 | 파일 | 하는 일 |
|------|------|---------|
| classify | `src/agent/nodes.py` | LLM 이 질문을 `rag` 또는 `general` 로만 답하게 함 |
| retrieve | 같은 파일 | ChromaDB 에서 질문과 비슷한 글 10개(`k=10`)를 가져옴 |
| generate | 같은 파일 | 그 10개만 보고 한국어로 답함. 문서에 없으면 “찾을 수 없습니다” |
| verify | 같은 파일 | 답이 문서에 근거하는지 LLM 이 `grounded` / `ungrounded` 로 판정 |
| rewrite | 같은 파일 | 검색어를 동의어·상위/하위 개념으로 바꿔 씀 |
| general | 같은 파일 | 인사·잡담에 한두 문장으로 답함 |

검증에서 “찾을 수 없습니다” 도 **근거 없음** 으로 칩니다.
일부러 검색어를 바꿔 **한 번은 다시 찾게** 하기 위해서입니다.
무한히 돌지 않도록 재작성은 **최대 2회** (`MAX_REWRITES = 2`) 입니다.

## 상태(메모장)에 쌓이는 값

단계들은 하나의 사전(`AgentState`)을 나눠 씁니다. `src/agent/state.py`

| 키 | 뜻 |
|----|----|
| `question` | 사용자가 친 원래 질문 |
| `query_type` | `rag` 또는 `general` |
| `rewritten_query` | 재작성된 검색어 (없으면 원래 질문으로 검색) |
| `retrieved_docs` | 찾아 온 문서 조각들 |
| `answer` | 최종 답 |
| `grounded` | 답이 문서에 근거했는지 |
| `rewrite_count` | 검색어를 몇 번 바꿨는지 |

각 노드는 이 사전의 **일부만** 돌려줍니다. LangGraph 가 나머지를 합칩니다.

## 문서가 검색 가능해지기까지

```
data/samples/*.md
        │  TextLoader 로 파일 단위 로드
        ▼
  Markdown 헤더(# ~ ####) 기준 1차 분할
        │  섹션 이름들을 이어 section_path 로 저장
        │  예: "법인세 > 가. 이월결손금"
        ▼
  길이 기준 2차 분할 (1000자, 겹침 150자)
        │
        ▼
  OpenAI embedding  →  ChromaDB (컬렉션 이름 finance_docs)
```

한국어 세법 문장은 길고 조·호·목 단위로 이어집니다.
너무 짧게 자르면 앞뒤가 끊겨서, 청크를 **1000자 / 겹침 150자** 로 잡았습니다.

검색은 **유사도 검색**만 씁니다. MMR(다양성 검색)은 한국어 세무 문서에서
핵심 조각을 밀어내는 경우가 있어 쓰지 않습니다.

## API 계층이 하는 일 / 하지 않는 일

`src/api/main.py` 는 HTTP 만 담당합니다.

1. 비밀번호(또는 이미 발급된 쿠키)를 확인한다.
2. `agent_graph.invoke(...)` 를 호출한다.
3. 검색된 문서에서 출처·섹션·앞부분 160자를 잘라 JSON 으로 돌려준다.

세무 로직은 API 에 없습니다. 같은 그래프를 CLI 도 그대로 부릅니다.

## 비밀번호 보호가 있는 이유

`/chat` 한 번은 **임베딩(검색) + LLM(생성)** 이라 OpenAI 에 요금이 나갑니다.
서버가 열려 있으면 누구나 크레딧을 쓸 수 있어서, 서버가 비밀번호를 검사합니다.
프론트에서만 막는 방식은 우회할 수 있어서 쓰지 않습니다.

- 비밀번호가 **비어 있으면** `/chat` 은 503 으로 잠깁니다 (실수로 열어 두지 않음).
- 맞히면 서명된 쿠키를 주고, 기본 **60분** 은 다시 묻지 않습니다.
- 같은 IP 에서 5번 틀리면 5분간 429 로 막습니다.
- 비밀번호를 바꾸면 예전 쿠키는 바로 무효가 됩니다.

CLI 와 인덱싱 스크립트는 이 보호를 타지 않습니다. **밖으로 열린 HTTP** 만 대상입니다.

## 왜 이렇게 나눴는가

1. **scripts** — 사람(또는 Docker)이 터미널에서 실행하는 일.
2. **rag** — 문서를 자르고 저장소에 넣고 찾기. 그래프와 분리.
3. **agent** — 질문 처리 순서. 순수 함수 노드라 테스트하기 쉽습니다.
4. **api** — JSON 을 받고 JSON 을 돌려줌. 비밀번호도 여기만.

나중에 모델을 바꾸려면 `.env` 의 `OPENAI_MODEL` 만 바꾸면 됩니다.
검색 저장소를 바꾸려면 `src/rag/vectorstore.py` 를 손보면 되고, 그래프 상자 이름은 그대로입니다.

각 소스 파일의 함수 설명은 [source/README.md](source/README.md) 에 있습니다.
