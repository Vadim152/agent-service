from __future__ import annotations

from agents.testcase_parser_agent import TestcaseParserAgent


class _FailingLlm:
    def __init__(self) -> None:
        self.called = False

    def generate(self, _prompt: str, **_kwargs) -> str:
        self.called = True
        raise RuntimeError("LLM should not be called")


class _LlmWithScenario:
    def __init__(self) -> None:
        self.called = False

    def generate(self, _prompt: str, **_kwargs) -> str:
        self.called = True
        return (
            '{"name":"LLM scenario","description":null,"preconditions":[],"steps":'
            '["Открыть экран","Нажать кнопку"],"expected_result":null,"tags":[]}'
        )


def test_parser_agent_uses_heuristic_by_default_even_with_llm() -> None:
    llm = _FailingLlm()
    agent = TestcaseParserAgent(llm_client=llm)  # type: ignore[arg-type]

    result = agent.parse_testcase("1. Открыть экран\n2. Нажать кнопку")

    assert result["source"] == "heuristic"
    assert result["normalization"]["llmParseUsed"] is False
    assert len(result["steps"]) == 2
    assert llm.called is False


def test_parser_agent_uses_llm_only_when_heuristic_has_no_steps() -> None:
    llm = _LlmWithScenario()
    agent = TestcaseParserAgent(llm_client=llm)  # type: ignore[arg-type]

    result = agent.parse_testcase("Свободное описание без явных шагов")

    assert result["source"] == "llm"
    assert result["normalization"]["llmParseUsed"] is True
    assert len(result["steps"]) == 2
    assert llm.called is True
