"""Агент для генерации .feature текста из сопоставленных шагов."""
from __future__ import annotations

import logging
from typing import Any

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
        step_details = []
        for scenario in feature.scenarios:
            step_details.extend(scenario.steps_details or [])
        steps_summary = {
            "exact": sum(1 for match in matched_steps if match.status == MatchStatus.EXACT),
            "fuzzy": sum(1 for match in matched_steps if match.status == MatchStatus.FUZZY),
            "unmatched": sum(1 for match in matched_steps if match.status == MatchStatus.UNMATCHED),
        }
        parameter_fill_summary = {"full": 0, "partial": 0, "fallback": 0, "none": 0}
        for detail in step_details:
            meta = detail.get("meta") if isinstance(detail, dict) else None
            if not isinstance(meta, dict):
                parameter_fill_summary["none"] += 1
                continue
            fill_meta = meta.get("parameterFill")
            if isinstance(fill_meta, dict):
                status = str(fill_meta.get("status") or "").casefold()
            else:
                status = str(meta.get("parameterFillStatus") or "").casefold()
            if status in parameter_fill_summary:
                parameter_fill_summary[status] += 1
            elif status:
                parameter_fill_summary["none"] += 1
            else:
                parameter_fill_summary["none"] += 1

        logger.info(
            "[FeatureBuilderAgent] Feature собран: %s, шагов: %s", feature.name, len(feature.scenarios)
        )
        return {
            "featureText": rendered,
            "unmappedSteps": unmapped_steps,
            "stepDetails": step_details,
            "buildStage": "feature_built",
            "stepsSummary": steps_summary,
            "parameterFillSummary": parameter_fill_summary,
            "meta": {
                "featureName": feature.name,
                "language": feature.language,
            },
            "feature": _serialize_feature(feature, rendered_text=rendered),
        }


__all__ = ["FeatureBuilderAgent"]
