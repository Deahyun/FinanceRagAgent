"""FastAPI 서버"""
import logging

from fastapi import FastAPI

from src.agent.graph import agent_graph
from src.api.schemas import ChatRequest, ChatResponse, SourceItem
from src.config import settings

logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="Finance RAG Agent",
    description="LangGraph 기반 한국 금융/세무 Q&A Agentic RAG",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.openai_model}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    result = agent_graph.invoke(
        {"question": req.question, "rewrite_count": 0}
    )

    sources = [
        SourceItem(
            source=d.metadata.get("source", "unknown"),
            section_path=d.metadata.get("section_path"),
            snippet=d.page_content[:160],
        )
        for d in result.get("retrieved_docs", [])
    ]

    return ChatResponse(
        answer=result.get("answer", ""),
        query_type=result.get("query_type", "unknown"),
        grounded=bool(result.get("grounded", False)),
        rewrite_count=int(result.get("rewrite_count", 0)),
        sources=sources,
    )
