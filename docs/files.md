# 파일별 설명

이 문서는 저장소 **전체 파일의 역할 요약**입니다.
`src/` 와 `tests/` 를 함수 단위로 읽고 싶다면 [source/README.md](source/README.md) 로 가세요.

빈 `__init__.py` 는 “이 디렉터리는 파이썬 패키지” 라는 표시입니다. 아래에 따로 적지 않은 `__init__.py` 는 내용이 거의 없습니다.

---

## 저장소 루트

### `README.md`

프로젝트 소개, 아키텍처 그림, 빠른 시작, 샘플 질문입니다. 개발자가 처음 열어보는 파일입니다. 초보자용 긴 설명은 이 `docs/` 폴더에 있습니다.

### `CLAUDE.md`

AI 코딩 도구가 이 저장소를 빠르게 파악하도록 정리한 내부 메모입니다. 사람용 입문서는 아닙니다.

### `LICENSE`

MIT 라이선스입니다.

### `.gitignore`

깃에 올리지 않을 목록입니다. `.env`, `.env_pwd`, `chroma_db/`, 가상환경, PDF 원본 등이 들어 있습니다.

### `.env.example`

설정 템플릿입니다. 복사해서 `.env` 를 만듭니다.

| 키 | 기본값 | 뜻 |
|----|--------|----|
| `OPENAI_API_KEY` | (직접 넣음) | OpenAI 열쇠. 없으면 인덱싱·챗봇이 동작하지 않음 |
| `OPENAI_MODEL` | `gpt-4o-mini` | 답변·분류·검증에 쓰는 모델 |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | 글을 숫자로 바꾸는 모델 |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | 검색 DB 가 저장되는 폴더 |
| `COLLECTION_NAME` | `finance_docs` | ChromaDB 컬렉션 이름 |
| `LOG_LEVEL` | `INFO` | 로그 상세 정도 |

### `.env`

이 컴퓨터에서만 쓰는 실제 설정입니다. 깃에 올라가지 않습니다.

### `.env_pwd.example` / `.env_pwd`

`/chat` 을 열 때 쓰는 비밀번호입니다. 견본을 복사해 `.env_pwd` 를 만듭니다.

| 키 | 기본값 | 뜻 |
|----|--------|----|
| `PAID_MODEL_PASSWORD` | (비우면 `/chat` 잠김) | 질의 비밀번호 |
| `PAID_SESSION_MINUTES` | `60` | 한 번 인증한 뒤 재입력 없이 쓰는 시간(분) |

견본 파일을 고쳐도 효과가 없습니다. 실제로 읽히는 파일은 `.env_pwd` 입니다.

### `requirements.txt`

`pip install -r requirements.txt` 로 설치하는 파이썬 패키지 목록입니다.
LangChain, LangGraph, ChromaDB, FastAPI, PyMuPDF 계열, pytest 등이 있습니다.

### `Dockerfile`

프로그램을 컨테이너로 묶는 레시피입니다. Python 3.11 이미지에 의존성과 소스를 넣고 `uvicorn src.api.main:app` 으로 시작합니다.

### `docker-compose.yml`

한 번에 띄우는 서비스 정의입니다. 서비스 이름은 `agent`, 포트는 `8000` 입니다.

- `.env` 의 `OPENAI_API_KEY` 를 컨테이너에 넣습니다.
- `.env_pwd` 가 있으면 비밀번호도 넣습니다. 없으면 `/chat` 은 잠깁니다.
- `chroma_db/` 와 `data/` 를 볼륨으로 붙여, 컨테이너를 지워도 인덱스와 문서가 남습니다.

Docker 에서 비밀번호를 바꾼 뒤에는 `restart` 가 아니라 **컨테이너 재생성**이 필요합니다.

```bash
docker compose up -d --force-recreate agent
```

---

## `src/` — 애플리케이션

함수·프롬프트·분기 조건까지 적은 설명은 [source/](source/README.md) 에 있습니다.

### `src/config.py`

`.env` 와 `.env_pwd` 를 읽어 `settings` 객체로 만듭니다.
비밀번호 앞뒤 공백은 잘라 내고, 값이 있는지만 `password_configured` 로 알려 줍니다.

### `src/agent/state.py`

그래프 전체가 공유하는 상태 모양입니다. `question`, `query_type`, `retrieved_docs` 등이 정의되어 있습니다.

### `src/agent/nodes.py`

여섯 개 노드와 두 개 분기 함수가 있습니다.

