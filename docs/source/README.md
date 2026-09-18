# 소스 코드 상세 설명

이 폴더는 `src/` 와 `tests/` **파이썬 소스**를 파일·함수 단위로 풀어 쓴 문서입니다.
코드를 처음 열어보는 사람을 기준으로 썼습니다.

폴더 전체 지도는 [../files.md](../files.md), 질문 한 건의 흐름은 [../example-question.md](../example-question.md) 입니다.

## 읽는 순서

프로그램이 켜질 때 파일이 로드되는 순서를 따라가면 이해가 쉽습니다.

| 순서 | 문서 | 소스 | 한 줄 |
|------|------|------|--------|
| 1 | [01-config.md](01-config.md) | `src/config.py` | `.env` 를 읽어 전역 설정 만들기 |
| 2 | [02-state.md](02-state.md) | `src/agent/state.py` | 질문 처리 중 주고받는 메모장 |
| 3 | [03-nodes.md](03-nodes.md) | `src/agent/nodes.py` | 분류·검색·답변·검증 각 단계 |
| 4 | [04-graph.md](04-graph.md) | `src/agent/graph.py` | 단계를 화살표로 연결 |
| 5 | [05-rag.md](05-rag.md) | `src/rag/loader.py`, `vectorstore.py` | 문서를 자르고 저장·검색 |
| 6 | [06-api.md](06-api.md) | `src/api/main.py`, `schemas.py` | HTTP 창구와 비밀번호 |
| 7 | [07-scripts.md](07-scripts.md) | `src/scripts/*.py` | PDF 변환, 인덱싱, 터미널 챗 |
| 8 | [08-tests.md](08-tests.md) | `tests/test_agent.py` | 동작 확인 |

## 소스 트리

```
src/
├── __init__.py              패키지 표시 (내용 없음)
├── config.py                설정
├── agent/
│   ├── __init__.py
│   ├── state.py             AgentState
│   ├── nodes.py             노드 6개 + 라우터 2개
│   └── graph.py             StateGraph 조립
├── rag/
│   ├── __init__.py
│   ├── loader.py            Markdown 로드 + 2단 분할
│   └── vectorstore.py       ChromaDB / OpenAI 임베딩
├── api/
│   ├── __init__.py
│   ├── schemas.py           요청·응답 JSON 모양
│   └── main.py              FastAPI
└── scripts/
    ├── __init__.py
    ├── pdf_to_md.py
    ├── ingest.py
    └── chat_cli.py
tests/
└── test_agent.py
```

모든 `__init__.py` 는 비어 있습니다. “이 폴더는 import 할 수 있는 패키지” 라는 표시입니다.

## 이 코드에서 반복되는 패턴

초보자가 처음 보면 낯설 수 있는 세 가지입니다.

### 1. 노드는 “상태 일부 → 고칠 칸만 담긴 dict”

```python
def classify_node(state: AgentState) -> dict:
    ...
    return {"query_type": query_type}
```

전체 상태를 새로 만들지 않습니다. LangGraph 가 반환된 키만 기존 상태에 덮어씁니다.

### 2. LLM 호출은 프롬프트 | 모델 | 파서

```python
chain = CLASSIFY_PROMPT | llm | StrOutputParser()
raw = chain.invoke({"question": state["question"]})
```

`|` 는 파이프입니다. 질문을 프롬프트에 넣고, 모델에 보내고, 답을 문자열로 받습니다.

### 3. 설정은 import 할 때 한 번 읽힌다

`src/config.py` 맨 아래 `settings = Settings()` 때문에,
다른 파일이 `from src.config import settings` 하는 순간 `.env` 가 필요합니다.
`OPENAI_API_KEY` 가 없으면 프로그램이 시작도 하기 전에 실패합니다.

## 누가 누구를 부르는가

```
chat_cli.py  ──┐
main.py /chat ─┼──► agent_graph.invoke()
tests          ─┘         │
                          ├── nodes.py (LLM, Chroma 검색)
                          └── vectorstore.py
ingest.py ──► loader.py + vectorstore.py
pdf_to_md.py  (다른 모듈을 거의 부르지 않음)
```

질문 처리의 중심은 `agent_graph` 입니다. API 와 CLI 는 입구만 다릅니다.
