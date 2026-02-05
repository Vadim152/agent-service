"""Capability registry и профильные pipeline'ы."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class Capability:
    name: str
    handler: Callable[..., Any]


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}

    def register(self, name: str, handler: Callable[..., Any]) -> None:
        self._items[name] = Capability(name=name, handler=handler)

    def get(self, name: str) -> Capability:
        if name not in self._items:
            raise KeyError(f"Capability is not registered: {name}")
        return self._items[name]

    def build_pipeline(self, profile: str) -> list[str]:
        common = [
            "scan_steps",
            "parse_testcase",
            "match_steps",
            "build_feature",
            "run_test_execution",
            "collect_run_artifacts",
            "classify_failure",
            "apply_remediation",
            "rerun_with_strategy",
            "incident_report_builder",
        ]
        if profile == "quick":
            return common[:7] + ["rerun_with_strategy", "incident_report_builder"]
        if profile == "strict":
            return common
        if profile == "ci":
            return common
        return common
