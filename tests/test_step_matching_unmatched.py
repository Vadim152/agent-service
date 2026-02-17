"""Проверки для поведения при отсутствии сопоставлений шагов."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from domain.enums import MatchStatus, StepKeyword
from domain.models import MatchedStep, Scenario, StepDefinition, TestStep
from tools.feature_generator import FeatureGenerator
from tools.step_matcher import StepMatcher


def test_match_steps_collects_structured_notes_for_unmatched() -> None:
    matcher = StepMatcher()
    test_steps = [TestStep(order=1, text="Выполнить важное действие")]
    step_definitions = [
        StepDefinition(
            id="1",
            keyword=StepKeyword.GIVEN,
            pattern="Открыт стартовый экран",
            regex=None,
            code_ref="steps.start_screen",
            parameters=[],
            tags=[],
        )
    ]

    matches = matcher.match_steps(test_steps, step_definitions)

    assert matches[0].status is MatchStatus.UNMATCHED
    assert matches[0].generated_gherkin_line is None
    notes = matches[0].notes or {}
    assert notes["reason"] == "no_definition_found"
    assert notes["original_text"] == "Выполнить важное действие"
    assert notes["closest_pattern"] == "Открыт стартовый экран"
    assert "confidence" in notes
    assert notes.get("final_score", 0.0) >= notes["confidence_sources"]["sequence"]
    assert set(notes.get("confidence_sources", {}).keys()) == {
        "sequence",
        "embedding",
        "parameter_fit",
        "llm",
    }
    assert "TODO" not in (matches[0].generated_gherkin_line or "")


def test_feature_generator_renders_placeholder_without_todo() -> None:
    generator = FeatureGenerator()
    test_step = TestStep(order=1, text="Неизвестный шаг")
    matched_step = MatchedStep(
        test_step=test_step,
        status=MatchStatus.UNMATCHED,
        step_definition=None,
        generated_gherkin_line=None,
        notes={"reason": "no_definition_found"},
    )
    scenario = Scenario(
        name="Сценарий без сопоставлений",
        description="",
        steps=[test_step],
        expected_result=None,
        tags=[],
    )

    feature = generator.build_feature(scenario, [matched_step])
    rendered = generator.render_feature(feature)

    assert "TODO" not in rendered
    assert f"{StepKeyword.WHEN.as_text('ru')} <no_definition_found: {test_step.text}>" in rendered

