"""애플리케이션 설정 (pydantic-settings)"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    chroma_persist_dir: str = "./chroma_db"
    collection_name: str = "finance_docs"
    log_level: str = "INFO"

    # --- 공개 배포용 접근 제어 ---------------------------------------------
    # /chat 은 호출 한 번마다 임베딩(검색) + LLM(생성) 으로 실제 요금이 청구됩니다.
    # 데모 서버가 LAN/인터넷에 열려 있으면 누구나 크레딧을 소진시킬 수 있으므로
    # 비밀번호를 입력해야만 질의할 수 있게 막습니다. (/health, /docs 는 무료라 공개)
    #   비밀번호 : .env_pwd 의 PAID_MODEL_PASSWORD
    # 값이 비어 있으면 /chat 은 아예 503 으로 잠깁니다 = fail-closed.
    paid_model_password: str = ""
    # 비밀번호를 한 번 맞히면 이 시간(분) 동안은 쿠키로 재입력 없이 사용.
    paid_session_minutes: int = 60

    model_config = SettingsConfigDict(
        # .env_pwd 를 뒤에 두어 비밀번호를 별도 파일로 분리(.gitignore 대상).
        # 컨테이너에선 compose 의 env_file 이 주입하지만, 로컬 실행 편의를 위해 함께 읽습니다.
        env_file=(".env", ".env_pwd"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("paid_model_password")
    @classmethod
    def _strip_password(cls, v: str) -> str:
        # .env 편집 중 흔한 앞뒤 공백을 제거 (따옴표는 제거하지 않음 — 값의 일부로 간주)
        return v.strip()

    @property
    def password_configured(self) -> bool:
        """서버에 /chat 보호 비밀번호가 설정되어 있는지."""
        return bool(self.paid_model_password)


settings = Settings()
