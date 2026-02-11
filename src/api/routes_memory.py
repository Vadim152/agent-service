"""Project memory and feedback routes for learning loop."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from api.schemas import MemoryFeedbackRequest, MemoryFeedbackResponse
from infrastructure.project_learning_store import ProjectLearningStore

router = APIRouter(prefix="/memory", tags=["memory"])


def _get_learning_store(request: Request) -> ProjectLearningStore:
    orchestrator = getattr(request.app.state, "orchestrator", None)
    store = getattr(orchestrator, "project_learning_store", None) if orchestrator else None
    if not store:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project learning store is not initialized",
        )
    return store


@router.post("/feedback", response_model=MemoryFeedbackResponse)
async def submit_feedback(payload: MemoryFeedbackRequest, request: Request) -> MemoryFeedbackResponse:
    store = _get_learning_store(request)
    updated = store.record_feedback(
        project_root=payload.project_root,
        step_id=payload.step_id,
        accepted=payload.accepted,
        note=payload.note,
        preference_key=payload.preference_key,
        preference_value=payload.preference_value,
    )
    return MemoryFeedbackResponse(
        project_root=payload.project_root,
        updated_at=updated.get("updatedAt"),
        step_boosts=store.get_step_boosts(payload.project_root),
        feedback_count=len(updated.get("feedback", [])),
    )

