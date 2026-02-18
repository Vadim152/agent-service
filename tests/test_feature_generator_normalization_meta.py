from __future__ import annotations

from domain.enums import MatchStatus, StepKeyword
from domain.models import MatchedStep, Scenario, StepDefinition, TestStep
from tools.feature_generator import FeatureGenerator
from tools.testcase_step_normalizer import build_normalization_section


def test_feature_generator_renders_table_rows_without_unmatched_marker() -> None:
    table_step = TestStep(order=1, text="| value |")
    matched = MatchedStep(
        test_step=table_step,
        status=MatchStatus.UNMATCHED,
        step_definition=None,
        notes={"reason": "no_definition_found"},
    )
    scenario = Scenario(name="Table scenario", description=None, steps=[table_step], tags=[])

    rendered = FeatureGenerator().render_feature(
        FeatureGenerator().build_feature(scenario, [matched], language="ru")
    )
    assert "Когда <no_definition_found" not in rendered
    assert "| value |" in rendered


def test_feature_generator_exposes_normalization_meta_in_step_details() -> None:
    definition = StepDefinition(
        id="1",
        keyword=StepKeyword.GIVEN,
        pattern="пользователь авторизован",
        regex=r"пользователь авторизован",
        code_ref="steps.auth",
    )
    section = build_normalization_section(
        normalized_from="Дано подготовим среду И пользователь авторизован",
        strategy="rule",
    )
    test_step = TestStep(order=1, text="пользователь авторизован", section=section)
    matched = MatchedStep(
        test_step=test_step,
        status=MatchStatus.EXACT,
        step_definition=definition,
        resolved_step_text="пользователь авторизован",
    )
    scenario = Scenario(name="Normalization meta", description=None, steps=[test_step], tags=[])

    feature = FeatureGenerator().build_feature(scenario, [matched], language="ru")
    details = feature.scenarios[0].steps_details[0]
    meta = details["meta"]

    assert meta["normalizedFrom"] == "Дано подготовим среду И пользователь авторизован"
    assert meta["normalizationStrategy"] == "rule"
    assert meta["renderSource"] == "definition_pattern"

def test_feature_generator_maps_tmslink_tag_to_feature_and_scenario_tags() -> None:
    definition = StepDefinition(
        id="1",
        keyword=StepKeyword.GIVEN,
        pattern="data is prepared",
        regex=r"data is prepared",
        code_ref="steps.setup",
    )
    test_step = TestStep(order=1, text="data is prepared")
    matched = MatchedStep(
        test_step=test_step,
        status=MatchStatus.EXACT,
        step_definition=definition,
        resolved_step_text="data is prepared",
    )
    scenario = Scenario(
        name="Jira scenario",
        description=None,
        steps=[test_step],
        tags=["TmsLink=SCBC-T3280"],
    )

    rendered = FeatureGenerator().render_feature(
        FeatureGenerator().build_feature(scenario, [matched], language="en")
    )

    assert "\n@SCBC-T3280\nFeature: Jira scenario\n" in rendered
    assert "\n@TmsLink=SCBC-T3280\n  Scenario: Jira scenario\n" in rendered
