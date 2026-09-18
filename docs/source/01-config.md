# `src/config.py` — 설정

다른 파일이 공통으로 읽는 **한 곳의 설정**입니다.
API 키, 모델 이름, ChromaDB 경로, `/chat` 비밀번호가 여기 모입니다.

## 이 파일이 하는 일

1. `.env` 와 `.env_pwd` 를 읽는다.
2. 환경 변수 이름을 파이썬 필드에 맞춘다 (`OPENAI_API_KEY` → `openai_api_key`).
3. 비밀번호 앞뒤 공백을 자른다.
4. 전역 객체 `settings` 를 만들어 둔다.

## 클래스 `Settings`

`pydantic-settings` 의 `BaseSettings` 를 씁니다.
필드에 타입을 적으면, 문자열이 들어와도 숫자·참거짓으로 바꿔 주고, 필수 값이 없으면 에러를 냅니다.

| 필드 | 환경 변수 | 기본값 | 뜻 |
|------|-----------|--------|----|
| `openai_api_key` | `OPENAI_API_KEY` | **없음 (필수)** | OpenAI 열쇠 |
| `openai_model` | `OPENAI_MODEL` | `gpt-4o-mini` | 분류·답변·검증 LLM |
| `embedding_model` | `EMBEDDING_MODEL` | `text-embedding-3-small` | 글을 숫자로 바꾸는 모델 |
| `chroma_persist_dir` | `CHROMA_PERSIST_DIR` | `./chroma_db` | 검색 DB 폴더 |
| `collection_name` | `COLLECTION_NAME` | `finance_docs` | Chroma 컬렉션 이름 |
| `log_level` | `LOG_LEVEL` | `INFO` | 로그 수준 |
| `paid_model_password` | `PAID_MODEL_PASSWORD` | `""` (빈 문자열) | `/chat` 비밀번호 |
| `paid_session_minutes` | `PAID_SESSION_MINUTES` | `60` | 인증 쿠키 유효 시간(분) |

`openai_api_key` 만 기본값이 없습니다. `.env` 에 키가 없으면 `Settings()` 생성 시 예외가 납니다.

## `model_config`

```python
model_config = SettingsConfigDict(
    env_file=(".env", ".env_pwd"),
    env_file_encoding="utf-8",
    extra="ignore",
)
```

- 두 파일을 순서대로 읽습니다. 같은 키가 있으면 **뒤 파일**이 이깁니다.
- 비밀번호를 `.env` 가 아니라 `.env_pwd` 에 둔 이유는 Git 에 올리지 않고, API 키와 권한을 분리하기 위해서입니다.
- `extra="ignore"` 는 파일에 모르는 키가 있어도 무시합니다. 주석용 키를 넣어도 프로그램이 죽지 않습니다.
- Docker 안에서는 `docker-compose.yml` 의 `environment` / `env_file` 이 운영체제 환경 변수로 들어갑니다. pydantic-settings 는 **환경 변수가 파일보다 우선**합니다.

## `_strip_password`

```python
@field_validator("paid_model_password")
@classmethod
def _strip_password(cls, v: str) -> str:
    return v.strip()
```

`.env_pwd` 를 편집할 때 `PAID_MODEL_PASSWORD= abc` 처럼 실수로 공백을 넣기 쉽습니다.
앞뒤 공백을 제거합니다. **따옴표는 제거하지 않습니다.** `"abc"` 라고 쓰면 따옴표까지 비밀번호의 일부가 됩니다.

## `password_configured`

```python
@property
def password_configured(self) -> bool:
    return bool(self.paid_model_password)
```

빈 문자열은 `False` 입니다. FastAPI 는 이 값이 거짓이면 `/chat` 을 503 으로 잠급니다.
비밀번호를 안 정한 채 서버를 인터넷에 열어도, 질의는 나가지 않습니다.

## 파일 맨 아래 `settings = Settings()`

모듈을 import 하는 순간 설정이 로드됩니다.

```python
from src.config import settings
```

그래서 `src.agent.nodes` 나 `src.api.main` 을 불러오기만 해도 `.env` 의 `OPENAI_API_KEY` 가 필요합니다.
테스트에서 키가 없으면 그래프 컴파일만 따로 두고, LLM 테스트는 skip 하는 이유이기도 합니다.

## 다른 파일이 이 값을 쓰는 곳

| 값 | 쓰는 곳 |
|----|---------|
| `openai_api_key`, `openai_model` | `nodes.py` 의 `ChatOpenAI`, `api/main.py` 의 `/health` |
| `embedding_model`, `openai_api_key` | `rag/vectorstore.py` |
| `chroma_persist_dir`, `collection_name` | `vectorstore.py`, `ingest.py` 로그 |
| `log_level` | `main.py`, `ingest.py`, `chat_cli.py` |
| `paid_model_password`, `paid_session_minutes` | `api/main.py` 비밀번호·쿠키 |