- `classify_node` — `rag` / `general`
- `retrieve_node` — ChromaDB `similarity_search(k=10)`
- `generate_node` — 참고 문서만 보고 답변
- `verify_node` — grounded 판정. “찾을 수 없습니다” 는 근거 없음
- `rewrite_node` — 검색어 재작성, `rewrite_count` + 1
- `general_node` — 짧은 일반 대화
- `route_by_type` — classify 다음 목적지
- `route_after_verify` — 끝낼지 rewrite 할지

LLM 은 `temperature=0` 이라 같은 입력에 답이 비교적 일정합니다.

### `src/agent/graph.py`

위 노드를 `StateGraph` 로 연결하고 `compile()` 합니다.
앱 전역에서 쓰는 인스턴스 이름은 `agent_graph` 입니다.

### `src/rag/loader.py`

`data/samples/**/*.md` 를 읽고 두 단계로 자릅니다.

1. Markdown 헤더(`#` ~ `####`) 단위
2. 1000자 조각, 앞뒤 150자 겹침

자른 조각에 `source`(파일명) 와 `section_path`(헤더를 `>` 로 이은 경로) 를 붙입니다.

### `src/rag/vectorstore.py`

OpenAI 임베딩과 ChromaDB 컬렉션을 만드는 얇은 래퍼입니다.
`get_vectorstore()` 를 ingest 와 retrieve 가 같이 씁니다.

### `src/api/schemas.py`

HTTP 입출력 모양입니다.

- 요청: `question`, 선택 `password`
- 응답: `answer`, `query_type`, `grounded`, `rewrite_count`, `sources`

`sources` 한 건에는 파일명, 섹션 경로, 본문 앞 160자가 들어갑니다.

### `src/api/main.py`

FastAPI 앱입니다. `/health`, `/unlock`, `/lock`, `/chat` 이 있습니다.
비밀번호 비교는 시간 공격에 덜 노출되도록 해시 후 비교합니다.
쿠키는 HttpOnly + HMAC 서명입니다.

---

## `src/scripts/` — 사람이 실행하는 명령

### `src/scripts/pdf_to_md.py`

`data/raw/*.pdf` → `data/samples/*.md`

국세청 PDF 는 커스텀 폰트 때문에 일반 추출이면 원문자(㉑ 등)가 깨집니다.
표지처럼 이상한 글자 비율이 높은 페이지는 건너뛰고,
깨진 페이지는 원시 텍스트로 바꾸며, 확인된 한글 시퀀스를 원문자로 고칩니다.

저장소에 이미 Markdown 이 있으면 **이 스크립트 없이** 인덱싱할 수 있습니다.

### `src/scripts/ingest.py`

Markdown 을 읽어 청크로 자른 뒤 ChromaDB 에 넣습니다.

```bash
python -m src.scripts.ingest          # 기존에 이어서 추가
python -m src.scripts.ingest --reset  # 비우고 처음부터 (청크 크기 바꿀 때 필수)
```

### `src/scripts/chat_cli.py`

터미널에서 질문하는 화면입니다. 답을 출력한 뒤
`type`, `grounded`, 출처 개수, 재작성 횟수, 각 출처의 섹션 경로를 보여 줍니다.
`exit` / `quit` / `q` 로 끝냅니다.

---

## `data/`

### `data/samples/`

인덱싱에 쓰는 Markdown 3개입니다. 챗봇의 지식 범위가 이 폴더입니다.

### `data/raw/`

PDF 원본을 두는 자리입니다. 기본 저장소에는 파일이 없을 수 있습니다.

### `data/legacy_samples/`

초기에 쓰던 짧은 데모 문서입니다. `ingest` 는 여기를 읽지 않습니다.

---

## `tests/`

### `tests/test_agent.py`

세 가지를 봅니다.

1. 그래프가 컴파일되는지 (API 키 없어도 됨)
2. “안녕하세요” 가 `general` 로 가는지
3. 세무 질문이 `rag` 로 분류되고 답이 있는지

2·3번은 `OPENAI_API_KEY` 가 없으면 건너뜁니다. 인덱스가 비어 있으면 RAG 테스트는 실패할 수 있습니다.

---

## 실행 중 생기는 폴더

### `chroma_db/`

인덱싱이 만든 ChromaDB 파일입니다. Git 에 올리지 않습니다.
지우고 다시 `ingest --reset` 하면 검색 DB 를 처음부터 만들 수 있습니다.
