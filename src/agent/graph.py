"""LangGraph StateGraph 조립"""
from langgraph.graph import END, StateGraph

from src.agent.nodes import (
    classify_node,
    general_node,
    generate_node,
    retrieve_node,
    rewrite_node,
    route_after_verify,
    route_by_type,
    verify_node,
)
from src.agent.state import AgentState


def build_graph():
    """전체 에이전트 워크플로우를 조립해 compiled graph 를 반환한다.

    Flow:
        classify --[general]--> general ----------------> END
        classify --[rag]------> retrieve -> generate -> verify
                                    ^                     |
                                    |                     v
                                    +--- rewrite <--[ungrounded & attempts left]
                                                      [grounded or max]--> END
    """
    workflow = StateGraph(AgentState)

    # Nodes
    workflow.add_node("classify", classify_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("rewrite", rewrite_node)
    workflow.add_node("general", general_node)

    # Entry point
    workflow.set_entry_point("classify")

    # classify -> (retrieve | general)
    workflow.add_conditional_edges(
        "classify",
        route_by_type,
        {"retrieve": "retrieve", "general": "general"},
    )

    # RAG path
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", "verify")

    # verify -> (end | rewrite)
    workflow.add_conditional_edges(
        "verify",
        route_after_verify,
        {"rewrite": "rewrite", "end": END},
    )

    # rewrite -> retrieve (loop)
    workflow.add_edge("rewrite", "retrieve")

    # general -> end
    workflow.add_edge("general", END)

    return workflow.compile()


# 앱 전역에서 재사용할 compiled graph 인스턴스
agent_graph = build_graph()
