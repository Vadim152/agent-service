"""Heuristic failure taxonomy classifier."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class FailureClassificationResult:
    category: str
    confidence: float
    signals: list[str]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FailureClassifier:
    taxonomy = ("infra", "env", "data", "flaky", "product", "automation", "unknown")

    def classify(self, artifacts: dict[str, str]) -> FailureClassificationResult:
        text = "\n".join(v for v in artifacts.values() if v).lower()
        signals: list[str] = []

        if any(token in text for token in ("timeout", "connection reset", "dns", "503", "502")):
            signals.append("network_or_infra_signal")
            return FailureClassificationResult("infra", 0.86, signals, "Infrastructure/network instability")
        if any(token in text for token in ("assert", "expected", "actual", "mismatch")):
            signals.append("assertion_signal")
            return FailureClassificationResult("product", 0.72, signals, "Product-level assertion failed")
        if any(token in text for token in ("element not found", "stale element", "locator", "ui")):
            signals.append("ui_automation_signal")
            return FailureClassificationResult("automation", 0.74, signals, "Automation issue while interacting with UI")
        if any(token in text for token in ("flaky", "intermittent", "rerun pass", "random")):
            signals.append("flaky_signal")
            return FailureClassificationResult("flaky", 0.81, signals, "Likely flaky test")
        if any(token in text for token in ("seed", "fixture", "test data", "dataset", "not found in db")):
            signals.append("data_signal")
            return FailureClassificationResult("data", 0.78, signals, "Test data/setup issue")
        if any(token in text for token in ("environment", "config", "permission denied", "missing env")):
            signals.append("env_signal")
            return FailureClassificationResult("env", 0.7, signals, "Environment misconfiguration")

        return FailureClassificationResult("unknown", 0.3, signals, "Unable to classify failure confidently")
