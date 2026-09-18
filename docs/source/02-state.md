# `src/agent/state.py` — 에이전트 상태

그래프의 모든 노드가 나눠 쓰는 **메모장**입니다.
질문이 들어오면 이 칸들이 하나씩 채워지고, 마지막에 API/CLI 가 칸을 읽어 답을 보여 줍니다.

파일은 짧습니다. 역할은 “데이터 모양을 약속하는 것”입니다. 로직은 없습니다.

## `AgentState`

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

`TypedDict` 는 “이 이름은 이런 타입의 딕셔너리” 라고 에디터와 타입 검사기에 알려 주는 방법입니다.
실행 중에 진짜 클래스 인스턴스가 되지는 않습니다. 실제 값은 평범한 `dict` 입니다.

`total=False` 는 **모든 키가 처음부터 있지 않아도 된다**는 뜻입니다.
시작 시에는 보통 이것만 있습니다.

```python
{"question": "이월결손금은 몇 년까지 공제할 수 있어?", "rewrite_count": 0}
```

노드가 `{"query_type": "rag"}` 만 반환하면 LangGraph 가 기존 dict 에 합칩니다.

## 칸마다 뜻

| 키 | 누가 쓰나 | 뜻 |
|----|-----------|----|
| `question` | 호출자가 넣음. generate / classify / rewrite 가 읽음 | 사용자가 친 **원래** 질문. 재작성해도 바꾸지 않음 |
| `query_type` | `classify_node` | `rag`(문서 검색) 또는 `general`(인사) |
| `rewritten_query` | `rewrite_node` 가 씀, `retrieve_node` 가 읽음 | 검색용으로 고친 문장 |
| `retrieved_docs` | `retrieve_node` / `general_node` | LangChain `Document` 목록. 본문 + metadata |
| `answer` | `generate_node` 또는 `general_node` | 사용자에게 보여줄 글 |
| `grounded` | `verify_node` 또는 `general_node` | 답이 참고 문서에 근거하는지 |
| `rewrite_count` | 호출자가 0으로 시작, `rewrite_node` 가 +1 | 검색어를 몇 번 바꿨는지. 2가 되면 루프 종료 |

## 왜 `question` 과 `rewritten_query` 를 나누나

검색이 실패하면 검색어만 바꿉니다.
답변 생성은 항상 **원래 질문**을 봅니다. 사용자가 물은 뜻을 잃지 않기 위해서입니다.

```
retrieve: rewritten_query 가 있으면 그것으로 검색, 없으면 question
generate: 항상 question
rewrite: 항상 question 을 보고 새 검색어를 만듦
```

## `retrieved_docs` 안의 `Document`

LangChain 의 `Document` 는 대략 다음 모양입니다.

```python
Document(
    page_content="각 사업연도 개시일 전 15년 이내에 ...",
    metadata={
        "source": "2025_법인세_신고안내.md",
        "h1": "...",
        "section_path": "가. 이월결손금",
    },
)
```

- `page_content` — 검색·답변에 쓰는 본문
- `metadata["source"]` — 파일 이름
- `metadata["section_path"]` — 목차 경로. CLI 와 API 출처 표시에 사용

`h1`~`h4` 는 분할 단계에서 잠깐 쓰이고, 바깥으로 나가는 JSON 에는 `section_path` 만 실립니다.

## `graph.py` 와의 연결

```python
workflow = StateGraph(AgentState)
```

그래프를 만들 때 상태 타입을 넘깁니다. 각 `add_node` 함수는 이 상태를 인자로 받고, 부분 dict 를 반환해야 합니다.
칸 이름을 여기서 바꾸면 `nodes.py` 와 `main.py` 도 같이 바꿔야 합니다.
