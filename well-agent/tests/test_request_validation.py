from pathlib import Path
from unittest.mock import Mock

import pytest

from agent import run
from src.agent import loop
from src.agent.llm import LlmError
from src.agent.schemas import BenchContext, RequestedTime, RequestIntent
from src.agent.tools import McpGatewayError, McpToolGateway


CASE_ID = "mbsnu_bypass_96h"
FIXTURE = "tests/fixtures/mcp_stdio_server.py"


def make_intent(
    event: tuple[float, str | None] | None = None,
    duration: tuple[float, str | None] | None = None,
    end: tuple[float, str | None] | None = None,
    case_id: str | None = None,
) -> RequestIntent:
    def time(pair: tuple[float, str | None] | None) -> RequestedTime | None:
        return RequestedTime(value=pair[0], unit=pair[1]) if pair is not None else None

    return RequestIntent(
        action="simulate_bypass", case_id=case_id, event_time=time(event),
        transition_duration=time(duration), end_time=time(end), requested_outputs=[],
    )


@pytest.fixture
def context(tmp_path: Path) -> BenchContext:
    return BenchContext(
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        llm_model="test-model",
        mcp_case_id=CASE_ID,
        mcp_server_args=(FIXTURE, str(tmp_path / "server.pid")),
    )


@pytest.mark.parametrize(
    ("intent", "sources"),
    [
        (make_intent((48, "h"), (60, "s"), (96, "h")), ("request", "request", "request")),
        (make_intent((2, "d"), (1, "min"), (4, "d")), ("request", "request", "request")),
        (make_intent(duration=(1, "min")), ("manifest", "request", "manifest")),
    ],
)
def test_entrypoint_validates_schedule_through_stdio(
    monkeypatch: pytest.MonkeyPatch, context: BenchContext,
    intent: RequestIntent, sources: tuple[str, str, str],
) -> None:
    monkeypatch.setattr(loop, "parse_request", Mock(return_value=intent))

    result = run("Запусти подготовленный обход МБСНУ.", context)

    assert result.status == "ok", result.answer
    assert result.answer.startswith("TEST MODE.")
    assert result.validated_request is not None
    assert result.validated_request.schedule.model_dump() == {
        "event_time_s": 172800, "transition_s": 60, "end_time_s": 345600,
    }
    assert result.validated_request.parameter_sources == dict(
        zip(("event_time_s", "transition_s", "end_time_s"), sources, strict=True)
    )
    assert [call.tool for call in result.trace] == ["read_case_manifest"]
    assert result.trace[0].arguments["trace_id"] == result.trace_id
    assert result.values == []


@pytest.mark.parametrize(
    ("intent", "field", "code"),
    [
        (make_intent((-1, "h")), "event_time_s", "INVALID_INPUT"),
        (make_intent((1, None)), "event_time_s", "INVALID_UNIT"),
        (make_intent((1, "неделя")), "event_time_s", "INVALID_UNIT"),
        (make_intent(duration=(0, "s")), "transition_s", "INVALID_INPUT"),
        (make_intent((2, "s"), (1, "s"), (3, "s")), "end_time_s", "INVALID_INPUT"),
        (make_intent((1e308, "d")), "event_time_s", "INVALID_INPUT"),
        (make_intent(case_id="another_case"), "case_id", "UNSUPPORTED_SCENARIO"),
    ],
)
def test_entrypoint_refuses_invalid_input_before_mcp(
    monkeypatch: pytest.MonkeyPatch, context: BenchContext,
    intent: RequestIntent, field: str, code: str,
) -> None:
    monkeypatch.setattr(loop, "parse_request", Mock(return_value=intent))
    call_tool = Mock()
    monkeypatch.setattr(McpToolGateway, "call_tool", call_tool)

    result = run("Запусти расчёт.", context)

    assert result.status == "refused"
    assert result.rejection is not None
    assert (result.rejection.field, result.rejection.code) == (field, code)
    assert result.rejection.received_value is not None
    assert result.trace_id
    assert result.values == result.trace == []
    call_tool.assert_not_called()


def test_entrypoint_refuses_deviation_from_fixed_schedule(
    monkeypatch: pytest.MonkeyPatch, context: BenchContext,
) -> None:
    monkeypatch.setattr(loop, "parse_request", Mock(return_value=make_intent((47, "h"))))

    result = run("Начни переключение на 47-м часу.", context)

    assert result.status == "refused"
    assert result.rejection is not None
    assert result.rejection.code == "UNSUPPORTED_SCENARIO_PARAMETER"
    assert result.rejection.received_value == {"value": 169200, "unit": "s"}
    assert [call.tool for call in result.trace] == ["read_case_manifest"]
    assert result.values == []


def test_missing_case_without_configuration_requires_clarification(
    monkeypatch: pytest.MonkeyPatch, context: BenchContext,
) -> None:
    monkeypatch.setattr(loop, "parse_request", Mock(return_value=make_intent()))

    result = run("Запусти подготовленный сценарий.", context.model_copy(update={"mcp_case_id": None}))

    assert result.status == "refused"
    assert result.rejection is not None
    assert (result.rejection.field, result.rejection.code) == ("case_id", "CLARIFICATION_REQUIRED")
    assert result.trace == []


def test_entrypoint_reports_llm_error(monkeypatch: pytest.MonkeyPatch, context: BenchContext) -> None:
    monkeypatch.setattr(loop, "parse_request", Mock(side_effect=LlmError("Модель недоступна.")))

    result = run("Запусти обход МБСНУ.", context)

    assert result.status == "error"
    assert "Модель недоступна" in result.answer
    assert result.trace == []


def test_gateway_rejects_incompatible_advertised_schema(context: BenchContext) -> None:
    gateway = McpToolGateway(server_args=context.mcp_server_args)

    with pytest.raises(McpGatewayError) as failure:
        gateway.call_tool("read_case_manifest", {"case_id": 42, "trace_id": "test"}, check_schema=True)

    assert failure.value.code == "INCOMPATIBLE_MCP_SCHEMA"
