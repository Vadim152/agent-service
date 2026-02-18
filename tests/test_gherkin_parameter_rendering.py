"""Проверки подстановки параметров в сгенерированный Gherkin."""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from domain.enums import MatchStatus, StepKeyword, StepPatternType
from domain.models import MatchedStep, Scenario, StepDefinition, TestStep
from tools.cucumber_expression import cucumber_expression_to_regex
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
        regex=r"Пользователь авторизован",
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


def test_feature_generator_substitutes_unquoted_cucumber_strings() -> None:
    given_definition = StepDefinition(
        id="4",
        keyword=StepKeyword.GIVEN,
        pattern="открыт сайт {string}",
        regex=cucumber_expression_to_regex("открыт сайт {string}"),
        code_ref="steps.browser",
        parameters=[],
    )
    when_definition = StepDefinition(
        id="5",
        keyword=StepKeyword.WHEN,
        pattern="пользователь прокручивает страницу к элементу {string}",
        regex=cucumber_expression_to_regex(
            "пользователь прокручивает страницу к элементу {string}"
        ),
        code_ref="steps.scroll",
        parameters=[],
    )
    given_step = TestStep(order=1, text="открыт сайт google.com")
    when_step = TestStep(order=2, text="пользователь прокручивает страницу к элементу Поиск")
    matched_steps = [
        MatchedStep(
            test_step=given_step,
            status=MatchStatus.EXACT,
            step_definition=given_definition,
        ),
        MatchedStep(
            test_step=when_step,
            status=MatchStatus.EXACT,
            step_definition=when_definition,
        ),
    ]
    scenario = Scenario(
        name="Навигация",
        description="",
        steps=[given_step, when_step],
        expected_result=None,
        tags=[],
    )

    feature = FeatureGenerator().build_feature(scenario, matched_steps, language="ru")
    rendered = FeatureGenerator().render_feature(feature)

    assert "Дано открыт сайт google.com" in rendered
    assert "Когда пользователь прокручивает страницу к элементу Поиск" in rendered
    assert "{string}" not in rendered


def test_cucumber_expression_converts_anonymous_placeholder_to_capture_group() -> None:
    regex = cucumber_expression_to_regex("авторизуемся клиентом {} в МП СБОЛ")

    assert r"\{\}" not in regex
    assert regex.startswith("^") and regex.endswith("$")

    assert re.search(regex, 'авторизуемся клиентом "Иван Иванов" в МП СБОЛ')
    assert re.search(regex, "авторизуемся клиентом ООО Ромашка в МП СБОЛ")


def test_matcher_exposes_parameters_for_anonymous_cucumber_placeholder() -> None:
    definition = StepDefinition(
        id="anonymous-1",
        keyword=StepKeyword.AND,
        pattern="авторизуемся клиентом {} в МП СБОЛ",
        regex=cucumber_expression_to_regex("авторизуемся клиентом {} в МП СБОЛ"),
        code_ref="steps.auth",
        parameters=[{"name": "clientName", "type": "string", "placeholder": "{}"}],
    )
    test_step = TestStep(order=1, text='И авторизуемся клиентом "Иван Иванов" в МП СБОЛ')

    matched = StepMatcher().match_steps([test_step], [definition])[0]

    assert matched.status in {MatchStatus.EXACT, MatchStatus.FUZZY}
    assert matched.parameter_fill_meta is not None
    assert matched.parameter_fill_meta.get("status") == "full"
    assert matched.resolved_step_text == "авторизуемся клиентом Иван Иванов в МП СБОЛ"
    assert len(matched.matched_parameters) == 1
    assert matched.matched_parameters[0]["name"] == "clientName"
    assert matched.matched_parameters[0]["placeholder"] == "{}"
    assert matched.matched_parameters[0]["value"] == "Иван Иванов"


