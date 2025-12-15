"""Парсер текстового тесткейса в доменный сценарий.

Логика построена на простых эвристиках без участия LLM. В будущем сюда можно
добавить более интеллектуальный разбор с использованием LLM или шаблонов для
конкретных форматов тест-кейсов.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable

from domain.models import Scenario, TestStep
from infrastructure.llm_client import LLMClient


logger = logging.getLogger(__name__)


class TestCaseParser:
    """Преобразует текст тесткейса в Scenario и последовательность TestStep."""

    STEP_PATTERNS = (
        re.compile(r"^\s*\d+[.)]\s*(?P<text>.+)$"),
        re.compile(r"^\s*(Шаг|Step)\s*\d*[:\.-]?\s*(?P<text>.+)$", re.IGNORECASE),
        re.compile(r"^\s*[-*]\s*(?P<text>.+)$"),
    )

    def parse(self, raw_text: str) -> Scenario:
        """Разбирает сырой текст тесткейса в доменную модель."""

        lines = [line.rstrip() for line in raw_text.splitlines() if line.strip()]
        name = self._extract_name(lines)
        expected_result = self._extract_expected_result(lines)
        steps = self._extract_steps(lines)

        return Scenario(
            name=name or "Без названия",
            description=None,
            preconditions=[],
            steps=steps,
            expected_result=expected_result,
            tags=[],
        )

    def parse_with_llm(self, raw_text: str, llm_client: LLMClient) -> Scenario:
        """Использует LLM для структурирования тесткейса."""

        prompt = (
            "Ты аналитик тестов. Извлеки из текста тесткейса структуру сценария. "
            "Верни строго JSON без комментариев и пояснений со следующими полями: "
            "name (строка), description (строка или null), preconditions (массив строк), "
            "steps (массив строк), expected_result (строка или null), tags (массив строк).\n"
            "Текст тесткейса:\n"
            f"{raw_text}\n"
            "Ответ должен быть только JSON."
        )

        llm_response = llm_client.generate(prompt)
        logger.debug("[TestCaseParser] LLM response: %s", llm_response)

        payload = self._extract_json(llm_response)

        preconditions = self._to_steps(payload.get("preconditions", []))
        steps = self._to_steps(payload.get("steps", []))
        expected_result = payload.get("expected_result") or payload.get("expectedResult")

        return Scenario(
            name=str(payload.get("name") or "Без названия"),
            description=payload.get("description"),
            preconditions=preconditions,
            steps=steps,
            expected_result=expected_result,
            tags=[str(tag) for tag in payload.get("tags", []) if tag],
        )

    def _extract_name(self, lines: list[str]) -> str | None:
        """Пытается определить название сценария."""

        for line in lines:
            match = re.match(r"^\s*(Сценарий|Scenario)[:\s]+(.+)$", line, re.IGNORECASE)
            if match:
                return match.group(2).strip()
        return lines[0].strip() if lines else None

    def _extract_expected_result(self, lines: Iterable[str]) -> str | None:
        """Ищет строку с ожидаемым результатом."""

        for line in lines:
            match = re.search(r"(ожидаемый результат|expected result)[:\s-]+(.+)$", line, re.IGNORECASE)
            if match:
                return match.group(2).strip()
        return None

    def _extract_steps(self, lines: list[str]) -> list[TestStep]:
        """Извлекает шаги сценария по набору паттернов."""

        steps: list[TestStep] = []
        order = 1
        for line in lines:
            extracted = self._extract_step_text(line)
            if extracted:
                steps.append(TestStep(order=order, text=extracted))
                order += 1
            elif self._is_table_row(line):
                normalized = self._normalize_table_row(line)
                steps.append(TestStep(order=order, text=normalized))
                order += 1
        return steps

    def _extract_step_text(self, line: str) -> str | None:
        """Проверяет строку на соответствие шагу и возвращает текст шага."""

        for pattern in self.STEP_PATTERNS:
            match = pattern.match(line)
            if match:
                return match.group("text").strip()
        return None

    def _is_table_row(self, line: str) -> bool:
        """Определяет, является ли строка табличной записью шага."""

        return bool(re.match(r"^\s*\|.+\|\s*$", line))

    def _normalize_table_row(self, line: str) -> str:
        """Преобразует табличный шаг в удобочитаемую строку."""

        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        return " | ".join(cells)

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Выделяет и парсит JSON-ответ LLM."""

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        raise ValueError("LLM не вернул валидный JSON для тесткейса")

    def _to_steps(self, items: Iterable[Any], *, start_order: int = 1) -> list[TestStep]:
        """Конвертирует элементы массива в TestStep с нумерацией."""

        steps: list[TestStep] = []
        order = start_order
        for item in items:
            if isinstance(item, dict):
                text = item.get("text") or item.get("step") or str(item)
            else:
                text = str(item)
            if not text:
                continue
            steps.append(TestStep(order=order, text=text.strip()))
            order += 1
        return steps
