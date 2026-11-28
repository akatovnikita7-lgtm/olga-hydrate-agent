import pytest

from agent import run
from src.agent import loop
from src.agent.schemas import AgentResult, BenchContext, RequestIntent


def test_entrypoint_returns_agent_result(monkeypatch: pytest.MonkeyPatch) -> None:
    context = BenchContext(
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        llm_model="test-model",
    )

    intent = RequestIntent(
        action="unsupported", case_id=None, event_time=None, transition_duration=None,
        end_time=None, requested_outputs=[],
    )
    monkeypatch.setattr(loop, "parse_request", lambda request, context: intent)
    result = run("Рассчитай режим скважины", context)

    assert isinstance(result, AgentResult)
    assert result.status == "refused"
    assert result.rejection is not None
    assert result.rejection.code == "UNSUPPORTED_ACTION"


def test_empty_request_is_refused() -> None:
    context = BenchContext(
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        llm_model="test-model",
    )

    result = run("   ", context)

    assert result.status == "refused"
    assert "пустым" in result.answer
