"""Маршруты HTTP API."""
from fastapi import APIRouter

from .routes_chat import router as chat_router
from .routes_generate import router as generate_router
from .routes_jobs import router as jobs_router
from .routes_llm import router as llm_router
from .routes_memory import router as memory_router
from .routes_steps import router as steps_router
from .routes_tools import router as tools_router

router = APIRouter()
router.include_router(steps_router)
router.include_router(llm_router)
router.include_router(generate_router)
router.include_router(jobs_router)
router.include_router(chat_router)
router.include_router(memory_router)
router.include_router(tools_router)

__all__ = ["router"]
