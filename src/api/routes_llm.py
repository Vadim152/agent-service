"""Роуты для проверки доступности LLM-провайдера."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from agents.orchestrator import Orchestrator
from api.schemas import LlmTestRequest, LlmTestResponse

router = APIRouter(prefix="/llm", tags=["llm"])
logger = logging.getLogger(__name__)


def _get_orchestrator(request: Request) -> Orchestrator:
    orchestrator: Orchestrator | None = getattr(request.app.state, "orchestrator", None)
    if not orchestrator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Orchestrator is not initialized",
        )
    return orchestrator


@router.post("/test", response_model=LlmTestResponse, summary="Проверка доступности LLM")
async def test_llm(request_model: LlmTestRequest, request: Request) -> LlmTestResponse:
    """Выполняет тестовый вызов LLM для проверки доступности провайдера."""

    orchestrator = _get_orchestrator(request)
    llm_client = getattr(orchestrator, "llm_client", None)
    if not llm_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM client is not configured",
        )

    prompt = request_model.prompt.strip() or LlmTestRequest.model_fields["prompt"].default  # type: ignore[index]
    logger.info("API: тестовый запрос к LLM (len=%s)", len(prompt))

    try:
        reply = llm_client.generate(prompt)
    except Exception as exc:  # pragma: no cover - внешний провайдер
        logger.exception("API: ошибка при вызове LLM")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM request failed: {exc}",
        ) from exc

    logger.info("API: тестовый ответ от LLM получен (len=%s)", len(reply))
    return LlmTestResponse(
        prompt=prompt,
        reply=reply,
        provider=getattr(llm_client, "__class__", type("", (), {})).__name__,
        model=getattr(llm_client, "model_name", None),
    )

