"""Remediation playbooks с allowlist-действиями."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RemediationDecision:
    action: str
    strategy: str
    safe: bool
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "strategy": self.strategy,
            "safe": self.safe,
            "notes": self.notes,
        }


class RemediationPlaybooks:
    def decide(self, category: str) -> RemediationDecision:
        mapping = {
            "infra": RemediationDecision("backoff_retry", "exponential_backoff", True, "Retry after short delay"),
            "flaky": RemediationDecision("rerun_isolated", "isolation_mode", True, "Rerun in isolated execution mode"),
            "env": RemediationDecision("env_reset", "safe_reprovision", True, "Safe environment reset requested"),
            "data": RemediationDecision("data_reset", "safe_seed_rebuild", True, "Restore stable seed/fixtures"),
            "automation": RemediationDecision("enable_debug", "verbose_logging", True, "Enable verbose logs and diagnostics"),
        }
        return mapping.get(category, RemediationDecision("manual_attention", "no_auto_action", False, "Requires human review"))

    def apply(self, decision: RemediationDecision) -> dict[str, Any]:
        if not decision.safe:
            return {"applied": False, "reason": decision.notes}
        return {"applied": True, "action": decision.action, "strategy": decision.strategy}
