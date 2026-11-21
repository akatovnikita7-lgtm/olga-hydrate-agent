import asyncio
import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.demo import run_one
from src.agent import loop
from src.agent.journal import Journal
from src.agent.schemas import BenchContext, RequestIntent
from src.agent.tools import McpGatewayError, McpToolGateway


def events(folder):
    [path] = list(folder.glob("*.jsonl"))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert {row["trace_id"] for row in rows} == {path.stem}
    return rows


@pytest.mark.parametrize(
    ("decision", "outcome", "expected"),
    [("да", "success", "ok"), ("нет", "success", "refused"), (None, "success", "refused"),
     ("да", "stuck", "timeout"), ("да", "failed", "failed"), ("да", "cancelled", "cancelled")],
)
def test_demo_decision_controls_run(tmp_path, monkeypatch, decision, outcome, expected):
    parse = Mock(return_value=RequestIntent(
        action="simulate_bypass", case_id=None, event_time=None, transition_duration=None,
        end_time=None, requested_outputs=[],
    ))
    monkeypatch.setattr(loop, "parse_request", parse)
    context = BenchContext(llm_model="test", llm_base_url="https://example.invalid", llm_api_key="secret-test-key")
    args = Namespace(test_mcp=True, test_outcome=outcome, log_dir=tmp_path,
                     poll_interval=0.01, timeout=0.3 if outcome == "stuck" else 10)
    output = []
    ask = Mock(side_effect=EOFError()) if decision is None else Mock(return_value=decision)

    assert run_one("Запусти обход МБСНУ.", context, args, ask, output.append) == expected
    parse.assert_called_once()
    ask.assert_called_once()
    rows = events(tmp_path)
    calls = [row for row in rows if row["component"] == "mcp" and row["event"] == "call"]
    names = [row["tool"] for row in calls]
    assert names[:2] == ["read_case_manifest", "prepare_scenario"]
    [approval] = [row for row in rows if row["event"] == "approval_decision"]
    assert approval["approved"] == (decision == "да")
    assert approval["plan_id"] and approval["model_fingerprint"]
    assert rows[-1]["status"] == expected
    if expected == "refused":
        assert names == ["read_case_manifest", "prepare_scenario"]
        return
    assert names.count("start_run") == 1
    assert calls[2]["arguments"]["approval_token"] == "[скрыто]"
    assert rows[-1]["run_id"]
    assert ("read_run_results" in names) == (expected == "ok")
    if expected == "timeout":
        timeout = next(row for row in rows if row["event"] == "wait_timeout")
        assert timeout["last_status"] in {"QUEUED", "RUNNING"}
    if expected == "ok":
        result = next(row for row in rows if row["event"] == "results_read")
        assert result["assessment"] == "NOT_ASSESSED"
        assert all(Path(path).is_file() for path in result["plots"].values())
        assert any("Давление в конце расчёта | АГЗУ-2 | 8.2 | bara" in line for line in output)


def test_jsonl_redacts_nested_secrets_and_failure(tmp_path):
    log = Journal(tmp_path, "configured-secret")
    with pytest.raises(RuntimeError):
        with log.call("mcp", "start_run", {"headers": {"Authorization": "Basic hidden-header"},
                                         "approval_token": "hidden-token", "text": "configured-secret"}):
            raise RuntimeError("Authorization: Bearer hidden-error; api_key=hidden-key")
    contents = log.path.read_text()
    for secret in ("configured-secret", "hidden-header", "hidden-token", "hidden-error", "hidden-key"):
        assert secret not in contents
    call, response = events(tmp_path)
    assert call["call_id"] == response["call_id"]
    assert response["duration_ms"] >= 0


def test_fixture_checks_approval_and_reuses_run(tmp_path):
    import hashlib

    async def check():
        gateway = McpToolGateway(server_args=["tests/fixtures/mcp_stdio_server.py", str(tmp_path / "pid")])
        async with gateway.session() as session:
            plan = await session.call_tool("prepare_scenario", dict(case_id="mbsnu_bypass_96h",
                event_time_s=172800, transition_s=60, end_time_s=345600, trace_id="a"))
            def token(data):
                return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            args = dict(plan_id=plan["plan_id"], approval_token=token(plan), trace_id="a")
            for change in ({"trace_id": "b"}, {"approval_token": token(dict(plan, model_version="other"))}):
                with pytest.raises(McpGatewayError):
                    await session.call_tool("start_run", args | change)
            first = await session.call_tool("start_run", args)
            assert first == await session.call_tool("start_run", args)
    asyncio.run(check())


def test_cli_logs_refusal_before_mcp(tmp_path, monkeypatch):
    from src.agent.schemas import RequestedTime

    intent = RequestIntent(
        action="simulate_bypass", case_id=None, event_time=RequestedTime(value=-1, unit="h"),
        transition_duration=None, end_time=None, requested_outputs=[],
    )
    monkeypatch.setattr(loop, "parse_request", Mock(return_value=intent))
    context = BenchContext(llm_model="test", llm_base_url="https://example.invalid", llm_api_key="key-test")
    args = Namespace(test_mcp=True, test_outcome="success", log_dir=tmp_path)
    ask = Mock(side_effect=AssertionError("Неожиданное подтверждение"))
    assert run_one("Начни переключение через минус один час", context, args, ask, lambda text: None) == "refused"
    rows = events(tmp_path)
    [check] = [row for row in rows if row["event"] == "validation"]
    assert check["rejection"]["field"] == "event_time_s"
    assert not any(row["component"] == "mcp" for row in rows)
    ask.assert_not_called()
