"""Роуты, связанные со сканированием шагов."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable

from fastapi import Body, APIRouter, HTTPException, Request, status

from agents.orchestrator import Orchestrator
from api.schemas import ScanStepsRequest, ScanStepsResponse, StepDefinitionDto
from domain.models import StepDefinition

router = APIRouter(prefix="/steps", tags=["steps"])
logger = logging.getLogger(__name__)


def _get_orchestrator(request: Request) -> Orchestrator:
    orchestrator: Orchestrator | None = getattr(request.app.state, "orchestrator", None)
    if not orchestrator:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Orchestrator is not initialized",
        )
    return orchestrator


def _to_step_dto(step_definitions: Iterable[StepDefinition]) -> list[StepDefinitionDto]:
    return [
        StepDefinitionDto(
            id=step.id,
            keyword=str(step.keyword.value),
            pattern=step.pattern,
            code_ref=step.code_ref,
            tags=step.tags or None,
        )
        for step in step_definitions
    ]


def _preview_body(raw_body: bytes, limit: int = 512) -> str:
    """Возвращает безопасный префикс тела запроса для логов."""

    if not raw_body:
        return ""

    try:
        text = raw_body.decode("utf-8", errors="replace")
    except Exception:
        text = str(raw_body)

    if len(text) > limit:
        text = text[:limit] + "...<truncated>"

    return text


async def _extract_project_root(
    request: Request,
    request_model: ScanStepsRequest | None,
    raw_body: bytes,
    parsed_body: dict | None,
) -> tuple[str | None, dict]:
    """Извлекает projectRoot из разных видов тела запроса и возвращает детали."""

    details: dict[str, str | int | None] = {
        "content_type": request.headers.get("content-type"),
        "content_length": request.headers.get("content-length"),
        "query_root": None,
        "header_root": None,
        "body_json_root": None,
        "body_text_root": None,
        "form_root": None,
        "model_root": None,
        "body_length": len(raw_body or b""),
    }

    if request_model and request_model.project_root:
        details["model_root"] = request_model.project_root
        return request_model.project_root, details

    query_root = request.query_params.get("projectRoot") or request.query_params.get(
        "project_root"
    )
    if query_root:
        details["query_root"] = query_root
        return query_root, details

    header_root = request.headers.get("x-project-root")
    if header_root:
        details["header_root"] = header_root
        return header_root, details

    if isinstance(parsed_body, dict):
        body_root = parsed_body.get("projectRoot") or parsed_body.get("project_root")
        if body_root:
            details["body_json_root"] = str(body_root)
            return str(body_root), details

    if raw_body and not parsed_body:
        text_root = raw_body.decode(errors="ignore").strip()
        if text_root:
            details["body_text_root"] = text_root
            return text_root, details

    try:
        form_data = await request.form()
    except Exception:
        form_data = None

    if form_data:
        body_root = form_data.get("projectRoot") or form_data.get("project_root")
        if body_root:
            details["form_root"] = str(body_root)
            return str(body_root), details

    return None, details


@router.post("/scan-steps", response_model=ScanStepsResponse, summary="Сканировать проект на Cucumber шаги")
async def scan_steps(
    request: Request,
) -> ScanStepsResponse:
    """Запускает сканирование проекта и возвращает краткую статистику."""

    orchestrator = _get_orchestrator(request)

    # Читаем тело вручную, чтобы избежать 422 при не-JSON или пустом body
    try:
        raw_body = await request.body()
    except Exception:
        raw_body = b""

    parsed_model: ScanStepsRequest | None = None
    parsed_json: dict | None = None
    if raw_body:
        try:
            parsed_json_candidate = json.loads(raw_body)
        except json.JSONDecodeError:
            parsed_json_candidate = None

        if isinstance(parsed_json_candidate, dict):
            parsed_json = parsed_json_candidate
            try:
                parsed_model = ScanStepsRequest(**parsed_json_candidate)
            except Exception:
                parsed_model = None

    project_root, extraction_details = await _extract_project_root(
        request, parsed_model, raw_body, parsed_json
    )
    content_length_header = request.headers.get("content-length")
    body_length = len(raw_body or b"")

    if not project_root:
        header_snapshot = {
            key: value
            for key, value in request.headers.items()
            if key.lower()
            in {"content-type", "content-length", "transfer-encoding", "user-agent"}
        }
        mismatch_note = None
        try:
            if content_length_header is not None:
                expected = int(content_length_header)
                if expected != body_length:
                    mismatch_note = (
                        f"content-length header is {expected} but received {body_length} bytes"
                    )
        except ValueError:
            mismatch_note = f"invalid content-length header: {content_length_header!r}"

        logger.warning(
            "API: projectRoot is missing for scan-steps. Details: %s, headers=%s, body_preview=%s, mismatch=%s",
            extraction_details,
            header_snapshot,
            _preview_body(raw_body),
            mismatch_note,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "projectRoot is required in request body or query string"
                if not mismatch_note
                else "projectRoot is missing; "
                + mismatch_note
            ),
        )
    path_obj = Path(project_root).expanduser()
    if not path_obj.exists():
        logger.warning("Путь проекта не найден: %s", project_root)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project root not found: {project_root}",
        )

    logger.info(
        "API: запуск сканирования шагов для %s (details: %s, body_preview=%s)",
        project_root,
        extraction_details,
        _preview_body(raw_body),
    )
    result = orchestrator.scan_steps(project_root)
    sample_steps = orchestrator.step_index_store.load_steps(project_root)[:5]

    updated_at = result.get("updatedAt")
    updated_at_dt = datetime.fromisoformat(updated_at) if updated_at else datetime.utcnow()

    response = ScanStepsResponse(
        project_root=result.get("projectRoot", project_root),
        steps_count=int(result.get("stepsCount", 0)),
        updated_at=updated_at_dt,
        sample_steps=_to_step_dto(sample_steps) or None,
    )
    logger.info(
        "API: сканирование завершено для %s, шагов: %s", response.project_root, response.steps_count
    )
    return response


@router.get("/", response_model=list[StepDefinitionDto], summary="Получить сохранённые шаги")
async def list_steps(projectRoot: str, request: Request) -> list[StepDefinitionDto]:
    """Возвращает список шагов из индекса для указанного проекта."""

    orchestrator = _get_orchestrator(request)
    path_obj = Path(projectRoot).expanduser()
    if not path_obj.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project root not found: {projectRoot}",
        )

    steps = orchestrator.step_index_store.load_steps(projectRoot)
    logger.info(
        "API: получены шаги для %s, всего %s", projectRoot, len(steps)
    )
    return _to_step_dto(steps)
