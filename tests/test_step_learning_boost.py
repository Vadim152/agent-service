from __future__ import annotations

from domain.enums import StepKeyword
from domain.models import StepDefinition, TestStep
from tools.step_matcher import StepMatcher


def test_step_boost_can_change_selected_definition() -> None:
    matcher = StepMatcher()
    test_steps = [TestStep(order=1, text="open login page")]
    step_definitions = [
        StepDefinition(
            id="s1",
            keyword=StepKeyword.GIVEN,
            pattern="open login form",
            regex=None,
            code_ref="steps.login_form",
            parameters=[],
            tags=[],
        ),
        StepDefinition(
            id="s2",
            keyword=StepKeyword.GIVEN,
            pattern="open account page",
            regex=None,
            code_ref="steps.account_page",
            parameters=[],
            tags=[],
        ),
    ]

    baseline = matcher.match_steps(test_steps, step_definitions)
    assert baseline[0].step_definition is not None
    baseline_id = baseline[0].step_definition.id
    assert baseline_id in {"s1", "s2"}
    boosted_id = "s1" if baseline_id == "s2" else "s2"

    boosted = matcher.match_steps(
        test_steps,
        step_definitions,
        step_boosts={boosted_id: 0.2},
    )
    assert boosted[0].step_definition is not None
    assert boosted[0].step_definition.id == boosted_id
