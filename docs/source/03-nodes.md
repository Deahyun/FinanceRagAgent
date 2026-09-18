# `src/agent/nodes.py` — 그래프의 각 단계

이 파일이 **실제 일**을 합니다. 질문 분류, 검색, 답 생성, 근거 검증, 검색어 수정, 일반 대화가 모두 여기 있습니다.
`graph.py` 는 이 함수들을 어떤 순서로 부를지만 정합니다.

각 함수는 `state` 를 받아 **고칠 칸만** dict 로 반환합니다. 부수 효과(전역 변수 변경)를 거의 두지 않아 테스트하기 쉽습니다.

## 파일 위쪽: 공통 LLM

```python
llm = ChatOpenAI(
    model=settings.openai_model,
    api_key=settings.openai_api_key,
    temperature=0,
)

MAX_REWRITES = 2
```

- 모듈을 import 할 때 모델 클라이언트가 하나 만들어집니다. 노드마다 새로 만들지 않습니다.
- `temperature=0` 은 같은 입력에 답이 덜 흔들리게 합니다. 분류·검증처럼 “두 단어 중 하나”를 원할 때 유리합니다.
- `MAX_REWRITES = 2` 는 재검색을 무한히 돌리지 않기 위한 상한입니다. `route_after_verify` 가 이 숫자를 봅니다.

프롬프트는 `ChatPromptTemplate` 입니다. `system` 은 역할, `human` 은 이번 입력입니다.
`{question}` 같은 중괄호는 `.invoke({...})` 할 때 채워집니다.

---

## 1. `classify_node` — 검색이 필요한 질문인가?

**읽음:** `question`  
**씀:** `query_type`

시스템 메시지 요지: 한국 금융/세무/회계 문서가 필요하면 `rag`, 인사·잡담이면 `general`. **그 두 단어만** 출력.

```python
raw = chain.invoke({"question": state["question"]}).strip().lower()
query_type = "rag" if "rag" in raw else "general"
```

모델이 `"RAG"` 나 `"rag."` 처럼 조금 벗어나도, 글자에 `rag` 가 있으면 검색 경로로 보냅니다.
`rag` 가 전혀 없으면 `general` 입니다. 애매하면 검색을 안 하는 쪽으로 기울습니다.

인사(“안녕하세요”)는 여기서 걸러져 문서 검색 비용이 나가지 않습니다.

---

## 2. `retrieve_node` — 비슷한 글 10개

**읽음:** `rewritten_query` 또는 `question`  
**씀:** `retrieved_docs`

```python
query = state.get("rewritten_query") or state["question"]
docs = vs.similarity_search(query, k=10)
```

1. 재작성된 검색어가 있으면 그것을 씁니다. 첫 시도에는 없습니다.
2. `get_vectorstore()` 로 로컬 ChromaDB 를 엽니다.
3. 질문 벡터와 가까운 청크 **10개**를 가져옵니다.

`k=10` 인 이유: 법인세 안내가 700페이지가 넘고 청크가 2,000개 넘게라, 3~4개만 가져오면 정답이 있는 조각이 빠지기 쉽습니다.

MMR(다양하게 뽑기)은 쓰지 않습니다. 한국어 세무 문서에서는 “비슷한 듯 다른” 조각이 핵심 문단을 밀어내는 경우가 있어, 단순 유사도만 씁니다.

OpenAI **임베딩 API** 가 여기서 한 번 호출됩니다. 질의 요금의 일부입니다.

---

## 3. `generate_node` — 참고 문서만 보고 답하기

**읽음:** `retrieved_docs`, `question`  
**씀:** `answer`

문서가 하나도 없으면 LLM 을 부르지 않고 고정 문구를 반환합니다.

```python
if not state.get("retrieved_docs"):
    return {"answer": "제공된 문서에서 해당 내용을 찾을 수 없습니다."}
```

있으면 10개 본문을 `\n\n---\n\n` 로 이어 `context` 로 넣습니다.
시스템 프롬프트가 강하게 제한합니다.

- 참고 문서만 근거로 할 것
- 없으면 위 고정 문구만
- 추측·외부 지식 금지
- 한국어, 간결하게

