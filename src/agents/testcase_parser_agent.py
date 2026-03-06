"""Agent wrapper around testcase parsing and step normalization."""
from __future__ import annotations

import logging
from typing import Any

from agents import _serialize_scenario
from domain.enums import StepIntentType
from domain.models import Scenario, TestStep
from infrastructure.llm_client import LLMClient
from tools.testcase_parser import TestCaseParser
from tools.testcase_step_normalizer import normalize_test_steps

logger = logging.getLogger(__name__)


class TestcaseParserAgent:
    """Parse free-form testcase text into a serializable scenario payload."""

    __test__ = False

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client
        self.parser = TestCaseParser()

    def parse_testcase(self, testcase_text: str) -> dict[str, Any]:
        logger.info("[TestcaseParserAgent] Parse testcase text (len=%s)", len(testcase_text))
        source = "heuristic"
        scenario = self.parser.parse(testcase_text)

        # Keep default parsing deterministic and avoid LLM paraphrasing.
        if self.llm_client and not scenario.steps:
            try:
                scenario = self.parser.parse_with_llm(testcase_text, self.llm_client)
                source = "llm"
            except Exception:
                logger.warning(
                    "[TestcaseParserAgent] LLM parsing failed, heuristic result is used",
                    exc_info=True,
                )

        preconditions = list(scenario.preconditions)
        action_steps = [step for step in scenario.steps if step.section == "step"]
        expected_steps = [step for step in scenario.steps if step.section == "expected_result"]

        normalized_preconditions, precondition_report = normalize_test_steps(
            preconditions,
            source=source,
            llm_client=None,
        )
        normalized_actions, action_report = normalize_test_steps(
            action_steps,
            source=source,
            llm_client=None,
        )
        normalized_expected, expected_report = normalize_test_steps(
            expected_steps,
            source=source,
            llm_client=None,
        )
        normalization_report = {
            "inputSteps": precondition_report["inputSteps"]
            + action_report["inputSteps"]
            + expected_report["inputSteps"],
            "normalizedSteps": precondition_report["normalizedSteps"]
            + action_report["normalizedSteps"]
            + expected_report["normalizedSteps"],
            "splitCount": precondition_report["splitCount"]
            + action_report["splitCount"]
            + expected_report["splitCount"],
            "llmFallbackUsed": bool(precondition_report["llmFallbackUsed"])
            or bool(action_report["llmFallbackUsed"])
            or bool(expected_report["llmFallbackUsed"]),
            "llmFallbackSuccessful": bool(precondition_report["llmFallbackSuccessful"])
            or bool(action_report["llmFallbackSuccessful"])
            or bool(expected_report["llmFallbackSuccessful"]),
            "llmParseUsed": source == "llm",
            "source": source,
        }
        scenario.preconditions = self._relabel_steps(
            normalized_preconditions,
            section="precondition",
            default_intent=StepIntentType.SETUP,
        )
        normalized_actions = self._relabel_steps(
            normalized_actions,
            section="step",
            default_intent=None,
        )
        normalized_expected = self._relabel_steps(
            normalized_expected,
            section="expected_result",
            default_intent=StepIntentType.ASSERTION,
        )
        scenario.steps = []
        scenario.steps.extend(
            self._renumber_steps([*scenario.preconditions, *normalized_actions, *normalized_expected])
        )
        scenario.expected_result = "; ".join(step.text for step in normalized_expected) or scenario.expected_result
        scenario.canonical = self._build_canonical_payload(
            scenario,
            source=source,
        )

        logger.debug(
            "[TestcaseParserAgent] Scenario=%s, steps=%s",
            scenario.name,
            len(scenario.steps),
        )
        serialized = _serialize_scenario(scenario)
        serialized["source"] = source
        serialized["normalization"] = normalization_report
        return serialized

    @staticmethod
    def _relabel_steps(
        steps: list[TestStep],
        *,
        section: str,
        default_intent: StepIntentType | None,
    ) -> list[TestStep]:
        result: list[TestStep] = []
        for step in steps:
            result.append(
                TestStep(
                    order=step.order,
                    text=step.text,
                    section=section,
                    intent_type=step.intent_type or default_intent,
                    source_text=step.source_text or step.text,
                )
            )
        return result

    @staticmethod
    def _renumber_steps(steps: list[TestStep]) -> list[TestStep]:
        result: list[TestStep] = []
        for index, step in enumerate(steps, start=1):
            result.append(
                TestStep(
                    order=index,
                    text=step.text,
                    section=step.section,
                    intent_type=step.intent_type,
                    source_text=step.source_text,
                )
            )
        return result

    @staticmethod
    def _build_canonical_payload(
        scenario: Scenario,
        *,
        source: str,
    ) -> dict[str, Any]:
        def _serialize_step(step: TestStep, origin: str) -> dict[str, Any]:
            return {
                "order": step.order,
                "text": step.text,
                "intent_type": step.intent_type.value if step.intent_type else None,
                "source": source,
                "origin": origin,
                "confidence": 1.0,
                "normalized_from": step.source_text or step.text,
                "metadata": {},
            }

        actions = [step for step in scenario.steps if step.section == "step"]
        expected_results = [step for step in scenario.steps if step.section == "expected_result"]
        return {
            "title": scenario.name,
            "preconditions": [_serialize_step(step, "preconditions") for step in scenario.preconditions],
            "actions": [_serialize_step(step, "actions") for step in actions],
            "expected_results": [
                _serialize_step(step, "expected_results") for step in expected_results
            ],
            "test_data": list(scenario.test_data),
            "tags": list(scenario.tags),
            "scenario_type": scenario.scenario_type.value,
            "source": source,
        }


__all__ = ["TestcaseParserAgent"]
