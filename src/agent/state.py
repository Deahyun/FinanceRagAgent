"""LangGraph 에이전트 상태 정의"""
from typing import Literal, TypedDict

from langchain_core.documents import Document


class AgentState(TypedDict, total=False):
    """에이전트 워크플로우 전체에서 공유되는 상태.

    각 노드는 이 상태의 일부를 읽고/수정하며,
    LangGraph가 자동으로 상태를 병합한다.
    """

    question: str
    query_type: Literal["rag", "general"]
    rewritten_query: str
    retrieved_docs: list[Document]
    answer: str
    grounded: bool
    rewrite_count: int