생성에 쓰는 질문은 **원래 `question`** 입니다. 재작성된 검색어로 답을 바꾸지 않습니다.

이 단계에서 OpenAI **채팅 API** 가 호출됩니다.

---

## 4. `verify_node` — 답이 문서에 있는가?

**읽음:** `retrieved_docs`, `answer`  
**씀:** `grounded` (`True` / `False`)

세 갈래입니다.

1. 검색 결과가 없다 → `grounded=False` (LLM 호출 없음)
2. 답에 `"찾을 수 없습니다"` 가 있다 → `grounded=False`  
   일부러 재검색 루프를 **최소 한 번** 타게 합니다. 첫 검색이 빗나갔을 때를 위한 장치입니다.
3. 그 외 → 검증용 LLM 이 `grounded` 또는 `ungrounded` 만 말함  
   `verdict == "grounded"` 일 때만 `True`. 철자가 조금 달라도 실패로 봅니다.

검증도 채팅 API 를 씁니다. RAG 질문 한 건은 대략 **분류 + (검색 임베딩) + 생성 + 검증** 이고, 재작성되면 검색·생성·검증이 더 붙습니다.

---

## 5. `rewrite_node` — 검색어만 고치기

**읽음:** `question`, `rewrite_count`  
**씀:** `rewritten_query`, `rewrite_count`

```python
new_query = chain.invoke({"question": state["question"]}).strip()
count = state.get("rewrite_count", 0) + 1
return {"rewritten_query": new_query, "rewrite_count": count}
```

프롬프트: 같은 뜻을 유지하되 동의어·상위/하위 개념으로 검색이 잘 되게, **한 줄만**.

예: `명세서 늦으면 얼마?` → `지급명세서 지연 제출 가산세`

`rewrite_count` 가 없는 상태를 대비해 `0` 을 기본으로 씁니다.
그래프 다음 화살표는 항상 `retrieve` 입니다 (`graph.py`).

---

## 6. `general_node` — 검색 없는 짧은 인사

**읽음:** `question`  
**씀:** `answer`, `grounded=True`, `retrieved_docs=[]`

세무 챗봇 말투로 한두 문장만 답합니다.
`grounded=True` 로 두는 이유는 검증 루프를 타지 않기 때문입니다. 이 노드는 바로 END 로 갑니다.
빈 문서 목록을 넣어 두면 API 가 출처를 만들 때 오류가 나지 않습니다.

---

## 분기 함수 (노드가 아니라 “다음 상자 이름”을 반환)

LangGraph 의 `add_conditional_edges` 에 넘기는 함수입니다.
상태의 칸을 바꾸지 않고, **다음에 갈 노드 이름 문자열**만 반환합니다.

### `route_by_type`

```python
return "retrieve" if state["query_type"] == "rag" else "general"
```

`graph.py` 에서 이 문자열을 실제 노드에 대응시킵니다.

```python
{"retrieve": "retrieve", "general": "general"}
```

### `route_after_verify`

```python
if state.get("grounded"):
    return "end"
if state.get("rewrite_count", 0) >= MAX_REWRITES:
    return "end"
return "rewrite"
```

| 상황 | 다음 |
|------|------|
| 근거 있음 | 종료 |
| 근거 없고 아직 2번 미만 재작성 | `rewrite` |
| 근거 없고 이미 2번 | 종료 (없는 내용을 지어내지 않음) |

`end` 는 노드 이름이 아닙니다. `graph.py` 가 `END` 상수에 연결합니다.

---

## 한 질문에서 호출 횟수 (대략)

| 경로 | LLM 채팅 | 임베딩 |
|------|----------|--------|
| 인사 (general) | classify 1 + general 1 | 0 |
| RAG, 한 번에 성공 | classify + generate + verify = 3 | 1 |
| RAG, 재작성 1회 후 성공 | 위 + rewrite + generate + verify, 임베딩 1회 추가 | 2 |
| RAG, 2회 재작성 후에도 실패 | 채팅 최대 3 + 2*(rewrite+generate+verify) | 3 |

그래서 `/chat` 을 비밀번호로 막는 것입니다. 한 질문이 여러 번 과금될 수 있습니다.
