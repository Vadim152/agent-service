"""Доменные модели для описания шагов, сценариев и feature-файлов."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from .enums import MatchStatus, StepKeyword


@dataclass
class StepDefinition:
    """Описание шага тестового фреймворка (Cucumber/BDD)."""

    id: str
    keyword: StepKeyword
    pattern: str
    regex: str | None
    code_ref: str
    parameters: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    language: str | None = None


@dataclass
class TestStep:
    """Шаг тесткейса, полученный из внешнего источника (Jira, ТЗ и т.п.)."""

    order: int
    text: str
    section: str | None = None


@dataclass
class Scenario:
    """Сценарий, сформированный после парсинга тесткейса."""

    name: str
    description: str | None
    preconditions: list[TestStep] = field(default_factory=list)
    steps: list[TestStep] = field(default_factory=list)
    expected_result: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class MatchedStep:
    """Результат сопоставления шага тесткейса с известными cucumber-шагами."""

    test_step: TestStep
    status: MatchStatus
    step_definition: StepDefinition | None = None
    confidence: float | None = None
    generated_gherkin_line: str | None = None
    notes: str | None = None


@dataclass
class FeatureScenario:
    """Сценарий внутри .feature файла."""

    name: str
    tags: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    is_outline: bool = False
    examples: list[Dict[str, str]] = field(default_factory=list)


@dataclass
class FeatureFile:
    """Доменная модель будущего .feature файла."""

    name: str
    description: str | None
    language: str | None
    tags: list[str] = field(default_factory=list)
    background_steps: list[str] = field(default_factory=list)
    scenarios: list[FeatureScenario] = field(default_factory=list)

    def add_scenario(self, scenario: FeatureScenario) -> None:
        """Добавляет сценарий в feature-файл."""
        self.scenarios.append(scenario)

    def to_gherkin(self) -> str:
        """Формирует текстовое представление Gherkin.

        Будет реализовано позже, когда появится полноценная генерация.
        """
        raise NotImplementedError("Метод to_gherkin будет реализован позже")
