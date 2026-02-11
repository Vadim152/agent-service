"""Shared runtime-level exceptions."""
from __future__ import annotations


class ChatRuntimeError(RuntimeError):
    """Raised by chat runtime when request-level processing fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

