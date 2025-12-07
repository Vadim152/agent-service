"""Генерация текстового .feature файла на основе доменных моделей."""
from __future__ import annotations

from domain.enums import StepKeyword
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

        scenario_steps = [self._render_step(ms) for ms in matched_steps]
        feature_scenario = FeatureScenario(
            name=scenario.name,
            tags=scenario.tags,
            steps=scenario_steps,
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

    def _render_step(self, matched_step: MatchedStep) -> str:
        """Преобразует MatchedStep в строку Gherkin."""

        if matched_step.status.value == "unmatched" or not matched_step.step_definition:
            return matched_step.generated_gherkin_line or self._unmatched_comment(matched_step.test_step.text)

        keyword = self._select_keyword(matched_step)
        body = matched_step.generated_gherkin_line or matched_step.step_definition.pattern
        return f"{keyword} {body}" if body else self._unmatched_comment(matched_step.test_step.text)

    def _select_keyword(self, matched_step: MatchedStep) -> str:
        """Выбирает ключевое слово для шага."""

        definition = matched_step.step_definition
        if definition and isinstance(definition.keyword, StepKeyword):
            return definition.keyword.as_text()
        return StepKeyword.WHEN.as_text()

    @staticmethod
    def _unmatched_comment(step_text: str) -> str:
        """Создает комментарий для шага без сопоставления."""

        return f"# TODO: не найден шаг для: \"{step_text}\""
