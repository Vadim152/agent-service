"""Агент для генерации .feature текста из сопоставленных шагов."""
from __future__ import annotations

import logging
from typing import Any

from autogen import AssistantAgent

from agents import _deserialize_matched_step, _deserialize_scenario, _serialize_feature
from domain.enums import MatchStatus
from domain.models import FeatureFile, MatchedStep, Scenario
from infrastructure.llm_client import LLMClient
from tools.feature_generator import FeatureGenerator

logger = logging.getLogger(__name__)


class FeatureBuilderAgent:
    """Оберта над FeatureGenerator для построения итогового feature-файла."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client
        self.generator = FeatureGenerator()
        self.assistant = AssistantAgent(
            name="feature_builder",
            system_message=(
                "Ты агент, который собирает итоговый текст .feature на основе сценария"
                " и сопоставленных шагов."
            ),
        )
        self.assistant.register_function({
            "build_feature_from_matches": self.build_feature_from_matches,
        })

    def build_feature_from_matches(
        self,
        scenario_dict: dict[str, Any],
        matched_steps_dicts: list[dict[str, Any]],
        language: str | None = None,
    ) -> dict[str, Any]:
        """Собирает доменную модель feature и отдаёт сериализуемый результат."""

        scenario: Scenario = _deserialize_scenario(scenario_dict)
        matched_steps: list[MatchedStep] = [
            _deserialize_matched_step(entry) for entry in matched_steps_dicts
        ]
        feature: FeatureFile = self.generator.build_feature(
            scenario, matched_steps, language=language
        )
        rendered = self.generator.render_feature(feature)
        unmapped_steps = [
            match.test_step.text for match in matched_steps if match.status == MatchStatus.UNMATCHED
        ]
        steps_summary = {
            "exact": sum(1 for match in matched_steps if match.status == MatchStatus.EXACT),
            "fuzzy": sum(1 for match in matched_steps if match.status == MatchStatus.FUZZY),
            "unmatched": sum(1 for match in matched_steps if match.status == MatchStatus.UNMATCHED),
        }

        logger.info(
            "[FeatureBuilderAgent] Feature собран: %s, шагов: %s", feature.name, len(feature.scenarios)
        )
        return {
            "featureText": rendered,
            "unmappedSteps": unmapped_steps,
            "buildStage": "feature_built",
            "stepsSummary": steps_summary,
            "meta": {
                "featureName": feature.name,
                "language": feature.language,
            },
            "feature": _serialize_feature(feature, rendered_text=rendered),
        }


__all__ = ["FeatureBuilderAgent"]
