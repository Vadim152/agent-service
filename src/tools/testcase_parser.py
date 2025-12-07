"""Парсер текстового тесткейса в доменный сценарий.

Логика построена на простых эвристиках без участия LLM. В будущем сюда можно
добавить более интеллектуальный разбор с использованием LLM или шаблонов для
конкретных форматов тест-кейсов.
"""
from __future__ import annotations

import re
from typing import Iterable

from domain.models import Scenario, TestStep


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
