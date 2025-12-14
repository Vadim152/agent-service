"""Pydantic-схемы запросов и ответов для HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    """Преобразует snake_case в camelCase для JSON."""

    parts = value.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


class ApiBaseModel(BaseModel):
    """Базовая модель для API со стилем camelCase и populate_by_name."""

    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class StepDefinitionDto(ApiBaseModel):
    """Упрощённое представление StepDefinition для отдачи в API."""

    id: str = Field(..., description="Уникальный идентификатор шага")
    keyword: str = Field(..., description="Ключевое слово шага (Given/When/Then)")
    pattern: str = Field(..., description="Паттерн шага из аннотации")
    code_ref: str = Field(..., alias="codeRef", description="Ссылка на исходный код")
    tags: list[str] | None = Field(
        default=None, description="Теги шага из исходника, если есть"
    )


class UnmappedStepDto(ApiBaseModel):
    """Шаг тесткейса, который не удалось сопоставить с cucumber-шагом."""

    text: str = Field(..., description="Текст исходного шага тесткейса")
    reason: str | None = Field(
        default=None, description="Причина отсутствия сопоставления"
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
    used_steps: list[StepDefinitionDto] = Field(
        ..., alias="usedSteps", description="Шаги фреймворка, использованные в feature"
    )
    meta: dict[str, Any] | None = Field(
        default=None, description="Дополнительные метаданные о feature"
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
    "ScanStepsRequest",
    "ScanStepsResponse",
    "StepDefinitionDto",
    "UnmappedStepDto",
]
