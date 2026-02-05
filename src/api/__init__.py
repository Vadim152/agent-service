"""Маршруты HTTP API."""
from fastapi import APIRouter

from .routes_generate import router as generate_router
from .routes_jobs import router as jobs_router
from .routes_llm import router as llm_router
from .routes_steps import router as steps_router

router = APIRouter()
router.include_router(steps_router)
router.include_router(llm_router)
router.include_router(generate_router)
router.include_router(jobs_router)

__all__ = ["router"]
