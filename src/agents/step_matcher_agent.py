"""Agent that matches testcase steps against indexed cucumber steps."""
from __future__ import annotations

import logging
from typing import Any

from agents import _deserialize_scenario, _serialize_matched_step
from domain.enums import MatchStatus
from domain.models import MatchedStep, Scenario
from infrastructure.embeddings_store import EmbeddingsStore
from infrastructure.llm_client import LLMClient
from infrastructure.project_learning_store import ProjectLearningStore
from infrastructure.step_index_store import StepIndexStore
from tools.step_matcher import StepMatcher

logger = logging.getLogger(__name__)


class StepMatcherAgent:
    """Thin wrapper around StepMatcher with store integrations."""

    def __init__(
        self,
        step_index_store: StepIndexStore,
        embeddings_store: EmbeddingsStore,
        llm_client: LLMClient | None = None,
        project_learning_store: ProjectLearningStore | None = None,
    ) -> None:
        self.step_index_store = step_index_store
        self.embeddings_store = embeddings_store
        self.llm_client = llm_client
        self.project_learning_store = project_learning_store
        self.matcher = StepMatcher(llm_client=llm_client, embeddings_store=embeddings_store)

    def match_testcase_steps(self, project_root: str, scenario_dict: dict[str, Any]) -> dict[str, Any]:
        logger.info("[StepMatcherAgent] Matching steps for project %s", project_root)
        scenario: Scenario = _deserialize_scenario(scenario_dict)
        step_definitions = self.step_index_store.load_steps(project_root)
        step_boosts = (
            self.project_learning_store.get_step_boosts(project_root)
            if self.project_learning_store
            else {}
        )
        index_status = "ready" if step_definitions else "missing"
        logger.debug("[StepMatcherAgent] Loaded %s step definitions", len(step_definitions))
        matched_steps: list[MatchedStep] = self.matcher.match_steps(
            scenario.steps,
            step_definitions,
            project_root=project_root,
            step_boosts=step_boosts,
        )
        unmatched = [m.test_step.text for m in matched_steps if m.status == MatchStatus.UNMATCHED]
        logger.info(
            "[StepMatcherAgent] Matching complete. Matched=%s, unmatched=%s",
            len(matched_steps) - len(unmatched),
            len(unmatched),
        )
        return {
            "matched": [_serialize_matched_step(m) for m in matched_steps],
            "unmatched": unmatched,
            "indexStatus": index_status,
            "needsScan": not step_definitions,
        }


__all__ = ["StepMatcherAgent"]
