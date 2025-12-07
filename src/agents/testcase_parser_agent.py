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
        self.assistant.register_function(
            self.parse_testcase,
            name="parse_testcase",
            description="Парсит текст тесткейса в структуру Scenario",
        )

    def parse_testcase(self, testcase_text: str) -> dict[str, Any]:
        """Разобрать текст тесткейса в Scenario и вернуть сериализуемый словарь."""

        logger.info("[TestcaseParserAgent] Разбор тесткейса (длина=%s)", len(testcase_text))
        scenario: Scenario = self.parser.parse(testcase_text)
        logger.debug(
            "[TestcaseParserAgent] Сценарий: %s, шагов: %s", scenario.name, len(scenario.steps)
        )
        return _serialize_scenario(scenario)


__all__ = ["TestcaseParserAgent"]
