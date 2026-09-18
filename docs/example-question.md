# 질문 한 건이 코드를 지나는 길

아래 질문을 예로 듭니다.

> 이월결손금은 몇 년까지 공제할 수 있어?

터미널(`chat_cli`)이든 API(`/chat`)든, 결국 같은 한 줄을 호출합니다.

```python
agent_graph.invoke({"question": "이월결손금은 몇 년까지 공제할 수 있어?", "rewrite_count": 0})
```

`agent_graph` 는 `src/agent/graph.py` 에서 조립된 그래프입니다.

---

## 0. 입구가 둘

### 터미널

`src/scripts/chat_cli.py` 가 입력을 받아 위 `invoke` 를 호출합니다.
비밀번호 검사는 없습니다.

### HTTP

`src/api/main.py` 의 `chat()` 이 먼저 비밀번호(또는 쿠키)를 본 다음
같은 `invoke` 를 호출합니다. 돌아온 문서 조각에서 출처 JSON 을 만듭니다.

---

## 1. classify — 이 질문은 검색이 필요한가?

파일: `src/agent/nodes.py` → `classify_node`

LLM 에게 “세무 문서 검색이 필요하면 `rag`, 인사이면 `general`” 만 말하라고 합니다.

이월결손금은 법인세 문서 주제이므로 `query_type` 은 `rag` 가 됩니다.

`route_by_type` 이 `retrieve` 로 보냅니다.
“안녕하세요” 였다면 `general` 로 가서 검색 없이 끝입니다.

---

## 2. retrieve — 비슷한 글 10조각

파일: `src/agent/nodes.py` → `retrieve_node`

검색어는 `rewritten_query` 가 있으면 그것을, 없으면 원래 질문을 씁니다.
첫 시도이므로 원래 질문 그대로입니다.

`src/rag/vectorstore.py` 의 ChromaDB 에서 `similarity_search(query, k=10)` 을 합니다.
인덱스는 미리 `ingest.py` 가 `data/samples/` 를 넣어 둔 것입니다.

기대한 조각의 메타데이터 예:

- `source`: `2025_법인세_신고안내.md`
- `section_path`: `가. 이월결손금` (헤더가 더 있으면 `상위 > 하위` 형태)

이 10개가 `retrieved_docs` 에 들어갑니다.

---

## 3. generate — 그 조각만 보고 답하기

파일: `src/agent/nodes.py` → `generate_node`

프롬프트 요지:

- 참고 문서만 근거로 답하라
- 없으면 “제공된 문서에서 해당 내용을 찾을 수 없습니다.”
- 추측·외부 지식 금지
- 한국어로 간결하게

열 조각의 본문을 `---` 로 이어 `context` 로 넣습니다.

문서에 있으면 대략 이런 취지의 답이 나옵니다.

- 각 사업연도 개시일 전 **15년** 이내 결손금 공제
- 더 오래된 사업연도는 **10년** 또는 **5년** 제한이 있음

(연도와 숫자의 정확한 문장은 원문 청크를 따릅니다.)

---

## 4. verify — 답이 문서에 있는가?

파일: `src/agent/nodes.py` → `verify_node`

두 갈래입니다.

1. 답에 “찾을 수 없습니다” 가 있으면 바로 `grounded=False`
2. 아니면 LLM 이 참고 문서와 답을 보고 `grounded` / `ungrounded` 중 하나만 말함

이월결손금처럼 청크에 숫자가 있으면 보통 `grounded=True` 입니다.

`route_after_verify`:

- 근거 있음 → 종료
- 근거 없고 `rewrite_count` 가 2 미만 → `rewrite`
- 근거 없고 이미 2번 바꿈 → 종료 (더 이상 지어내지 않음)

---

## 5. (이 질문에서는 건너뜀) rewrite

구어체 예: `명세서 늦으면 얼마?`

1차 검색이 빗나가면 verify 가 근거 없음으로 보고,
`rewrite_node` 가 “지급명세서 지연 제출 가산세” 같은 검색어로 바꿉니다.
`rewrite_count` 가 1이 되고 다시 retrieve 로 갑니다.

상한은 2회입니다. `상속세 세율은?` 처럼 코퍼스 밖이면 두 번 찾고 `grounded=False` 로 끝납니다.

---

## 6. 사용자에게 보이는 결과

### CLI

```
답변> 이월결손금은 각 사업연도 개시일 전 15년 이내에 ...
     [type=rag grounded=True sources=10 rewrite=0]
     [1] 2025_법인세_신고안내.md — 가. 이월결손금
     ...
```

### API JSON

```json
{
  "answer": "이월결손금은 각 사업연도 개시일 전 15년 이내에 발생한 결손금에 대해 공제할 수 있습니다. ...",
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

`sources` 는 검색에 쓰인 조각입니다. 답 문장 전부가 첫 번째 조각에만 있다는 뜻은 아닙니다.

---

## 한눈에 보는 호출 순서

| 순서 | 함수 | 이 질문에서 |
|------|------|-------------|
| 1 | `classify_node` | `rag` |
| 2 | `route_by_type` | `retrieve` |
| 3 | `retrieve_node` | 법인세 청크 10개 |
| 4 | `generate_node` | 15년(및 예외 연한) 답 |
| 5 | `verify_node` | `grounded=True` |
| 6 | `route_after_verify` | `end` |

인사 질문이면 1 → `general_node` → 끝입니다.
검색이 실패하면 5 다음에 `rewrite_node` → 다시 3 으로 돌아갑니다.

코드를 열어 볼 때는 `src/agent/graph.py` 의 화살표를 먼저 보고,
상자 안 내용은 `src/agent/nodes.py` 를 보면 됩니다.
