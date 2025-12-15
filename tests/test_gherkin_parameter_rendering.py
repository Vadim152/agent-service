"""Проверки подстановки параметров в сгенерированный Gherkin."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from domain.enums import StepKeyword
from domain.models import Scenario, StepDefinition, TestStep
from tools.feature_generator import FeatureGenerator
from tools.step_matcher import StepMatcher


def test_builds_gherkin_line_with_regex_numbers() -> None:
    matcher = StepMatcher()
    definition = StepDefinition(
        id="1",
        keyword=StepKeyword.WHEN,
        pattern="Пользователь вводит {amount} рублей",
        regex=r"Пользователь вводит (\d+) рублей",
        code_ref="steps.money",
        parameters=[],
        tags=[],
    )
    test_step = TestStep(order=1, text="Пользователь вводит 150 рублей")

    matches = matcher.match_steps([test_step], [definition])

    assert matches[0].generated_gherkin_line == f"{StepKeyword.WHEN.as_text()} Пользователь вводит 150 рублей"


def test_feature_generator_renders_substituted_values() -> None:
    matcher = StepMatcher()
    definition = StepDefinition(
        id="2",
        keyword=StepKeyword.THEN,
        pattern="Отображается товар {item}",
        regex=r"Отображается товар (.+)",
        code_ref="steps.catalog",
        parameters=[],
        tags=[],
    )
    test_step = TestStep(order=1, text="Отображается товар Красная рубашка")

    matched = matcher.match_steps([test_step], [definition])[0]
    scenario = Scenario(
        name="Просмотр товара",
        description="",
        steps=[test_step],
        expected_result=None,
        tags=[],
    )
    feature = FeatureGenerator().build_feature(scenario, [matched])
    rendered = FeatureGenerator().render_feature(feature)

    assert matched.generated_gherkin_line == f"{StepKeyword.THEN.as_text()} Отображается товар Красная рубашка"
    assert "Отображается товар Красная рубашка" in rendered
    assert "{item}" not in rendered

