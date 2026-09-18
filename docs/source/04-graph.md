# `src/agent/graph.py` — 단계를 그래프로 조립

상자는 `nodes.py` 에 있고, 이 파일은 **상자를 화살표로 잇습니다.**
실행 순서의 유일한 정의입니다.

## `build_graph()`

```python
workflow = StateGraph(AgentState)
```

상태가 `AgentState` 모양인 빈 그래프를 만듭니다.

### 상자 등록

```python
workflow.add_node("classify", classify_node)
workflow.add_node("retrieve", retrieve_node)
workflow.add_node("generate", generate_node)
workflow.add_node("verify", verify_node)
workflow.add_node("rewrite", rewrite_node)
workflow.add_node("general", general_node)
```

첫 인자는 **그래프 안에서의 이름**, 둘째는 파이썬 함수입니다.
분기 함수가 돌려주는 문자열(`"retrieve"`, `"rewrite"` …)은 이 이름과 같아야 합니다.

### 시작점

```python
workflow.set_entry_point("classify")
```

`invoke` 하면 무조건 분류부터 합니다.

### 고정 화살표 `add_edge`

조건 없이 항상 다음으로 갑니다.

```python
workflow.add_edge("retrieve", "generate")
workflow.add_edge("generate", "verify")
workflow.add_edge("rewrite", "retrieve")   # 루프
workflow.add_edge("general", END)
```

`END` 는 LangGraph 가 제공하는 “여기서 멈춤” 표시입니다.

### 조건부 화살표 `add_conditional_edges`

```python
workflow.add_conditional_edges(
    "classify",
    route_by_type,
    {"retrieve": "retrieve", "general": "general"},
)

workflow.add_conditional_edges(
    "verify",
    route_after_verify,
    {"rewrite": "rewrite", "end": END},
)
```

세 인자:

1. 출발 노드
2. 상태를 보고 **키 문자열**을 고르는 함수
3. 그 키를 실제 목적지(노드 이름 또는 `END`)에 대응하는 사전

`route_after_verify` 가 `"end"` 를 주면 그래프가 끝납니다. `"end"` 라는 이름의 노드는 없습니다.

## 컴파일과 전역 인스턴스

```python
return workflow.compile()

agent_graph = build_graph()
```

`compile()` 은 실행 가능한 객체를 만듭니다. 이후에는 `.invoke(상태)` 로 돌립니다.

파일 맨 아래 `agent_graph = build_graph()` 때문에,
`from src.agent.graph import agent_graph` 하는 순간 그래프가 한 번 조립됩니다.
CLI 와 FastAPI 와 테스트가 **같은 조립 결과**를 씁니다.

테스트의 `test_graph_compiles` 는 OpenAI 를 부르지 않고 `build_graph()` 만 호출해, 이름과 화살표가 맞는지 확인합니다. 노드 함수 본문은 그때 실행되지 않습니다.

## 실행 방법

```python
result = agent_graph.invoke({"question": "원천징수의무자란 무엇인가요?", "rewrite_count": 0})
```

- 입력은 `AgentState` 의 일부 dict
- 출력은 칸이 채워진 dict (`answer`, `grounded`, `retrieved_docs` 등)
- 중간에 사람이 개입하지 않습니다. 분기는 `route_*` 함수가 합니다.

스트리밍·체크포인터(대화 기억)는 없습니다. 질문 한 건이 한 번의 `invoke` 입니다.

## 그림으로 다시 보기

```
                 set_entry_point
                        │
                        ▼
                   [classify]
                    /       \
         rag / retrieve    general
                  │            │
             [retrieve]     [general]
                  │            │
             [generate]        END
                  │
              [verify]
               /     \
        rewrite       end → END
           │
           └──► retrieve  (다시)
```

상자를 바꾸고 싶으면 `nodes.py` 의 함수를 고칩니다.
순서를 바꾸고 싶으면 이 파일의 `add_edge` / `add_conditional_edges` 만 고칩니다.
