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
from tools.step_matcher import StepMatcher, StepMatcherConfig

logger = logging.getLogger(__name__)


class StepMatcherAgent:
    """Thin wrapper around StepMatcher with store integrations."""

    def __init__(
        self,
        step_index_store: StepIndexStore,
        embeddings_store: EmbeddingsStore,
        llm_client: LLMClient | None = None,
        project_learning_store: ProjectLearningStore | None = None,
        matcher_config: StepMatcherConfig | None = None,
    ) -> None:
        self.step_index_store = step_index_store
        self.embeddings_store = embeddings_store
        self.llm_client = llm_client
        self.project_learning_store = project_learning_store
        self.matcher = StepMatcher(
            llm_client=llm_client,
            embeddings_store=embeddings_store,
            config=matcher_config,
        )

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
        exact_definition_matches = 0
        source_text_fallback_used = 0
        llm_reranked_count = 0
        ambiguous_count = 0
        for match in matched_steps:
            notes = match.notes if isinstance(match.notes, dict) else {}
            if match.status is not MatchStatus.UNMATCHED and bool(notes.get("exact_definition_match")):
                exact_definition_matches += 1
            if bool(notes.get("llm_reranked")):
                llm_reranked_count += 1
            ambiguity_gap = notes.get("ambiguity_gap")
            if isinstance(ambiguity_gap, (float, int)) and float(ambiguity_gap) < self.matcher.config.ambiguity_gap:
                ambiguous_count += 1
            fill_meta = match.parameter_fill_meta if isinstance(match.parameter_fill_meta, dict) else {}
            if str(fill_meta.get("source") or "").casefold() == "source_text_fallback":
                source_text_fallback_used += 1
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
            "exactDefinitionMatches": exact_definition_matches,
            "sourceTextFallbackUsed": source_text_fallback_used,
            "llmRerankedCount": llm_reranked_count,
            "ambiguousCount": ambiguous_count,
        }


__all__ = ["StepMatcherAgent"]
