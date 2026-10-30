from agent import run
from src.agent.schemas import AgentResult, BenchContext


def test_entrypoint_returns_agent_result() -> None:
    context = BenchContext(
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        llm_model="test-model",
    )

    result = run("Рассчитай режим скважины", context)

    assert isinstance(result, AgentResult)
    assert result.status == "refused"


def test_empty_request_is_refused() -> None:
    context = BenchContext(
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        llm_model="test-model",
    )

    result = run("   ", context)

    assert result.status == "refused"
    assert "пустым" in result.answer
