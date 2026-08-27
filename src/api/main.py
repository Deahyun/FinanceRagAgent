"""FastAPI 서버"""
import hashlib
import hmac
import logging
import secrets
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response

from src.agent.graph import agent_graph
from src.api.schemas import ChatRequest, ChatResponse, SourceItem, UnlockRequest
from src.config import settings

logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="Finance RAG Agent",
    description="LangGraph 기반 한국 금융/세무 Q&A Agentic RAG",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# 유료 API 접근 제어 (공개 배포 대비)
#
# /chat 은 호출 한 번마다 임베딩(검색) + LLM(생성) 으로 실제 요금이 청구됩니다.
# 데모 서버가 열려 있으면 누구나 크레딧을 소진시킬 수 있으므로 비밀번호로 잠급니다.
# 검증은 반드시 서버에서 수행합니다 — 프론트엔드 검사는 우회 가능하므로 보호 수단이 아닙니다.
# 비밀번호는 .env_pwd 의 PAID_MODEL_PASSWORD 로 주입됩니다.
# ---------------------------------------------------------------------------
_MAX_FAILS = 5           # 이 횟수만큼 틀리면
_BLOCK_SECONDS = 300     # 5분간 차단 (무차별 대입 완화)
_fail_state: dict[str, tuple[int, float]] = {}

# 한 번 인증하면 paid_session_minutes 동안 재입력 없이 사용 (서명 쿠키, 서버 상태 없음)
_SESSION_COOKIE = "paid_session"


def _session_secret() -> bytes:
    """쿠키 서명 키. 비밀번호가 바뀌면 기존 쿠키는 자동으로 무효가 됩니다."""
    return (settings.paid_model_password + "|" + settings.openai_api_key).encode()


def _issue_session(response: Response) -> None:
    exp = int(time.time()) + settings.paid_session_minutes * 60
    sig = hmac.new(_session_secret(), str(exp).encode(), hashlib.sha256).hexdigest()
    response.set_cookie(
        _SESSION_COOKIE,
        f"{exp}.{sig}",
        max_age=settings.paid_session_minutes * 60,
        httponly=True,      # JS 로 읽을 수 없음 (XSS 로 탈취 불가)
        samesite="lax",
        path="/",
    )


def _session_remaining(request: Request) -> int:
    """유효한 인증 쿠키가 있으면 남은 초, 없으면 0."""
    token = request.cookies.get(_SESSION_COOKIE, "")
    exp_str, _, sig = token.partition(".")
    if not sig or not exp_str.isdigit():
        return 0
    expected = hmac.new(_session_secret(), exp_str.encode(), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(sig, expected):
        return 0
    return max(0, int(exp_str) - int(time.time()))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _throttle_guard(ip: str) -> None:
    fails, blocked_until = _fail_state.get(ip, (0, 0.0))
    if fails >= _MAX_FAILS and time.time() < blocked_until:
        wait = int(blocked_until - time.time())
        raise HTTPException(
            status_code=429,
            detail=f"비밀번호를 여러 번 틀렸습니다. {wait}초 후 다시 시도하세요.",
        )


def _record_failure(ip: str) -> None:
    fails, _ = _fail_state.get(ip, (0, 0.0))
    _fail_state[ip] = (fails + 1, time.time() + _BLOCK_SECONDS)


def _verify_paid_access(
    password: str | None,
    request: Request,
    response: Response | None = None,
) -> None:
    """/chat 호출 전 비밀번호(또는 유효한 인증 쿠키)를 검증.

    비밀번호가 맞으면 인증 쿠키를 발급해 이후 paid_session_minutes 분간 재입력이 필요 없습니다.
    """
    if not settings.password_configured:
        raise HTTPException(
            status_code=503,
            detail="질의는 유료 API 를 사용하며, 서버에 비밀번호가 설정되지 않아 "
            "비활성화되어 있습니다. (.env_pwd 의 PAID_MODEL_PASSWORD)",
        )

    if _session_remaining(request) > 0:  # 이미 인증된 세션
        return

    ip = _client_ip(request)
    _throttle_guard(ip)

    if not password or not secrets.compare_digest(
        password, settings.paid_model_password
    ):
        _record_failure(ip)
        raise HTTPException(
            status_code=401,
            detail="질의는 유료 API 를 사용합니다. 비밀번호가 필요합니다.",
        )

    _fail_state.pop(ip, None)  # 성공 시 실패 카운트 초기화
    if response is not None:
        _issue_session(response)


# ---------------------------------------------------------------------------
@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    """서버 상태 + 비밀번호 보호 상태 (비밀번호 자체는 절대 노출 X)."""
    return {
        "status": "ok",
        "model": settings.openai_model,
        "password_required": True,
        "password_configured": settings.password_configured,
        "unlock_remaining_sec": _session_remaining(request),
    }


@app.post("/unlock")
def unlock(req: UnlockRequest, request: Request, response: Response) -> dict[str, Any]:
    """비밀번호를 확인하고 인증 쿠키를 발급 (유효기간 paid_session_minutes 분)."""
    if not settings.password_configured:
        raise HTTPException(
            status_code=503,
            detail="서버에 비밀번호가 설정되지 않아 질의가 비활성화되어 있습니다.",
        )
    ip = _client_ip(request)
    _throttle_guard(ip)
    if not secrets.compare_digest(req.password or "", settings.paid_model_password):
        _record_failure(ip)
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")
    _fail_state.pop(ip, None)
    _issue_session(response)
    return {"unlocked": True, "expires_in_sec": settings.paid_session_minutes * 60}


@app.post("/lock")
def lock(response: Response) -> dict[str, Any]:
    """인증 쿠키 삭제 (수동 잠금)."""
    response.delete_cookie(_SESSION_COOKIE, path="/")
    return {"unlocked": False}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, response: Response) -> ChatResponse:
    """질문 → 에이전트 실행 → 응답.

    임베딩 + LLM 으로 실제 요금이 청구되므로 비밀번호(또는 유효한 인증 쿠키)가 필요합니다.
    """
    _verify_paid_access(req.password, request, response)

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
