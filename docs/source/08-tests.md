# `tests/test_agent.py` — 기본 동작 확인

세 가지 smoke 테스트만 있습니다. 전체 정답률을 재는 평가 세트는 아닙니다.

실행:

```powershell
pytest
```

프로젝트 루트에서 실행합니다. `OPENAI_API_KEY` 가 환경(또는 `.env` 로드 전 환경)에 있어야 LLM 테스트가 돕니다.

---

## fixture `graph`

```python
@pytest.fixture(scope="module")
def graph():
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    from src.agent.graph import build_graph
    return build_graph()
```

- `scope="module"` — 이 파일의 테스트가 그래프를 **한 번만** 조립해 공유
- 키가 없으면 skip. CI 에서 비밀 키 없이 돌릴 수 있게 하기 위함
- import 를 fixture 안으로 미룬 이유: 키가 없을 때 `config.py` / `nodes.py` 로드로 전체가 터지지 않게 하려는 쪽에 가깝습니다.  
  다만 `from src.agent.graph import build_graph` 는 결국 `nodes` → `settings` 를 불러 **키가 필요**합니다.  
  skip 은 **환경 변수** `OPENAI_API_KEY` 를 봅니다. pytest 가 `.env` 를 자동으로 넣지는 않습니다.

키가 `.env` 에만 있고 셸에는 없으면, fixture 가 skip 하거나, skip 을 통과한 뒤 Settings 가 실패할 수 있습니다.
로컬에서 테스트를 돌릴 때는 가상환경을 켠 뒤 키를 export 하거나, pytest 실행 전에 `.env` 를 로드하는 습관이 필요합니다.

---

## `test_general_greeting`

질문 `"안녕하세요"` 를 `invoke` 합니다.

- `query_type == "general"` — classify 가 검색으로 보내지 않았는지
- `answer` 가 비어 있지 않은지

검색 DB 가 없어도 통과해야 합니다. general 경로는 Chroma 를 안 엽니다.

---

## `test_rag_question_classification`

질문 `"부가가치세 일반 세율은 얼마인가요?"`

- `query_type == "rag"`
- `answer` 가 존재

**정답이 맞는지는 보지 않습니다.** 분류가 RAG 로 가고 문자열이 나오기만 하면 됩니다.
README 에도 적혀 있듯, 이 질문은 매뉴얼에 “세율은 10%” 문장이 없어 거절로 끝날 수 있습니다.
인덱스가 비어 있어도 답이 “찾을 수 없습니다” 이면 assert 는 통과합니다.
인덱스가 없고 검색에서 예외가 나면 실패합니다.

---

## `test_graph_compiles`

fixture 를 쓰지 않습니다. API 키 검사도 없습니다.

```python
from src.agent.graph import build_graph
g = build_graph()
assert g is not None
```

노드 함수는 실행하지 않고, `add_node` / 화살표 이름만 맞으면 됩니다.
다만 `graph.py` 를 import 하면 `nodes.py` 와 `settings` 가 따라오므로,
**키가 전혀 없으면 이 테스트도 Settings 검증에서 실패할 수 있습니다.**

키가 있는 개발 PC 에서는 그래프 조립이 깨졌는지 빠르게 보는 용도입니다.

---

## 이 테스트가 안 보는 것

- `verify` 가 정말 grounded 를 맞게 주는지
- `rewrite` 루프가 2회에서 멈추는지
- `/chat` 비밀번호, 429, 쿠키
- PDF 변환, 청킹 결과 개수
- 샘플 질문 표의 정답

그런 검사는 아직 코드에 없습니다. 동작을 손으로 보려면 [getting-started.md](../getting-started.md) 와 CLI 가 더 확실합니다.
