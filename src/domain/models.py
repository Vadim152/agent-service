"""Доменные модели для описания шагов, сценариев и feature-файлов."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable

from .enums import MatchStatus, ScenarioType, StepIntentType, StepKeyword, StepPatternType

GHERKIN_KEYWORDS: dict[str, dict[str, str]] = {
    "ru": {
        "Feature": "Функционал",
        "Background": "Предыстория",
        "Scenario": "Сценарий",
        "Scenario Outline": "Структура сценария",
        "Examples": "Примеры",
    }
}


def localize_gherkin_keyword(keyword: str, language: str | None) -> str:
    """Возвращает локализованное ключевое слово Gherkin."""

    if not language:
        return keyword
    return GHERKIN_KEYWORDS.get(language, {}).get(keyword, keyword)


@dataclass
class StepParameter:
    """Структурированное описание параметра шага."""

    name: str
    type: str | None = None
    placeholder: str | None = None


@dataclass
class StepImplementation:
    """Информация об исходной реализации шага."""

    file: str | None = None
    line: int | None = None
    class_name: str | None = None
    method_name: str | None = None


@dataclass
class StepDefinition:
    """Описание шага тестового фреймворка (Cucumber/BDD)."""

    id: str
    keyword: StepKeyword
    pattern: str
    regex: str | None
    code_ref: str
    pattern_type: StepPatternType = StepPatternType.CUCUMBER_EXPRESSION
    parameters: list[StepParameter] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    language: str | None = None
    implementation: StepImplementation | None = None
    summary: str | None = None
    doc_summary: str | None = None
    examples: list[str] = field(default_factory=list)
    step_type: StepIntentType | None = None
    usage_count: int = 0
    linked_scenario_ids: list[str] = field(default_factory=list)
    sample_scenario_refs: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    domain: str | None = None

    def __post_init__(self) -> None:
        if self.doc_summary and not self.summary:
            self.summary = self.doc_summary
        if self.summary and not self.doc_summary:
            self.doc_summary = self.summary
        if isinstance(self.pattern_type, str):
            self.pattern_type = StepPatternType(self.pattern_type)
        self.pattern_type = self.pattern_type or StepPatternType.CUCUMBER_EXPRESSION
        self.parameters = list(self._normalize_parameters(self.parameters))
        if self.step_type and isinstance(self.step_type, str):
            self.step_type = StepIntentType(self.step_type)
        if self.implementation and not isinstance(self.implementation, StepImplementation):
            impl = self.implementation
            self.implementation = StepImplementation(**impl) if isinstance(impl, dict) else None

    @staticmethod
    def _normalize_parameters(parameters: Iterable[StepParameter | str | dict]) -> Iterable[StepParameter]:
        for param in parameters:
            if isinstance(param, StepParameter):
                yield param
            elif isinstance(param, dict):
                yield StepParameter(**param)
            else:
                yield StepParameter(name=str(param))


@dataclass
class TestStep:
    """Шаг тесткейса, полученный из внешнего источника (Jira, ТЗ и т.п.)."""

    order: int
    text: str
    section: str | None = None
    intent_type: StepIntentType | None = None
    source_text: str | None = None
    __test__ = False


@dataclass
class Scenario:
    """Сценарий, сформированный после парсинга тесткейса."""

    name: str
    description: str | None
    preconditions: list[TestStep] = field(default_factory=list)
    steps: list[TestStep] = field(default_factory=list)
    expected_result: str | None = None
    tags: list[str] = field(default_factory=list)
    test_data: list[str] = field(default_factory=list)
    scenario_type: ScenarioType = ScenarioType.STANDARD
    canonical: dict[str, Any] | None = None


@dataclass
class CanonicalStep:
    order: int
    text: str
    intent_type: StepIntentType
    source: str
    origin: str
    confidence: float = 1.0
    normalized_from: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalTestCase:
    title: str
    preconditions: list[CanonicalStep] = field(default_factory=list)
    actions: list[CanonicalStep] = field(default_factory=list)
    expected_results: list[CanonicalStep] = field(default_factory=list)
    test_data: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    scenario_type: ScenarioType = ScenarioType.STANDARD
    domain_context: str | None = None
    source: str | None = None


@dataclass
class ScenarioCatalogEntry:
    id: str
    name: str
    feature_path: str
    scenario_name: str
    tags: list[str] = field(default_factory=list)
    background_steps: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    scenario_type: ScenarioType = ScenarioType.STANDARD
    document: str | None = None
    description: str | None = None


@dataclass
class SimilarScenarioCandidate:
    scenario_id: str
    name: str
    feature_path: str
    score: float
    matched_fragments: list[str] = field(default_factory=list)
    background_steps: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    recommended: bool = False


@dataclass
class BindingCandidate:
    step_id: str
    step_text: str
    status: MatchStatus
    confidence: float
    reason: str | None = None
    source: str | None = None


@dataclass
class GenerationPlanItem:
    order: int
    text: str
    intent_type: StepIntentType
    section: str
    keyword: StepKeyword
    binding_candidates: list[BindingCandidate] = field(default_factory=list)
    selected_step_id: str | None = None
    warning: str | None = None


@dataclass
class GenerationPlan:
    plan_id: str
    source: str
    recommended_scenario_id: str | None = None
    selected_scenario_id: str | None = None
    candidate_background: list[str] = field(default_factory=list)
    items: list[GenerationPlanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    draft_feature_text: str = ""


@dataclass
class MatchedStep:
    """Результат сопоставления шага тесткейса с известными cucumber-шагами."""

    test_step: TestStep
    status: MatchStatus
    step_definition: StepDefinition | None = None
    confidence: float | None = None
    generated_gherkin_line: str | None = None
    resolved_step_text: str | None = None
    matched_parameters: list[dict[str, Any]] = field(default_factory=list)
    parameter_fill_meta: Dict[str, Any] | None = None
    notes: Dict[str, Any] | None = None


@dataclass
class FeatureScenario:
    """Сценарий внутри .feature файла."""

    name: str
    tags: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    steps_details: list[dict[str, Any]] = field(default_factory=list)
    is_outline: bool = False
    examples: list[Dict[str, str]] = field(default_factory=list)


@dataclass
class FeatureFile:
    """Доменная модель будущего .feature файла."""

    name: str
    description: str | None
    language: str | None
    tags: list[str] = field(default_factory=list)
    background_steps: list[str] = field(default_factory=list)
    scenarios: list[FeatureScenario] = field(default_factory=list)

    def add_scenario(self, scenario: FeatureScenario) -> None:
        """Добавляет сценарий в feature-файл."""
        self.scenarios.append(scenario)

    def to_gherkin(self) -> str:
        """Формирует текстовое представление Gherkin."""

        lines: list[str] = []
        if self.language:
            lines.append(f"# language: {self.language}")

        if self.tags:
            lines.append(" ".join(f"@{tag}" for tag in self.tags))

        feature_keyword = localize_gherkin_keyword("Feature", self.language)
        lines.append(f"{feature_keyword}: {self.name}")

        if self.description:
            lines.append("")
            lines.append(self.description)

        if self.background_steps:
            lines.append("")
            background_keyword = localize_gherkin_keyword("Background", self.language)
            lines.append(f"  {background_keyword}:")
            for step in self.background_steps:
                lines.append(f"    {step}")

        for scenario in self.scenarios:
            lines.append("")
            if scenario.tags:
                lines.append(" ".join(f"@{tag}" for tag in scenario.tags))
            scenario_type = "Scenario Outline" if scenario.is_outline else "Scenario"
            localized_scenario_type = localize_gherkin_keyword(scenario_type, self.language)
            lines.append(f"  {localized_scenario_type}: {scenario.name}")
            for step in scenario.steps:
                lines.append(f"    {step}")
            if scenario.is_outline and scenario.examples:
                examples_keyword = localize_gherkin_keyword("Examples", self.language)
                lines.append(f"    {examples_keyword}:")
                for example in scenario.examples:
                    lines.append("      | " + " | ".join(str(value) for value in example.values()) + " |")

        return "\n".join(lines).rstrip() + "\n"


@dataclass
class CorrelationFields:
    run_id: str
    attempt_id: str | None = None
    source: str | None = None


@dataclass
class FailureClassification:
    correlation: CorrelationFields
    category: str
    confidence: float
    signals: list[str] = field(default_factory=list)


@dataclass
class RemediationAction:
    correlation: CorrelationFields
    action: str
    strategy: str
    safe: bool = True
    result: dict[str, Any] | None = None


@dataclass
class RunAttempt:
    correlation: CorrelationFields
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    classification: FailureClassification | None = None
    remediation: RemediationAction | None = None


@dataclass
class Run:
    correlation: CorrelationFields
    attempts: list[RunAttempt] = field(default_factory=list)
    status: str = "started"


@dataclass
class IncidentReport:
    correlation: CorrelationFields
    summary: str
    hypotheses: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)


@dataclass
class Job:
    correlation: CorrelationFields
    status: str
    created_at: str
    updated_at: str
    runs: list[Run] = field(default_factory=list)
    incident_report: IncidentReport | None = None
