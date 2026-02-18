"""Agent wrapper around testcase parsing and step normalization."""
from __future__ import annotations

import logging
from typing import Any

from agents import _serialize_scenario
from domain.models import Scenario
from infrastructure.llm_client import LLMClient
from tools.testcase_parser import TestCaseParser
from tools.testcase_step_normalizer import normalize_test_steps

logger = logging.getLogger(__name__)


class TestcaseParserAgent:
    """Parse free-form testcase text into a serializable scenario payload."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client
        self.parser = TestCaseParser()

    def parse_testcase(self, testcase_text: str) -> dict[str, Any]:
        logger.info("[TestcaseParserAgent] Parse testcase text (len=%s)", len(testcase_text))
        source = "heuristic"
        scenario: Scenario | None = None

        if self.llm_client:
            try:
                scenario = self.parser.parse_with_llm(testcase_text, self.llm_client)
                source = "llm"
            except Exception:
                logger.warning(
                    "[TestcaseParserAgent] LLM parsing failed, fallback to heuristic parser",
                    exc_info=True,
                )

        if scenario is None:
            scenario = self.parser.parse(testcase_text)

        normalized_steps, normalization_report = normalize_test_steps(
            scenario.steps,
            source=source,
            llm_client=self.llm_client,
        )
        scenario.steps = normalized_steps

        logger.debug(
            "[TestcaseParserAgent] Scenario=%s, steps=%s",
            scenario.name,
            len(scenario.steps),
        )
        serialized = _serialize_scenario(scenario)
        serialized["source"] = source
        serialized["normalization"] = normalization_report
        return serialized


__all__ = ["TestcaseParserAgent"]
