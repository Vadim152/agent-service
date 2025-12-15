"""Генерация текстового .feature файла на основе доменных моделей."""
from __future__ import annotations

import re
from typing import Any

from domain.enums import MatchStatus, StepKeyword
from domain.models import FeatureFile, FeatureScenario, MatchedStep, Scenario


class FeatureGenerator:
    """Собирает FeatureFile и финальный Gherkin-текст."""

    def build_feature(
        self, scenario: Scenario, matched_steps: list[MatchedStep], language: str | None = None
    ) -> FeatureFile:
        """Создает структуру FeatureFile на основе сценария и сопоставленных шагов."""

        feature = FeatureFile(
            name=scenario.name or "Feature",
            description=scenario.description or scenario.expected_result,
            language=language or "ru",
            tags=scenario.tags,
            background_steps=[],
            scenarios=[],
        )

        scenario_steps: list[str] = []
        steps_details: list[dict[str, Any]] = []
        for matched_step in matched_steps:
            rendered, meta = self._render_step(matched_step)
            scenario_steps.append(rendered)
            step_payload: dict[str, Any] = {
                "originalStep": matched_step.test_step.text,
                "generatedLine": rendered,
                "status": matched_step.status.value,
            }
            if meta:
                step_payload["meta"] = meta
            steps_details.append(step_payload)

        feature_scenario = FeatureScenario(
            name=scenario.name,
            tags=scenario.tags,
            steps=scenario_steps,
            steps_details=steps_details,
            is_outline=False,
            examples=[],
        )
        feature.add_scenario(feature_scenario)
        return feature

    def render_feature(self, feature: FeatureFile) -> str:
        """Собирает текст Gherkin из модели FeatureFile."""

        lines: list[str] = []
        if feature.language:
            lines.append(f"# language: {feature.language}")

        if feature.tags:
            lines.append(" ".join(f"@{tag}" for tag in feature.tags))

        lines.append(f"Feature: {feature.name}")

        if feature.description:
            lines.append("")
            lines.append(feature.description)

        if feature.background_steps:
            lines.append("")
            lines.append("  Background:")
            for step in feature.background_steps:
                lines.append(f"    {step}")

        for scenario in feature.scenarios:
            lines.append("")
            if scenario.tags:
                lines.append(" ".join(f"@{tag}" for tag in scenario.tags))
            lines.append(f"  Scenario: {scenario.name}")
            for step in scenario.steps:
                lines.append(f"    {step}")

        return "\n".join(lines).rstrip() + "\n"

    def _render_step(self, matched_step: MatchedStep) -> tuple[str, dict[str, Any]]:
        """Преобразует MatchedStep в строку Gherkin и сопутствующие метаданные."""

        if matched_step.generated_gherkin_line:
            return matched_step.generated_gherkin_line, {"substitutionType": "generated"}

        if matched_step.status is MatchStatus.UNMATCHED or not matched_step.step_definition:
            reason = None
            if isinstance(matched_step.notes, dict):
                reason = matched_step.notes.get("reason")
            marker = reason or "unmatched"
            line = f"{StepKeyword.WHEN.as_text()} <{marker}: {matched_step.test_step.text}>"
            meta: dict[str, Any] = {"substitutionType": "unmatched"}
            if reason:
                meta["reason"] = reason
            return line, meta

        rendered, meta = self._build_gherkin_line(matched_step)
        return rendered, meta

    def _select_keyword(self, matched_step: MatchedStep) -> str:
        """Выбирает ключевое слово для шага."""

        definition = matched_step.step_definition
        if definition and isinstance(definition.keyword, StepKeyword):
            return definition.keyword.as_text()
        return StepKeyword.WHEN.as_text()

    def _build_gherkin_line(self, matched_step: MatchedStep) -> tuple[str, dict[str, Any]]:
        """Формирует строку Gherkin для найденного определения с подстановкой параметров."""

        definition = matched_step.step_definition
        if not definition:
            return "", {"substitutionType": "unmatched"}

        keyword = self._select_keyword(matched_step)
        pattern = definition.pattern
        regex = definition.regex or pattern

        filled_pattern = pattern
        try:
            match = re.search(regex, matched_step.test_step.text)
        except re.error:
            match = None

        substitution_type = "pattern"
        if match:
            groups = match.groups()
            placeholders = re.findall(r"\{[^}]+\}", pattern)

            if groups and placeholders:
                for placeholder, value in zip(placeholders, groups):
                    filled_pattern = filled_pattern.replace(placeholder, value, 1)
            elif groups:
                filled_pattern = " ".join([pattern] + list(groups))
            substitution_type = "regex"

        rendered = f"{keyword} {filled_pattern}" if filled_pattern else keyword
        return rendered, {"substitutionType": substitution_type}
