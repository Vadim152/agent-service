"""Роуты, связанные с генерацией и применением .feature файлов."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import ValidationError

from agents.orchestrator import Orchestrator
from api.schemas import (
    ApplyFeatureRequest,
    ApplyFeatureResponse,
    GenerateFeatureRequest,
    GenerateFeatureResponse,
    StepDefinitionDto,
    UnmappedStepDto,
)
from domain.enums import MatchStatus
from domain.models import MatchedStep

router = APIRouter(prefix="/feature", tags=["feature-generation"])
logger = logging.getLogger(__name__)


def _get_orchestrator(request: Request) -> Orchestrator:
    orchestrator: Orchestrator | None = getattr(request.app.state, "orchestrator", None)
    if not orchestrator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Orchestrator is not initialized",
        )
    return orchestrator


def _dedup_used_steps(matched: Iterable[MatchedStep | dict[str, object]]) -> list[StepDefinitionDto]:
    seen: dict[str, StepDefinitionDto] = {}
    for entry in matched:
        if isinstance(entry, dict):
            step_def = entry.get("step_definition")
            status_value = entry.get("status")
        else:
            step_def = entry.step_definition
            status_value = entry.status.value

        if not step_def or status_value == MatchStatus.UNMATCHED.value:
            continue

        dto = (
            StepDefinitionDto.model_validate(step_def, from_attributes=True)
            if not isinstance(step_def, dict)
            else StepDefinitionDto.model_validate(step_def)
        )
        if dto.id in seen:
            continue

        seen[dto.id] = dto
    return list(seen.values())


async def _read_body_with_fallback(request: Request) -> bytes:
    """Считать тело запроса с попыткой дочитать поток при несоответствии длины."""

    body = await request.body()
    if body:
        return body

    content_length = request.headers.get("content-length")
    if content_length not in (None, "0"):
        # Иногда клиенты присылают Content-Length > 0, но request.body() возвращает
        # пустое значение (например, если тело не было буферизовано). В таких
        # случаях попробуем дочитать поток вручную.
        chunks: list[bytes] = []
        async for chunk in request.stream():
            if chunk:
                chunks.append(chunk)
        if chunks:
            return b"".join(chunks)

    return body


@router.post(
    "/generate-feature",
    response_model=GenerateFeatureResponse,
    summary="Сгенерировать Gherkin-файл по тесткейсу",
)
async def generate_feature(
    request: Request, request_model: GenerateFeatureRequest | None = Body(None)
) -> GenerateFeatureResponse:
    """Генерирует .feature текст и, опционально, сохраняет его на диск."""

    body = await _read_body_with_fallback(request)
    content_length = request.headers.get("content-length")
    content_type = request.headers.get("content-type")
    body_len = len(body) if body else 0
    body_preview = body.decode("utf-8", errors="replace")[:500] if body else ""
    body_hex_preview = body[:128].hex() if body else ""

    logger.debug(
        (
            "API: generate-feature raw body; client=%s, method=%s %s, content-length=%s, "
            "read_len=%s, hex_preview=%s, utf8_preview=%r"
        ),
        request.client,
        request.method,
        request.url.path,
        content_length,
        body_len,
        body_hex_preview,
        body_preview,
    )

    if request_model is None:
        logger.debug("API: request headers snapshot=%s", dict(request.headers))
        if content_length not in (None, str(body_len)):
            logger.debug(
                "API: Content-Length mismatch: header=%s, read=%s", content_length, body_len
            )

        if body:
            try:
                request_model = GenerateFeatureRequest.model_validate_json(body)
            except ValidationError as exc:  # pragma: no cover - обрабатывается ниже
                logger.warning(
                    "API: не удалось распарсить тело запроса: %s", exc, exc_info=exc
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=exc.errors(),
                ) from exc

        if request_model is None:
            logger.warning(
                (
                    "API: пустое тело запроса (len=%s, content-length=%s, content-type=%s, "
                    "preview=%r)"
                ),
                body_len,
                content_length,
                content_type,
                body_preview,
            )
            mismatch_note = (
                "; Content-Length differs from read body"
                if content_length not in (None, str(body_len))
                else ""
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Request body is empty; ensure Content-Type: application/json and non-empty payload"
                    f" (read {body_len} bytes, content-length={content_length}{mismatch_note})"
                ),
            )

    if content_length not in (None, str(body_len)):
        logger.info(
            "API: Body read length differs from Content-Length: header=%s, read=%s",
            content_length,
            body_len,
        )

    logger.info(
        (
            "API: generate-feature payload accepted (len=%s, content-type=%s, content-length=%s,"  # noqa: E501
            " testCaseText_len=%s, targetPath=%s, options=%s, preview=%r)"
        ),
        body_len,
        content_type,
        content_length,
        len(request_model.test_case_text or ""),
        request_model.target_path,
        request_model.options,
        (request_model.test_case_text or "")[:200],
    )

    if not (request_model.test_case_text or "").strip():
        logger.warning(
            "API: testCaseText пустой или состоит из пробелов; возможно перепутаны поля UI? targetPath=%s, options=%s",  # noqa: E501
            request_model.target_path,
            request_model.options,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "testCaseText is empty; ensure the UI sends the original test case text, "
                "not the generated feature body"
            ),
        )

    orchestrator = _get_orchestrator(request)
    project_root = request_model.project_root
    path_obj = Path(project_root).expanduser()
    if not path_obj.exists():
        logger.warning("Проект не найден: %s", project_root)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project root not found: {project_root}",
        )

    options = request_model.options or None
    logger.info(
        "API: генерация feature (len=%s) для %s", len(request_model.test_case_text), project_root
    )
    result = orchestrator.generate_feature(
        project_root,
        request_model.test_case_text,
        request_model.target_path,
        create_file=bool(options.create_file) if options else False,
        overwrite_existing=bool(options.overwrite_existing) if options else False,
        language=options.language if options else None,
    )

    feature_payload = result.get("feature", {})
    match_payload = result.get("matchResult", {})
    feature_text = feature_payload.get("featureText", "")
    unmapped_steps = [
        UnmappedStepDto(text=step_text, reason="not matched")
        for step_text in feature_payload.get("unmappedSteps", [])
    ]
    used_steps = _dedup_used_steps(match_payload.get("matched", []))

    logger.info(
        "API: генерация завершена, unmapped=%s, used_steps=%s",
        len(unmapped_steps),
        len(used_steps),
    )
    return GenerateFeatureResponse(
        feature_text=feature_text,
        unmapped_steps=unmapped_steps,
        used_steps=used_steps,
        meta=feature_payload.get("meta"),
    )


@router.post(
    "/apply-feature",
    response_model=ApplyFeatureResponse,
    summary="Сохранить .feature файл на диске",
)
async def apply_feature(request_model: ApplyFeatureRequest, request: Request) -> ApplyFeatureResponse:
    """Записывает переданный .feature текст в проект."""

    orchestrator = _get_orchestrator(request)
    project_root = request_model.project_root
    path_obj = Path(project_root).expanduser()
    if not path_obj.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project root not found: {project_root}",
        )

    logger.info(
        "API: сохранение feature для %s -> %s", project_root, request_model.target_path
    )
    result = orchestrator.apply_feature(
        project_root,
        request_model.target_path,
        request_model.feature_text,
        overwrite_existing=request_model.overwrite_existing,
    )

    status_value = result.get("status", "created")
    message_value = result.get("message")
    logger.info(
        "API: сохранение завершено %s, статус=%s", request_model.target_path, status_value
    )
    return ApplyFeatureResponse(
        project_root=result.get("projectRoot", project_root),
        target_path=result.get("targetPath", request_model.target_path),
        status=status_value,
        message=message_value,
    )
