from __future__ import annotations

from domain.models import TestStep
from infrastructure.llm_client import LLMClient
from tools.testcase_step_normalizer import (
    normalize_source_step_text,
    normalize_source_step_text_with_meta,
    normalize_test_steps,
    parse_normalization_section,
)


class _LlmArrayStub(LLMClient):
    def generate(self, prompt: str, **kwargs):  # noqa: ANN001, ANN003
        _ = (prompt, kwargs)
        return '["шаг один", "шаг два"]'


def test_splits_inline_gherkin_keywords() -> None:
    text = "Дано подготовим среду И авторизуемся клиентом И запомним сессию"
    parts = normalize_source_step_text(text, source="raw")
    assert parts == [
        "Дано подготовим среду",
        "И авторизуемся клиентом",
        "И запомним сессию",
    ]


def test_splits_compound_sentence_aggressively() -> None:
    text = "осуществим переход по диплинку, проверим что кошелек загрузился, вернемся на главную страницу"
    parts = normalize_source_step_text(text, source="raw")
    assert len(parts) == 3
    assert parts[0].startswith("осуществим переход")
    assert parts[1].startswith("проверим")
    assert parts[2].startswith("вернемся")


def test_does_not_split_url_clause() -> None:
    text = "откроем страницу https://example.test/path, затем проверим баннер"
    parts = normalize_source_step_text(text, source="raw")
    assert parts == [text]


def test_uses_llm_fallback_for_ambiguous_long_text() -> None:
    text = (
        "в рамках проверки пользователь проходит основной путь, после чего фиксируется промежуточное "
        "состояние, затем выполняется валидация финального состояния экрана без явных технических "
        "инструкций и формальных глагольных шагов"
    )
    parts, meta = normalize_source_step_text_with_meta(
        text,
        source="raw",
        llm_client=_LlmArrayStub(),
    )
    assert parts == ["шаг один", "шаг два"]
    assert meta["llmFallbackUsed"] is True
    assert meta["llmFallbackSuccessful"] is True
    assert meta["strategy"] == "llm_fallback"


def test_normalize_test_steps_attaches_normalization_section() -> None:
    source_steps = [TestStep(order=1, text="Дано подготовим среду И авторизуемся клиентом")]
    normalized_steps, report = normalize_test_steps(source_steps, source="raw")

    assert len(normalized_steps) == 2
    assert report["inputSteps"] == 1
    assert report["splitCount"] == 1

    section_meta = parse_normalization_section(normalized_steps[0].section)
    assert section_meta is not None
    assert section_meta["normalizedFrom"] == source_steps[0].text
    assert section_meta["normalizationStrategy"] == "rule"
