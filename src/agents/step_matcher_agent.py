"""Агент для сопоставления шагов тесткейса с cucumber-определениями."""
from __future__ import annotations

import logging
from typing import Any

from autogen import AssistantAgent

from agents import _deserialize_scenario, _serialize_matched_step
from domain.enums import MatchStatus
from domain.models import MatchedStep, Scenario
from infrastructure.embeddings_store import EmbeddingsStore
from infrastructure.llm_client import LLMClient
from infrastructure.step_index_store import StepIndexStore
from tools.step_matcher import StepMatcher

logger = logging.getLogger(__name__)


class StepMatcherAgent:
    """Оберта над StepMatcher с интеграцией хранилища шагов."""

    def __init__(
        self,
        step_index_store: StepIndexStore,
        embeddings_store: EmbeddingsStore,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.step_index_store = step_index_store
        self.embeddings_store = embeddings_store
        self.llm_client = llm_client
        self.matcher = StepMatcher(llm_client=llm_client, embeddings_store=embeddings_store)
        self.assistant = AssistantAgent(
            name="step_matcher",
            system_message=(
                "Ты агент, который сопоставляет шаги тесткейса с определениями cucumber."
                " Используй сохранённый индекс шагов и возвращай степень уверенности."
            ),
        )
        self.assistant.register_function({
            "match_testcase_steps": self.match_testcase_steps,
        })

    def match_testcase_steps(self, project_root: str, scenario_dict: dict[str, Any]) -> dict[str, Any]:
        """Матчит шаги сценария по сохранённому индексу."""

        logger.info("[StepMatcherAgent] Матчинг шагов для проекта %s", project_root)
        scenario: Scenario = _deserialize_scenario(scenario_dict)
        step_definitions = self.step_index_store.load_steps(project_root)
        logger.debug(
            "[StepMatcherAgent] Загружено шагов для сопоставления: %s", len(step_definitions)
        )
        matched_steps: list[MatchedStep] = self.matcher.match_steps(scenario.steps, step_definitions)
        unmatched = [m.test_step.text for m in matched_steps if m.status == MatchStatus.UNMATCHED]
        logger.info(
            "[StepMatcherAgent] Матчинг завершён. Совпадений: %s, без соответствия: %s",
            len(matched_steps) - len(unmatched),
            len(unmatched),
        )
        return {
            "matched": [_serialize_matched_step(m) for m in matched_steps],
            "unmatched": unmatched,
        }


__all__ = ["StepMatcherAgent"]
