# `src/api/` — HTTP 창구

브라우저, curl, 다른 프로그램이 이 서버에 질문을 보내는 층입니다.
세무 답변 로직은 없고, **비밀번호 검사 → 그래프 실행 → JSON 포장** 만 합니다.

---

## `schemas.py` — JSON 모양

Pydantic 모델입니다. FastAPI 가 이걸 보고 요청을 검사하고, `/docs` Swagger 화면을 만듭니다.

### `ChatRequest`

| 필드 | 타입 | 규칙 |
|------|------|------|
| `question` | 문자열 | 필수, 길이 1 이상 |
| `password` | 문자열 또는 없음 | `/unlock` 으로 쿠키가 있으면 생략 가능 |

빈 질문 `""` 은 422 로 거절됩니다.

### `UnlockRequest`

| 필드 | 뜻 |
|------|----|
| `password` | `/unlock` 전용. 기본값 `""` |

### `SourceItem`

검색에 쓰인 조각 하나입니다.

| 필드 | 뜻 |
|------|----|
| `source` | Markdown 파일 이름 |
| `section_path` | 목차 경로. 없으면 `null` |
| `snippet` | 본문 앞 160자 (`main.py` 에서 자름) |

### `ChatResponse`

| 필드 | 뜻 |
|------|----|
| `answer` | 답 본문 |
| `query_type` | `rag` / `general` / 예외 시 `unknown` |
| `grounded` | 문서 근거 여부 |
| `rewrite_count` | 검색어를 고친 횟수 |
| `sources` | `SourceItem` 목록 |

---

## `main.py` — FastAPI 앱

### 앱 생성

```python
app = FastAPI(
    title="Finance RAG Agent",
    description="LangGraph 기반 한국 금융/세무 Q&A Agentic RAG",
    version="0.1.0",
)
```

`uvicorn src.api.main:app` 의 `app` 이 이 객체입니다.
`/docs` 는 FastAPI 가 자동으로 붙입니다. 이 파일에 라우트를 적지 않았습니다.

모듈 로드 시 `from src.agent.graph import agent_graph` 때문에 그래프가 조립되고,
`nodes.py` 의 LLM 클라이언트도 만들어집니다. 그래서 서버 기동에 `.env` 의 API 키가 필요합니다.

---

## 비밀번호 관련 상수와 메모리

```python
_MAX_FAILS = 5
_BLOCK_SECONDS = 300
_fail_state: dict[str, tuple[int, float]] = {}
_SESSION_COOKIE = "paid_session"
```

- 같은 IP 에서 5번 틀리면 300초(5분) 동안 429
- `_fail_state` 는 **프로세스 메모리**입니다. 서버를 재시작하면 차단이 풀립니다.
- 세션은 서버 DB 가 아니라 **서명 쿠키**입니다. 서버를 여러 대 띄워도 쿠키만 유효하면 됩니다.

---

## 헬퍼 함수

초보자가 따라가기 쉬운 순서로 적습니다.

### `_session_secret()`

```python
return (settings.paid_model_password + "|" + settings.openai_api_key).encode()
```

쿠키 HMAC 키입니다. 비밀번호 **또는** API 키를 바꾸면 예전 쿠키는 검증에 실패합니다.

### `_issue_session(response)`

만료 시각(unix 초)을 만들고, 그 숫자를 HMAC-SHA256 으로 서명한 뒤
`{만료}.{서명}` 형태를 쿠키 `paid_session` 에 넣습니다.

- `httponly=True` — 브라우저 자바스크립트가 읽지 못함
- `samesite="lax"` — 다른 사이트에서 쿠키를 붙이기 어렵게
- `path="/"` — 이 서버의 모든 경로에서 전송
- `max_age` — 브라우저가 지우는 시간. 서버도 만료 시각을 검사함

### `_session_remaining(request)`

쿠키가 없거나, 형식이 아니거나, 서명이 틀리거나, 시간이 지났으면 `0`.
맞으면 남은 초. 비교는 `secrets.compare_digest` 로 해서 타이밍 차이를 줄입니다.

### `_password_matches(candidate)`

1. 서버에 비밀번호가 없으면 무조건 `False`
2. 입력과 정답을 각각 SHA-256 한 뒤 `compare_digest`  
   한글 비밀번호도 처리하고, 길이 차이로 힌트가 새지 않게 합니다.

### `_client_ip(request)`

`request.client.host`. 프록시 뒤에서는 실제 사용자 IP 가 아닐 수 있습니다. 데모 수준입니다.

### `_throttle_guard(ip)` / `_record_failure(ip)`

실패 횟수가 5 이상이고 차단 시각이 남아 있으면 429.
실패를 기록할 때는 횟수 +1 과 “지금부터 300초 뒤”를 저장합니다.

주의: 차단 시각은 **다섯 번째 실패 시각 + 300초** 입니다. 매 실패마다 차단 시각이 갱신됩니다.

### `_verify_paid_access(password, request, response)`

`/chat` 전용 검사 순서:

1. 비밀번호가 설정되지 않음 → **503** (질의를 아예 열지 않음)
2. 유효한 쿠키가 있음 → 통과
3. 이 IP 가 차단 중 → **429**
4. 본문 `password` 가 틀림 → 실패 기록 후 **401**
5. 맞음 → 실패 횟수 삭제, 쿠키 발급

프론트에서만 숨기는 방식은 우회되므로, 이 검사가 실제 보호입니다.

---

## 엔드포인트

### `GET /health`

비밀번호 없이 호출합니다. 과금 없음.

```json
{
  "status": "ok",
  "model": "gpt-4o-mini",
  "password_required": true,
  "password_configured": true,
  "unlock_remaining_sec": 0
}
```

`password_required` 는 항상 `true` 입니다. 설계가 “질의는 유료” 이기 때문입니다.
`password_configured` 가 `false` 이면 `/chat` 은 503 입니다.
비밀번호 문자열은 절대 넣지 않습니다.

### `POST /unlock`

본문 `{"password": "..."}`.
성공 시 쿠키를 심고 `unlocked`, `expires_in_sec` 를 반환합니다.
Swagger 에서 한 번 실행하면 같은 브라우저의 이후 `/chat` 에 쿠키가 붙습니다.

### `POST /lock`

쿠키를 지웁니다. 비밀번호를 검사하지 않습니다.

### `POST /chat`

1. `_verify_paid_access`
2. `agent_graph.invoke({"question": req.question, "rewrite_count": 0})`
3. `retrieved_docs` 를 `SourceItem` 목록으로 변환 (본문은 160자)
4. `ChatResponse` 반환

그래프가 칸을 안 채운 예외 상황에 대비해:

- `answer` 없으면 `""`
- `query_type` 없으면 `"unknown"`
- `grounded` 없으면 `False`
- `rewrite_count` 없으면 `0`

`general` 경로면 `retrieved_docs` 가 빈 리스트라 `sources` 도 `[]` 입니다.

---

## CLI 와 무엇이 다른가

| | `chat_cli.py` | `/chat` |
|--|---------------|---------|
| 입구 | 터미널 `input()` | JSON + 쿠키 |
| 비밀번호 | 없음 | 필수 (설정돼 있을 때) |
| 그래프 | 같은 `agent_graph` | 같음 |
| 출처 | 터미널에 파일명·섹션 전체 | JSON, 본문 160자 |

로컬에서 기능을 확인할 때는 CLI 가 더 단순합니다.
남에게 서버를 열 때만 API 보호가 의미를 갖습니다.
