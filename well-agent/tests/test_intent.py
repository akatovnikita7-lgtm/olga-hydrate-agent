from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai import AuthenticationError
from pydantic import ValidationError

from src.agent import llm
from src.agent.intent import parse_request
from src.agent.schemas import BenchContext, RequestIntent


def test_parser_preserves_explicit_time_and_leaves_omitted_times_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete = mock_completion(monkeypatch)
    complete.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="""{
            "action": "simulate_bypass", "case_id": null,
            "event_time": {"value": -1, "unit": "h"},
            "transition_duration": null, "end_time": null,
            "requested_outputs": [{"metric": "flow", "location": "АГЗУ-2", "presentation": "plot"}]
        }"""))],
    )
    request = "Начни переключение на обход МБСНУ через минус один час. Покажи график расхода на АГЗУ-2."

    intent = parse_request(request, context())

    assert intent.event_time is not None
    assert (intent.event_time.value, intent.event_time.unit) == (-1, "h")
    assert intent.case_id is intent.transition_duration is intent.end_time is None
    assert intent.requested_outputs[0].location == "АГЗУ-2"
    arguments = complete.call_args.kwargs
    assert arguments["messages"][-1] == {"role": "user", "content": request}
    assert arguments["response_format"]["json_schema"]["strict"] is True


@pytest.mark.parametrize("value", ["-1", True, float("inf")])
def test_time_requires_a_finite_number(value: object) -> None:
    with pytest.raises(ValidationError):
        RequestIntent.model_validate(
            {
                "action": "simulate_bypass", "case_id": None,
                "event_time": {"value": value, "unit": "h"},
                "transition_duration": None, "end_time": None, "requested_outputs": [],
            }
        )


def test_parser_rejects_unexpected_confirmation_field(monkeypatch: pytest.MonkeyPatch) -> None:
    complete = mock_completion(monkeypatch)
    complete.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="""{
            "action": "simulate_bypass", "case_id": null, "event_time": null,
            "transition_duration": null, "end_time": null, "requested_outputs": [],
            "approval_token": "unexpected-value"
        }"""))],
    )

    with pytest.raises(llm.LlmError, match="JSON Schema"):
        parse_request("Запусти подготовленный обход МБСНУ.", context())


def test_parser_reports_authentication_error_without_provider_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete = mock_completion(monkeypatch)
    complete.side_effect = AuthenticationError(
        "private test key", response=MagicMock(status_code=401), body=None
    )

    with pytest.raises(llm.LlmError, match="авторизацию") as failure:
        parse_request("Запусти подготовленный обход МБСНУ.", context())

    assert "private test key" not in str(failure.value)


def mock_completion(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock()
    monkeypatch.setattr(llm, "OpenAI", client)
    return client.return_value.__enter__.return_value.chat.completions.create


def context() -> BenchContext:
    return BenchContext(
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        llm_model="test-model",
    )
