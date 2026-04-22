"""기본 smoke 테스트.

실제 실행에는 OPENAI_API_KEY 와 인덱싱된 ChromaDB 가 필요하다.
CI 에서는 API 키가 없으면 자동으로 skip 된다.
"""
import os

import pytest


@pytest.fixture(scope="module")
def graph():
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    from src.agent.graph import build_graph

    return build_graph()


def test_general_greeting(graph):
    result = graph.invoke({"question": "안녕하세요", "rewrite_count": 0})
    assert result["query_type"] == "general"
    assert result["answer"]


def test_rag_question_classification(graph):
    result = graph.invoke(
        {"question": "부가가치세 일반 세율은 얼마인가요?", "rewrite_count": 0}
    )
    assert result["query_type"] == "rag"
    # RAG 경로를 탔다면 answer 가 존재해야 한다
    assert result["answer"]


def test_graph_compiles():
    """ChromaDB/OPENAI 호출 없이 순수하게 그래프 컴파일만 확인."""
    from src.agent.graph import build_graph

    g = build_graph()
    assert g is not None