def test_matcher_exposes_parameter_fill_meta_and_parameters() -> None:
    definition = StepDefinition(
        id="6",
        keyword=StepKeyword.WHEN,
        pattern="пользователь вводит в поле {string} текст {string}",
        regex=cucumber_expression_to_regex("пользователь вводит в поле {string} текст {string}"),
        code_ref="steps.input",
        parameters=[],
    )
    test_step = TestStep(order=1, text="пользователь вводит в поле email текст qwerty")
    matched = StepMatcher().match_steps([test_step], [definition])[0]

    assert matched.status in {MatchStatus.EXACT, MatchStatus.FUZZY}
    assert matched.parameter_fill_meta is not None
    assert matched.parameter_fill_meta.get("status") == "full"
    assert len(matched.matched_parameters) >= 2
    assert matched.matched_parameters[0]["value"] == "email"
    assert matched.matched_parameters[1]["value"] == "qwerty"


def test_matcher_marks_step_unmatched_when_no_strict_match() -> None:
    definition = StepDefinition(
        id="7",
        keyword=StepKeyword.WHEN,
        pattern="пользователь вводит в поле {string} текст {string}",
        regex=cucumber_expression_to_regex("пользователь вводит в поле {string} текст {string}"),
        code_ref="steps.input",
        parameters=[],
    )
    test_step = TestStep(order=1, text="пользователь вводит в поле email значение qwerty")
    matched = StepMatcher().match_steps([test_step], [definition])[0]
    scenario = Scenario(
        name="Ввод значения",
        description="",
        steps=[test_step],
        expected_result=None,
        tags=[],
    )

    feature = FeatureGenerator().build_feature(scenario, [matched], language="ru")
    rendered = FeatureGenerator().render_feature(feature)
    assert matched.status is MatchStatus.UNMATCHED
    reason = (matched.notes or {}).get("reason")
    assert reason in {"parameter_resolution_failed", "no_definition_found"}
    assert f"<{reason}: {test_step.text}>" in rendered


def test_matcher_regular_expression_handles_leading_and_keyword_ru() -> None:
    definition = StepDefinition(
        id="8",
        keyword=StepKeyword.AND,
        pattern="^(Включим|Отключим) заглушку sbermock с id = (.*) в проекте с id = (.*)$",
        regex=r"^(Включим|Отключим) заглушку sbermock с id = (.*) в проекте с id = (.*)$",
        code_ref="steps.mock",
        pattern_type=StepPatternType.REGULAR_EXPRESSION,
        parameters=[],
    )
    test_step = TestStep(
        order=1,
        text="И Включим заглушку sbermock с id = 812074 в проекте с id = 71563",
    )

    matched = StepMatcher().match_steps([test_step], [definition])[0]

    assert matched.status in {MatchStatus.EXACT, MatchStatus.FUZZY}
    assert matched.resolved_step_text == (
        "Включим заглушку sbermock с id = 812074 в проекте с id = 71563"
    )
    assert matched.parameter_fill_meta is not None
    assert matched.parameter_fill_meta.get("status") == "full"
    assert (matched.notes or {}).get("inputLeadingKeyword") == "И"
    assert (matched.notes or {}).get("inputTextNormalizedForMatch") is True


def test_matcher_regular_expression_handles_leading_and_keyword_ru_for_sup() -> None:
    definition = StepDefinition(
        id="9",
        keyword=StepKeyword.AND,
        pattern="^поменяем значение СУП-а (.*) для ключа конфигурации (.*) на (.*)$",
        regex=r"^поменяем значение СУП-а (.*) для ключа конфигурации (.*) на (.*)$",
        code_ref="steps.mock",
        pattern_type=StepPatternType.REGULAR_EXPRESSION,
        parameters=[],
    )
    test_step = TestStep(
        order=1,
        text=(
            "И поменяем значение СУП-а credit_cards_limit_inc_mb.oneclick.enabled "
            "для ключа конфигурации CREDIT_CARDS_LIMIT_INC_MB_SBOL на true"
        ),
    )

    matched = StepMatcher().match_steps([test_step], [definition])[0]

    assert matched.status in {MatchStatus.EXACT, MatchStatus.FUZZY}
    assert matched.resolved_step_text == (
        "поменяем значение СУП-а credit_cards_limit_inc_mb.oneclick.enabled "
        "для ключа конфигурации CREDIT_CARDS_LIMIT_INC_MB_SBOL на true"
    )
    assert matched.parameter_fill_meta is not None
    assert matched.parameter_fill_meta.get("status") == "full"
