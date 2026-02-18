"""Утилиты для работы с Cucumber Expression."""
from __future__ import annotations

import re


_TYPE_MAP: dict[str, str] = {
    "int": r"(\d+)",
    "integer": r"(\d+)",
    "float": r"(\d+(?:\.\d+)?)",
    "double": r"(\d+(?:\.\d+)?)",
    "word": r"(\w+)",
    "string": r"\"?([^\"\n]+)\"?",
    "byte": r"(\d+)",
    "short": r"(\d+)",
    "long": r"(\d+)",
    "bigdecimal": r"(\d+(?:\.\d+)?)",
}
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")


def cucumber_expression_to_regex(pattern: str) -> str:
    """Преобразует Cucumber Expression в регулярное выражение."""

    parts: list[str] = []
    last_end = 0
    for match in _PLACEHOLDER_RE.finditer(pattern):
        literal = pattern[last_end : match.start()]
        parts.append(re.escape(literal))
        placeholder = match.group(1).strip()
        type_name = placeholder.split(":")[-1].strip().casefold() or "string"
        parts.append(_TYPE_MAP.get(type_name, r"(.+?)"))
        last_end = match.end()

    parts.append(re.escape(pattern[last_end:]))
    return f"^{''.join(parts)}$"
