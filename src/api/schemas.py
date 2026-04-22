"""FastAPI Pydantic 스키마"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="사용자 질문")


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
