# 설치하고 질문해 보기

Windows PowerShell 기준으로 적었습니다. macOS / Linux 는 가상환경 활성화 명령만 다릅니다.

## 준비물

1. **Python 3.10 이상** (`python --version` 으로 확인)
2. **OpenAI API 키** — [OpenAI 플랫폼](https://platform.openai.com/) 에서 발급
3. (선택) **Docker Desktop** — 컨테이너로 띄울 때만

인터넷이 되고, 키가 유효해야 인덱싱과 답변이 됩니다.
검색·답변 모두 OpenAI 를 호출하므로 **소액 요금**이 발생합니다.

## 1. 로컬에서 실행

저장소 루트(`FinanceRagAgent`)에서 합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
```

`.env` 를 열어 `OPENAI_API_KEY=` 뒤에 본인 키를 넣습니다.

`data/samples/` 에 Markdown 3개가 이미 있습니다. PDF 변환은 건너뛰어도 됩니다.

```powershell
# 검색 DB 만들기 (최초 1회, 또는 청크 설정을 바꾼 뒤)
python -m src.scripts.ingest --reset

# 터미널에서 대화
python -m src.scripts.chat_cli
```

질문 칸에 한글을 넣고 Enter 를 칩니다. 끝내려면 `exit` 를 입력합니다.

웹으로 쓰려면:

```powershell
copy .env_pwd.example .env_pwd
# .env_pwd 의 PAID_MODEL_PASSWORD 를 원하는 값으로 바꿉니다.

uvicorn src.api.main:app --reload --port 8000
```

브라우저에서 http://localhost:8000/docs 를 엽니다.

1. `POST /unlock` → `Try it out` → `{"password": "설정한비밀번호"}` → Execute
2. `POST /chat` → `{"question": "원천징수의무자란 무엇인가요?"}` → Execute

비밀번호를 비워 두면 `/chat` 은 503 으로 거절합니다.

## 2. Docker 로 실행

`.env` 에 키가 있어야 합니다.

```powershell
echo OPENAI_API_KEY=sk-여기에키 > .env
copy .env_pwd.example .env_pwd
# .env_pwd 의 비밀번호를 바꿉니다.

docker compose up --build -d

# 컨테이너 안에서 인덱싱 (최초 1회)
docker compose exec agent python -m src.scripts.ingest --reset

# 살아 있는지
curl http://localhost:8000/health
```

질문 예:

```powershell
curl -X POST http://localhost:8000/chat `
  -H "Content-Type: application/json" `
  -d "{\"question\": \"이월결손금은 몇 년까지 공제할 수 있어?\", \"password\": \"설정한비밀번호\"}"
```

쿠키를 저장하면 다음 호출부터 비밀번호를 생략할 수 있습니다.

```powershell
curl -c jar.txt -X POST http://localhost:8000/unlock `
  -H "Content-Type: application/json" `
  -d "{\"password\": \"설정한비밀번호\"}"

curl -b jar.txt -X POST http://localhost:8000/chat `
  -H "Content-Type: application/json" `
  -d "{\"question\": \"부가가치세 납부기한 연장이 가능한 경우는?\"}"
```

## 3. PDF 를 다시 변환하고 싶을 때

원본 PDF 는 Git 에 없습니다. [국세청](https://www.nts.go.kr) 자료실에서
해당 연도 『법인세 신고안내』, 『부가가치세 신고안내 매뉴얼』,
『원천징수의무자를 위한 연말정산 신고안내』 를 받아 `data/raw/` 에 넣습니다.

```powershell
python -m src.scripts.pdf_to_md --overwrite
python -m src.scripts.ingest --reset
```

변환은 국세청 PDF 의 깨진 원문자를 보정합니다. 자세한 이유는 [files.md](files.md) 의 `pdf_to_md.py` 를 보세요.

## 처음 던져 볼 질문

문서에 있고, 재검색 없이 근거가 잡히기 쉬운 질문입니다.

- 간이과세자의 업종별 부가가치율을 알려주세요
- 이월결손금 공제 한도는 어떻게 되나요?
- 원천징수의무자란 무엇인가요?
- 사업자 미등록 가산세는 몇 퍼센트인가요?
- 법인세율은 과세표준 구간별로 어떻게 되나요?

에이전트의 **재검색** 을 보고 싶다면:

- `명세서 늦으면 얼마?` — 구어체라 한 번 검색어를 고친 뒤 맞는 경우가 많습니다.

문서 밖 주제를 보고 싶다면:

- `상속세 세율은 어떻게 되나요?` — 지어내지 않고 거절해야 정상입니다.

약점에 가까운 질문:

- `부가가치세 세율은 얼마인가요?` — 매뉴얼에 “세율은 10%” 문장이 없어 거절되는 경우가 많습니다.

## 자주 막히는 곳

| 증상 | 확인 |
|------|------|
| `OPENAI_API_KEY` 오류 | `.env` 파일 이름과 키 값. 저장소 루트에 있어야 함 |
| 검색 결과가 비었거나 동문서답 | `ingest --reset` 을 했는가. `chroma_db/` 폴더가 생겼는가 |
| `/chat` 이 503 | `.env_pwd` 의 `PAID_MODEL_PASSWORD` 가 비어 있음 |
| `/chat` 이 401 | 비밀번호가 다름. Docker 라면 컨테이너 재생성이 필요할 수 있음 |
| `/chat` 이 429 | 같은 IP 에서 5번 틀림. 5분 기다리거나 컨테이너를 재생성 |
| Docker 에서 비밀번호를 바꿨는데 옛 값 | `docker compose up -d --force-recreate agent` |
| PDF 변환 오류 | `data/raw/` 에 PDF 가 있는지, 파일 이름 확장자가 `.pdf` 인지 |

비밀번호가 컨테이너에 들어갔는지는 다음으로 확인합니다.

```powershell
docker compose exec agent printenv PAID_MODEL_PASSWORD
```

## 테스트

```powershell
pytest
```

API 키가 없으면 실제 LLM 테스트는 건너뛰고, 그래프 조립만 검사합니다.

## 다음 읽을 글

한 질문이 코드의 어느 함수를 타는지 보고 싶다면 [example-question.md](example-question.md) 입니다.
