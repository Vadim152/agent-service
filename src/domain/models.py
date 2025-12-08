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
    notes: Dict[str, str] | None = None


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
        """Формирует текстовое представление Gherkin."""

        lines: list[str] = []
        if self.language:
            lines.append(f"# language: {self.language}")

        if self.tags:
            lines.append(" ".join(f"@{tag}" for tag in self.tags))

        lines.append(f"Feature: {self.name}")

        if self.description:
            lines.append("")
            lines.append(self.description)

        if self.background_steps:
            lines.append("")
            lines.append("  Background:")
            for step in self.background_steps:
                lines.append(f"    {step}")

        for scenario in self.scenarios:
            lines.append("")
            if scenario.tags:
                lines.append(" ".join(f"@{tag}" for tag in scenario.tags))
            scenario_type = "Scenario Outline" if scenario.is_outline else "Scenario"
            lines.append(f"  {scenario_type}: {scenario.name}")
            for step in scenario.steps:
                lines.append(f"    {step}")
            if scenario.is_outline and scenario.examples:
                lines.append("    Examples:")
                for example in scenario.examples:
                    lines.append("      | " + " | ".join(str(value) for value in example.values()) + " |")

        return "\n".join(lines).rstrip() + "\n"
