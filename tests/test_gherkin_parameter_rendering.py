"""Проверки подстановки параметров в сгенерированный Gherkin."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from domain.enums import MatchStatus, StepKeyword
from domain.models import MatchedStep, Scenario, StepDefinition, TestStep
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

    assert matches[0].generated_gherkin_line is None

    scenario = Scenario(
        name="Оплата заказа",
        description="",
        steps=[test_step],
        expected_result=None,
        tags=[],
    )
    feature = FeatureGenerator().build_feature(scenario, matches, language="ru")
    rendered = FeatureGenerator().render_feature(feature)

    assert f"{StepKeyword.WHEN.as_text('ru')} Пользователь вводит 150 рублей" in rendered


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

    assert matched.generated_gherkin_line is None
    assert "Отображается товар Красная рубашка" in rendered
    assert "{item}" not in rendered


def test_feature_generator_localizes_given_keyword_in_ru() -> None:
    matcher = StepMatcher()
    definition = StepDefinition(
        id="3",
        keyword=StepKeyword.GIVEN,
        pattern="Пользователь авторизован",
        regex=None,
        code_ref="steps.auth",
        parameters=[],
        tags=[],
    )
    test_step = TestStep(order=1, text="Пользователь авторизован")

    matched = matcher.match_steps([test_step], [definition])[0]
    scenario = Scenario(
        name="Авторизация",
        description="",
        steps=[test_step],
        expected_result=None,
        tags=[],
    )
    feature = FeatureGenerator().build_feature(scenario, [matched], language="ru")
    rendered = FeatureGenerator().render_feature(feature)

    assert "Дано Пользователь авторизован" in rendered


def test_localizes_generated_gherkin_line_for_ru_language() -> None:
    matched = MatchedStep(
        test_step=TestStep(order=1, text="Given something"),
        status=MatchStatus.EXACT,
        step_definition=None,
        generated_gherkin_line="Given something",
        notes=None,
    )
    scenario = Scenario(
        name="Локализация",
        description="",
        steps=[matched.test_step],
        expected_result=None,
        tags=[],
    )
    feature = FeatureGenerator().build_feature(scenario, [matched], language="ru")
    rendered = FeatureGenerator().render_feature(feature)

    assert "Дано something" in rendered
