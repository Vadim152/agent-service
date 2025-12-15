"""Pydantic-схемы запросов и ответов для HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domain.enums import StepKeyword, StepPatternType


def _to_camel(value: str) -> str:
    """Преобразует snake_case в camelCase для JSON."""

    parts = value.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


class ApiBaseModel(BaseModel):
    """Базовая модель для API со стилем camelCase и populate_by_name."""

    model_config = ConfigDict(
        alias_generator=_to_camel, populate_by_name=True, from_attributes=True
    )


class StepParameterDto(ApiBaseModel):
    """Структурированное описание параметра шага."""

    name: str = Field(..., description="Имя параметра из сигнатуры шага")
    type: str | None = Field(
        default=None, description="Тип параметра (например, string/int/object)"
    )
    placeholder: str | None = Field(
        default=None,
        description="Исходный placeholder или регулярное выражение из паттерна",
    )


class StepImplementationDto(ApiBaseModel):
    """Информация об исходном файле и методе, реализующем шаг."""

    file: str | None = Field(default=None, description="Путь к файлу с реализацией")
    line: int | None = Field(default=None, description="Номер строки аннотации шага")
    class_name: str | None = Field(
        default=None, alias="className", description="Имя класса, если применимо"
    )
    method_name: str | None = Field(
        default=None, alias="methodName", description="Имя метода, если применимо"
    )


class StepDefinitionDto(ApiBaseModel):
    """Упрощённое представление StepDefinition для отдачи в API."""

    id: str = Field(..., description="Уникальный идентификатор шага")
    keyword: StepKeyword = Field(
        ..., description="Ключевое слово шага (Given/When/Then/And/But)"
    )
    pattern: str = Field(..., description="Паттерн шага из аннотации")
    pattern_type: StepPatternType = Field(
        default=StepPatternType.CUCUMBER_EXPRESSION,
        alias="patternType",
        description="Тип паттерна: cucumberExpression или regularExpression",
    )
    regex: str | None = Field(
        default=None,
        description="Регулярное выражение шага, если оно есть в исходнике",
    )
    code_ref: str = Field(..., alias="codeRef", description="Ссылка на исходный код")
    parameters: list[StepParameterDto] = Field(
        default_factory=list,
        description="Список параметров шага с типами и плейсхолдерами",
    )
    tags: list[str] | None = Field(
        default=None, description="Теги шага из исходника, если есть"
    )
    language: str | None = Field(
        default=None, description="Язык шага в исходнике (ru/en и т.д.)"
    )
    implementation: StepImplementationDto | None = Field(
        default=None,
        description="Подробности о файле, строке и методе, реализующем шаг",
    )
    summary: str | None = Field(
        default=None, description="Краткое описание шага из документации"
    )
    doc_summary: str | None = Field(
        default=None,
        alias="docSummary",
        description="Резюме шага, обогащенное LLM или документацией",
    )
    examples: list[str] = Field(
        default_factory=list,
        description="Примеры использования шага из комментариев или документации",
    )


class UnmappedStepDto(ApiBaseModel):
    """Шаг тесткейса, который не удалось сопоставить с cucumber-шагом."""

    text: str = Field(..., description="Текст исходного шага тесткейса")
    reason: str | None = Field(
        default=None, description="Причина отсутствия сопоставления"
    )


class StepsSummaryDto(ApiBaseModel):
    """Краткая статистика по результатам сопоставления шагов."""

    exact: int = Field(default=0, description="Количество точных совпадений")
    fuzzy: int = Field(default=0, description="Количество нестрогих совпадений")
    unmatched: int = Field(default=0, description="Количество шагов без сопоставления")


class PipelineStepDto(ApiBaseModel):
    """Описание шага пайплайна генерации feature."""

    stage: str = Field(..., description="Название этапа")
    status: str = Field(..., description="Статус выполнения этапа")
    details: dict[str, Any] | None = Field(
        default=None, description="Дополнительные детали об этапe"
    )


class ScanStepsRequest(ApiBaseModel):
    """Запрос на сканирование проекта для построения индекса шагов."""

    project_root: str = Field(..., alias="projectRoot", description="Путь к проекту")


class ScanStepsResponse(ApiBaseModel):
    """Ответ со статистикой после сканирования шагов."""

    project_root: str = Field(..., alias="projectRoot", description="Путь к проекту")
    steps_count: int = Field(..., alias="stepsCount", description="Количество шагов")
    updated_at: datetime = Field(..., alias="updatedAt", description="Время обновления")
    sample_steps: list[StepDefinitionDto] | None = Field(
        default=None,
        alias="sampleSteps",
        description="Первые найденные шаги для предпросмотра",
    )
    unmapped_steps: list[UnmappedStepDto] = Field(
        default_factory=list,
        alias="unmappedSteps",
        description="Шаги тесткейса без сопоставления",
    )


class GenerateFeatureOptions(ApiBaseModel):
    """Опции управления генерацией и сохранением .feature файла."""

    create_file: bool = Field(
        default=False, alias="createFile", description="Создавать ли файл на диске"
    )
    overwrite_existing: bool = Field(
        default=False,
        alias="overwriteExisting",
        description="Перезаписывать существующий файл",
    )
    language: str | None = Field(
        default=None, description="Желаемый язык Gherkin (ru/en)"
    )


class GenerateFeatureRequest(ApiBaseModel):
    """Запрос на генерацию .feature на основе тесткейса."""

    project_root: str = Field(..., alias="projectRoot", description="Путь к проекту")
    test_case_text: str = Field(
        ..., alias="testCaseText", description="Текст тесткейса, вставленный пользователем"
    )
    target_path: str | None = Field(
        default=None,
        alias="targetPath",
        description="Путь к целевому .feature относительно projectRoot",
    )
    options: GenerateFeatureOptions | None = Field(
        default=None, description="Опции генерации и сохранения файла"
    )


class GenerateFeatureResponse(ApiBaseModel):
    """Ответ с результатами генерации .feature файла."""

    feature_text: str = Field(..., alias="featureText", description="Сгенерированный текст")
    unmapped_steps: list[UnmappedStepDto] = Field(
        ..., alias="unmappedSteps", description="Шаги без сопоставления"
    )
    unmapped: list[str] = Field(
        default_factory=list, description="Не сопоставленные шаги из матчера"
    )
    used_steps: list[StepDefinitionDto] = Field(
        ..., alias="usedSteps", description="Шаги фреймворка, использованные в feature"
    )
    build_stage: str | None = Field(
        default=None, alias="buildStage", description="Этап сборки feature"
    )
    steps_summary: StepsSummaryDto | None = Field(
        default=None, alias="stepsSummary", description="Сводка по статусам шагов"
    )
    meta: dict[str, Any] | None = Field(
        default=None, description="Дополнительные метаданные о feature"
    )
    pipeline: list[PipelineStepDto] = Field(
        default_factory=list,
        description="Последовательность этапов построения feature",
    )


class ApplyFeatureRequest(ApiBaseModel):
    """Запрос на сохранение .feature файла в репозитории."""

    project_root: str = Field(..., alias="projectRoot", description="Путь к проекту")
    target_path: str = Field(
        ..., alias="targetPath", description="Целевой путь .feature относительно проекта"
    )
    feature_text: str = Field(..., alias="featureText", description="Содержимое файла")
    overwrite_existing: bool = Field(
        default=False,
        alias="overwriteExisting",
        description="Перезаписывать существующий файл",
    )


class ApplyFeatureResponse(ApiBaseModel):
    """Ответ после попытки записи .feature файла."""

    project_root: str = Field(..., alias="projectRoot", description="Путь к проекту")
    target_path: str = Field(
        ..., alias="targetPath", description="Целевой путь .feature относительно проекта"
    )
    status: str = Field(..., description="Статус операции: created/overwritten/skipped")
    message: str | None = Field(default=None, description="Дополнительное пояснение")


class LlmTestRequest(ApiBaseModel):
    """Запрос на тестовый вызов LLM."""

    prompt: str = Field(
        default="Ping from agent-service: please confirm connectivity.",
        description="Промпт, который будет отправлен в LLM",
    )


class LlmTestResponse(ApiBaseModel):
    """Ответ на тестовый вызов LLM."""

    prompt: str = Field(..., description="Отправленный промпт")
    reply: str = Field(..., description="Ответ LLM на тестовый запрос")
    provider: str | None = Field(default=None, description="Имя провайдера LLM")
    model: str | None = Field(default=None, description="Используемая модель LLM")


__all__ = [
    "ApplyFeatureRequest",
    "ApplyFeatureResponse",
    "LlmTestRequest",
    "LlmTestResponse",
    "GenerateFeatureOptions",
    "GenerateFeatureRequest",
    "GenerateFeatureResponse",
    "PipelineStepDto",
    "ScanStepsRequest",
    "ScanStepsResponse",
    "StepImplementationDto",
    "StepDefinitionDto",
    "StepParameterDto",
    "StepsSummaryDto",
    "UnmappedStepDto",
]
