"""Маршруты HTTP API."""
from fastapi import APIRouter

from .routes_generate import router as generate_router
from .routes_llm import router as llm_router
from .routes_memory import router as memory_router
from .routes_opencode import router as opencode_router
from .routes_policy import router as policy_router
from .routes_runs import router as runs_router
from .routes_sessions import router as sessions_router
from .routes_steps import router as steps_router
from .routes_tools import router as tools_router

router = APIRouter()
router.include_router(steps_router)
router.include_router(llm_router)
router.include_router(generate_router)
router.include_router(runs_router)
router.include_router(sessions_router)
router.include_router(opencode_router)
router.include_router(policy_router)
router.include_router(memory_router)
router.include_router(tools_router)

__all__ = ["router"]
