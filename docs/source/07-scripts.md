# `src/scripts/` — 사람이 실행하는 명령

세 파일 모두 `python -m src.scripts.이름` 으로 실행합니다.
`-m` 은 패키지 경로로 모듈을 실행하라는 뜻이라, 프로젝트 루트에서 실행해야 `src` 를 찾습니다.

---

## `pdf_to_md.py` — PDF 를 Markdown 으로

**입력:** `data/raw/*.pdf`  
**출력:** `data/samples/<같은이름>.md`  
**다른 src 모듈 의존:** 거의 없음 (PyMuPDF 만)

저장소에는 이미 변환된 Markdown 이 있습니다. PDF 가 없거나 변환을 다시 할 때만 필요합니다.

### 왜 그냥 복사하면 안 되나

국세청 PDF 는 커스텀 폰트로 **원문자(⑳㉑…㉛)** 를 넣습니다.
일반 추출 도구는 그 글자를 `�` 로 바꾸거나, `쇭쇶` 같은 한글 두 글자로 남깁니다.
표지 페이지는 장식용 글자가 많아 본문 검색에 잡음이 됩니다.

### 페이지 하나 처리 순서 (`convert`)

1. `page.get_text("text")` 로 원시 텍스트
2. `_is_cover_like` — 한글·ASCII·원문자가 아닌 글자 비율이 **30% 초과**면 표지로 보고 **건너뜀**
3. `pymupdf4llm.to_markdown` 으로 해당 페이지만 Markdown 추출
4. 결과에 `�`(U+FFFD) 가 있으면 Markdown 을 버리고 **원시 텍스트**로 대체
5. `_apply_circle_subs` 로 확인된 한글 쌍을 원문자로 치환

### `CIRCLE_SUBS` / `_apply_circle_subs`

예: `"쇭쇶"` → `"㉑"`.  
두 글자 사이에 공백·줄바꿈이 있어도 정규식이 맞춥니다.
표에 없는 쌍은 그대로 둡니다. 추측으로 잘못된 글자를 넣지 않기 위해서입니다.

### `_strip_noise`

pymupdf4llm 이 넣는 그림 자리 표시(`**==> ... <==**`) 줄을 지우고, 빈 줄이 3개 이상이면 2개로 줄입니다.
임베딩에 쓸데없는 토큰이 들어가지 않게 하기 위함입니다.

### `main`

```text
python -m src.scripts.pdf_to_md
python -m src.scripts.pdf_to_md --overwrite
python -m src.scripts.pdf_to_md --raw data/raw --out data/samples
```

- `--overwrite` 없으면 이미 `.md` 가 있는 PDF 는 건너뜀
- `data/raw` 가 없으면 종료 코드 1
- PDF 가 0개면 경고만 하고 종료 코드 0

각 파일마다 페이지 수, 표지 스킵, raw 폴백, 걸린 시간, 결과 용량을 로그로 남깁니다.

변환만 하고 **인덱싱은 하지 않습니다.** 이어서 `ingest --reset` 을 실행해야 검색에 반영됩니다.

---

## `ingest.py` — Markdown 을 ChromaDB 에 넣기

챗봇이 찾기 전에 **반드시 한 번** 실행합니다.

```text
python -m src.scripts.ingest          # 기존 벡터에 추가
python -m src.scripts.ingest --reset  # 비우고 처음부터
```

### `main` 세 단계

1. `load_documents("data/samples")` — 파일 몇 개인지 출력
2. `split_documents(docs)` — 청크 수, 평균 길이, `section_path` 가 붙은 비율 출력
3. `get_vectorstore()` 후  
   - `--reset` 이면 컬렉션의 모든 id 를 조회해 `delete`  
   - `vs.add_documents(chunks)` — 여기서 임베딩 API 가 청크 수만큼 호출됨

### `--reset` 구현이 조금 복잡한 이유

ChromaDB 1.0 이상은 “조건 없이 전부 삭제”를 거절합니다.
그래서 `get(include=[])` 로 id 만 가져온 뒤 `delete(ids=...)` 합니다.

청크 크기나 문서가 바뀌었는데 reset 없이 추가하면 **옛 조각이 남아** 검색이 섞입니다.
처음 설치와 문서 교체 때는 `--reset` 을 쓰는 것이 안전합니다.

이 스크립트는 HTTP 비밀번호를 보지 않습니다. 로컬/컨테이너 안에서만 실행하는 관리 명령입니다.

---

## `chat_cli.py` — 터미널 대화

서버를 띄우지 않고 그래프를 직접 부릅니다.

```text
python -m src.scripts.chat_cli
```

### 루프

1. 시작 안내 (`exit` / `quit` 로 종료)
2. `input("질문> ")`  
   - 빈 줄은 무시  
   - `Ctrl+C` / `Ctrl+Z`(EOF) 도 종료
3. `agent_graph.invoke({"question": q, "rewrite_count": 0})`
4. 답, 그다음 한 줄 메타 정보, 그다음 출처 목록

메타 정보 예:

```
[type=rag grounded=True sources=10 rewrite=0]
```

출처 한 줄:

```
[1] 2025_법인세_신고안내.md — 가. 이월결손금
```

`section_path` 가 없으면 파일 이름만 찍습니다.

비밀번호·쿠키·JSON 이 없어 동작 확인에 가장 직접적입니다.
OpenAI 키와 인덱스는 필요합니다.

---

## 세 스크립트를 언제 쓰나

```
(선택) PDF 추가     python -m src.scripts.pdf_to_md --overwrite
       ↓
(필수) 인덱싱       python -m src.scripts.ingest --reset
       ↓
       질문         python -m src.scripts.chat_cli
                    또는 uvicorn src.api.main:app
```
