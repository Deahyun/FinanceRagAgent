"""LangGraph 노드 정의.

각 노드는 순수 함수로, AgentState 일부를 받아 업데이트할 dict 를 반환한다.
"""
import logging

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from src.agent.state import AgentState
from src.config import settings
from src.rag.vectorstore import get_vectorstore

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# LLM 인스턴스 (temperature=0 으로 결정론적 동작)
# ------------------------------------------------------------------
llm = ChatOpenAI(
    model=settings.openai_model,
    api_key=settings.openai_api_key,
    temperature=0,
)

MAX_REWRITES = 2


# ==================================================================
# Node 1. classify — 질문을 RAG 검색 대상/일반 대화로 분류
# ==================================================================
CLASSIFY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """당신은 사용자 질문을 분류하는 라우터입니다.
질문이 한국 금융/세무/회계 도메인의 문서 검색이 필요한 질문이면 'rag',
단순 인사/감사/잡담이면 'general' 로만 답하세요.
반드시 두 단어 중 하나만 출력하세요.""",
        ),
        ("human", "{question}"),
    ]
)


def classify_node(state: AgentState) -> dict:
    chain = CLASSIFY_PROMPT | llm | StrOutputParser()
    raw = chain.invoke({"question": state["question"]}).strip().lower()
    query_type = "rag" if "rag" in raw else "general"
    logger.info("[classify] question=%r -> %s", state["question"], query_type)
    return {"query_type": query_type}


# ==================================================================
# Node 2. retrieve — ChromaDB 에서 top-k 검색
# ==================================================================
def retrieve_node(state: AgentState) -> dict:
    query = state.get("rewritten_query") or state["question"]
    vs = get_vectorstore()
    # 큰 PDF(700+ 페이지, 2200+ 청크) 커버리지 위해 k=10.
    # MMR 은 한국어 세무 문서에서 다양성이 오히려 핵심 청크를 밀어내
    # 정답률이 낮아지는 경향이 있어 사용하지 않음.
    docs = vs.similarity_search(query, k=10)
    logger.info("[retrieve] query=%r -> %d docs", query, len(docs))
    return {"retrieved_docs": docs}


# ==================================================================
# Node 3. generate — 컨텍스트 기반 답변 생성
# ==================================================================
ANSWER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """당신은 한국 금융/세무 전문 AI 어시스턴트입니다.
반드시 아래 [참고 문서] 만을 근거로 답변하세요.
참고 문서에 답이 없으면 "제공된 문서에서 해당 내용을 찾을 수 없습니다." 라고만 답하세요.
추측이나 외부 지식으로 보충하지 마세요.
답변은 한국어로, 간결하고 정확하게 작성하세요.

[참고 문서]
{context}""",
        ),
        ("human", "{question}"),
    ]
)


def generate_node(state: AgentState) -> dict:
    if not state.get("retrieved_docs"):
        return {"answer": "제공된 문서에서 해당 내용을 찾을 수 없습니다."}

    context = "\n\n---\n\n".join(
        d.page_content for d in state["retrieved_docs"]
    )
    chain = ANSWER_PROMPT | llm | StrOutputParser()
    answer = chain.invoke(
        {"context": context, "question": state["question"]}
    )
    logger.info("[generate] answer_len=%d", len(answer))
    return {"answer": answer}


# ==================================================================
# Node 4. verify — 답변이 참고 문서에 근거하는지 검증
# ==================================================================
VERIFY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """당신은 답변이 참고 문서에 근거를 두는지 판정하는 검증자입니다.
답변의 주요 주장이 참고 문서 내용으로 직접 뒷받침되면 'grounded',
근거가 부족하거나 문서에 없는 주장이 포함되어 있으면 'ungrounded' 라고만 답하세요.
반드시 두 단어 중 하나만 출력하세요.""",
        ),
        (
            "human",
            """[참고 문서]
{context}

[답변]
{answer}""",
        ),
    ]
)


def verify_node(state: AgentState) -> dict:
    if not state.get("retrieved_docs"):
        return {"grounded": False}

    # "찾을 수 없습니다" 응답은 검증 단계에서 ungrounded 로 처리해
    # rewrite 루프가 한 번은 돌게 한다. MAX_REWRITES 가드로 무한 루프 차단.
    # (rewrite 소진 후에도 여전히 못 찾으면 그대로 종료 — route_after_verify 참조)
    if "찾을 수 없습니다" in state.get("answer", ""):
        return {"grounded": False}

    context = "\n\n---\n\n".join(
        d.page_content for d in state["retrieved_docs"]
    )
    chain = VERIFY_PROMPT | llm | StrOutputParser()
    verdict = chain.invoke(
        {"context": context, "answer": state["answer"]}
    ).strip().lower()
    grounded = verdict == "grounded"
    logger.info("[verify] verdict=%r grounded=%s", verdict, grounded)
    return {"grounded": grounded}


# ==================================================================
# Node 5. rewrite — 근거 부족 시 검색어 재작성
# ==================================================================
REWRITE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """사용자의 원래 질문으로 검색한 결과의 근거가 부족합니다.
같은 의도를 유지하되 동의어/상위 개념/하위 개념을 활용해
검색이 더 잘 되도록 쿼리를 재작성하세요.
재작성된 쿼리 한 줄만 출력하세요.""",
        ),
        ("human", "원래 질문: {question}"),
    ]
)


def rewrite_node(state: AgentState) -> dict:
    chain = REWRITE_PROMPT | llm | StrOutputParser()
    new_query = chain.invoke({"question": state["question"]}).strip()
    count = state.get("rewrite_count", 0) + 1
    logger.info("[rewrite] new_query=%r (attempt %d)", new_query, count)
    return {"rewritten_query": new_query, "rewrite_count": count}


# ==================================================================
# Node 6. general — RAG 불필요한 일반 대화
# ==================================================================
GENERAL_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "당신은 한국 금융/세무 전문 챗봇입니다. "
            "인사말이나 일반 대화에 한두 문장으로 간결히 응답하세요.",
        ),
        ("human", "{question}"),
    ]
)


def general_node(state: AgentState) -> dict:
    chain = GENERAL_PROMPT | llm | StrOutputParser()
    answer = chain.invoke({"question": state["question"]})
    return {"answer": answer, "grounded": True, "retrieved_docs": []}


# ==================================================================
# Conditional edges
# ==================================================================
def route_by_type(state: AgentState) -> str:
    return "retrieve" if state["query_type"] == "rag" else "general"


def route_after_verify(state: AgentState) -> str:
    """근거 있음 -> 종료, 없음 -> (재시도 가능하면) 재작성 루프"""
    if state.get("grounded"):
        return "end"
    if state.get("rewrite_count", 0) >= MAX_REWRITES:
        return "end"
    return "rewrite"
