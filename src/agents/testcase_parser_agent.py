"""Агент для разбора текстовых тесткейсов в структурированный сценарий."""
from __future__ import annotations

import logging
from typing import Any

from autogen import AssistantAgent

from agents import _serialize_scenario
from domain.models import Scenario
from infrastructure.llm_client import LLMClient
from tools.testcase_parser import TestCaseParser

logger = logging.getLogger(__name__)


class TestcaseParserAgent:
    """Оберта над TestCaseParser для использования в оркестрации."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client
        self.parser = TestCaseParser()
        self.assistant = AssistantAgent(
            name="testcase_parser",
            system_message=(
                "Ты агент, который преобразует ручной текстовый тесткейс в структурированный"
                " сценарий с шагами, ожидаемым результатом и тегами."
            ),
        )
        self.assistant.register_function({
            "parse_testcase": self.parse_testcase,
        })

    def parse_testcase(self, testcase_text: str) -> dict[str, Any]:
        """Разобрать текст тесткейса в Scenario и вернуть сериализуемый словарь."""

        logger.info("[TestcaseParserAgent] Разбор тесткейса (длина=%s)", len(testcase_text))
        source = "heuristic"
        scenario: Scenario | None = None

        if self.llm_client:
            try:
                scenario = self.parser.parse_with_llm(testcase_text, self.llm_client)
                source = "llm"
            except Exception:
                logger.warning("[TestcaseParserAgent] LLM парсинг не удался, fallback на эвристику", exc_info=True)

        if scenario is None:
            scenario = self.parser.parse(testcase_text)

        logger.debug(
            "[TestcaseParserAgent] Сценарий: %s, шагов: %s", scenario.name, len(scenario.steps)
        )
        serialized = _serialize_scenario(scenario)
        serialized["source"] = source
        return serialized


__all__ = ["TestcaseParserAgent"]
