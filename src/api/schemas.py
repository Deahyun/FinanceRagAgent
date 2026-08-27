"""FastAPI Pydantic 스키마"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="사용자 질문")
    password: str | None = Field(
        default=None,
        description="유료 API 호출용 비밀번호. /unlock 으로 한 번 인증했다면 생략 가능",
    )


class UnlockRequest(BaseModel):
    password: str = Field(default="", description="유료 API 호출용 비밀번호")


class SourceItem(BaseModel):
    source: str
    section_path: str | None = None
    snippet: str


class ChatResponse(BaseModel):
    answer: str
    query_type: str
    grounded: bool
    rewrite_count: int
    sources: list[SourceItem]
