import asyncio
import os
from pathlib import Path

import pytest

from agent import run
from src.agent.schemas import BenchContext
from src.agent.tools import McpGatewayError, McpToolGateway


_FIXTURE = "tests/fixtures/mcp_stdio_server.py"
_MANIFEST_ARGS = {"case_id": "mbsnu_bypass_96h", "trace_id": "stdio-test"}


def assert_process_closed(pid_file: Path) -> None:
    pid = int(pid_file.read_text(encoding="utf-8"))
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_stdio_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pid_file = tmp_path / "server.pid"
    gateway = McpToolGateway(server_args=[_FIXTURE, str(pid_file)])
    monkeypatch.chdir(tmp_path)  # The relative fixture path resolves from well-agent.

    async def check_manifest() -> None:
        async with gateway.session() as session:
            tools = await session.list_tools()
            manifest_tool = next(tool for tool in tools if tool["name"] == "read_case_manifest")
            assert set(manifest_tool["inputSchema"]["required"]) == {"case_id", "trace_id"}
            assert manifest_tool["outputSchema"]["type"] == "object"
            result = await session.call_tool("read_case_manifest", _MANIFEST_ARGS)
            assert result["mode"] == "test"
            assert result["case_id"] == _MANIFEST_ARGS["case_id"]
            assert result["trace_id"] == _MANIFEST_ARGS["trace_id"]
            assert result["schedule"] == {
                "event_time_s": 172800,
                "transition_s": 60,
                "end_time_s": 345600,
            }
            print(f"TEST MODE · stdio · read_case_manifest = {result}")

    asyncio.run(check_manifest())
    assert_process_closed(pid_file)


def test_sync_gateway_inside_running_event_loop(tmp_path: Path) -> None:
    pid_file = tmp_path / "server.pid"
    gateway = McpToolGateway(server_args=[_FIXTURE, str(pid_file)])

    async def call_from_running_loop() -> None:
        assert gateway.call_tool("read_case_manifest", _MANIFEST_ARGS)["mode"] == "test"

    asyncio.run(call_from_running_loop())
    assert_process_closed(pid_file)


def test_stdio_structured_tool_error(tmp_path: Path) -> None:
    pid_file = tmp_path / "server.pid"
    gateway = McpToolGateway(server_args=[_FIXTURE, str(pid_file)])

    with pytest.raises(McpGatewayError, match="Модель недоступна") as failure:
        gateway.call_tool("report_error", {})

    assert failure.value.code == "MODEL_UNAVAILABLE"
    assert_process_closed(pid_file)


def test_stdio_call_timeout_closes_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "server.pid"
    gateway = McpToolGateway(server_args=[_FIXTURE, str(pid_file)], timeout_s=10)

    with pytest.raises(McpGatewayError, match="tools/call") as failure:
        gateway.call_tool("slow_tool", {})

    assert failure.value.code == "MCP_TIMEOUT"
    assert_process_closed(pid_file)


def test_default_stdio_command_uses_project_server(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = McpToolGateway()
    monkeypatch.setenv("SIMULATOR_NAME", "OLGA")

    tools = {tool["name"] for tool in gateway.list_tools()}
    assert {"get_simulator_status", "run_simulation"} <= tools
    assert gateway.call_tool("get_simulator_status", {})["simulator"] == "OLGA"


def test_entrypoint_reports_stdio_connection_error() -> None:
    context = BenchContext(
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        llm_model="test-model",
        mcp_server_args=("-m", "missing_mcp_server_for_test"),
    )

    result = run("Проверь соединение", context)

    assert result.status == "error"
    assert "Не удалось подключиться к MCP" in result.answer
    assert result.values == []
