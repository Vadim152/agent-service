"""Проверки сопоставления шагов с учетом эмбеддингов и LLM."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

from domain.enums import MatchStatus, StepKeyword
from domain.models import StepDefinition, TestStep
from infrastructure.llm_client import LLMClient
from tools.step_matcher import StepMatcher


class FakeEmbeddingsStore:
    def __init__(self, results: list[tuple[StepDefinition, float]]) -> None:
        self.results = results
        self.queries: list[tuple[str, str, int]] = []

    def get_top_k(self, project_root: str, query: str, top_k: int = 5):
        self.queries.append((project_root, query, top_k))
        return self.results[:top_k]


class FakeLLMClient(LLMClient):
    def __init__(self, response: str) -> None:
        super().__init__(allow_fallback=False)
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str, **kwargs):
        self.prompts.append(prompt)
        return self.response


def test_match_steps_prioritizes_embeddings_candidates() -> None:
    step_definitions = [
        StepDefinition(
            id="1",
            keyword=StepKeyword.GIVEN,
            pattern="Пользователь авторизован",
            regex=None,
            code_ref="steps.auth", 
            parameters=[],
            tags=[],
        ),
        StepDefinition(
            id="2",
            keyword=StepKeyword.WHEN,
            pattern="Открываю корзину пользователя",
            regex=None,
            code_ref="steps.cart",
            parameters=[],
            tags=[],
        ),
    ]

    embeddings_store = FakeEmbeddingsStore([(step_definitions[1], 0.9), (step_definitions[0], 0.4)])
    matcher = StepMatcher(embeddings_store=embeddings_store)

    matches = matcher.match_steps(
        [TestStep(order=1, text="Открыть корзину пользователя")],
        step_definitions,
        project_root="/tmp/project",
    )

    assert matches[0].step_definition == step_definitions[1]
    assert matches[0].status is MatchStatus.EXACT
    assert matches[0].confidence and matches[0].confidence > 0.75
    assert embeddings_store.queries  # убедились, что обращение в стор произошло


def test_llm_reranks_top_candidates() -> None:
    step_definitions = [
        StepDefinition(
            id="10",
            keyword=StepKeyword.WHEN,
            pattern="Открываю корзину",
            regex=None,
            code_ref="steps.cart.open",
            parameters=[],
            tags=[],
        ),
        StepDefinition(
            id="20",
            keyword=StepKeyword.WHEN,
            pattern="Закрываю корзину",
            regex=None,
            code_ref="steps.cart.close",
            parameters=[],
            tags=[],
        ),
    ]

    embeddings_store = FakeEmbeddingsStore([(step_definitions[0], 0.55), (step_definitions[1], 0.55)])
    llm_client = FakeLLMClient("C2")
    matcher = StepMatcher(llm_client=llm_client, embeddings_store=embeddings_store)

    matches = matcher.match_steps(
        [TestStep(order=1, text="Обновляю корзину")],
        step_definitions,
        project_root="/tmp/project",
    )

    assert matches[0].step_definition == step_definitions[1]
    assert matches[0].status is MatchStatus.FUZZY
    assert matches[0].confidence and matches[0].confidence > 0.6
    assert llm_client.prompts


def test_exact_text_match_skips_llm_rerank() -> None:
    step_definitions = [
        StepDefinition(
            id="30",
            keyword=StepKeyword.WHEN,
            pattern="авторизуемся клиентом для тестирования",
            regex=None,
            code_ref="steps.auth.exact",
            parameters=[],
            tags=[],
        ),
        StepDefinition(
            id="40",
            keyword=StepKeyword.WHEN,
            pattern="авторизоваться клиентом для тестирования",
            regex=None,
            code_ref="steps.auth.infinitive",
            parameters=[],
            tags=[],
        ),
    ]

    llm_client = FakeLLMClient("C2")
    matcher = StepMatcher(llm_client=llm_client)
    matches = matcher.match_steps(
        [TestStep(order=1, text="авторизуемся клиентом для тестирования")],
        step_definitions,
    )

    assert matches[0].step_definition == step_definitions[0]
    assert matches[0].status is MatchStatus.EXACT
    assert llm_client.prompts == []
    notes = matches[0].notes or {}
    assert notes.get("exact_definition_match") is True
