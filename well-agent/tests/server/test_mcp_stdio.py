"""Проверка настоящего MCP-транспорта stdio: клиент сам запускает процесс сервера.

Режим адаптера — fake (явно). Это проверка MCP, а не OLGA.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from .conftest import FAKE_OLGA, WELL_AGENT

EXPECTED_TOOLS = {
    "get_server_status", "read_case_manifest", "prepare_scenario",
    "start_run", "get_run_status", "read_run_results",
}


def test_stdio_server_tools_and_server_side_validation(kit: Path, tmp_path: Path) -> None:
    env = {
        "OLGA_ADAPTER_MODE": "fake",
        "OLGA_CASE_KIT_DIR": str(kit),
        "OLGA_LAUNCHER": sys.executable,
        "OLGA_LAUNCHER_ARGS": json.dumps([str(FAKE_OLGA), "{input}"]),
        "OLGA_RUNS_ROOT": str(tmp_path / "runs"),
        "OLGA_LOG_DIR": str(tmp_path / "logs"),
        "OLGA_APPROVAL_SECRET": "stdio-secret",
    }
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(WELL_AGENT), env=env)

    async def scenario() -> None:
        async with Client(params, read_timeout_seconds=60) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert EXPECTED_TOOLS <= names
            assert "run_simulation" not in names  # произвольного запуска нет

            man = (await client.call_tool("read_case_manifest", {"case_id": "mbsnu_bypass_96h", "trace_id": "s1"})).structured_content
            assert man["ok"] and man["adapter_mode"] == "fake" and man["kit"]["status"] == "ok"

            neg = (await client.call_tool("prepare_scenario", {
                "case_id": "mbsnu_bypass_96h", "event_time_s": -3600, "transition_s": 60,
                "end_time_s": 345600, "trace_id": "s1",
            })).structured_content
            assert neg["ok"] is False and neg["error"]["code"] == "INVALID_INPUT"

            plan = (await client.call_tool("prepare_scenario", {
                "case_id": "mbsnu_bypass_96h", "event_time_s": 172800, "transition_s": 60,
                "end_time_s": 345600, "trace_id": "s1",
            })).structured_content
            assert plan["ok"] and plan["requires_approval"]

            denied = (await client.call_tool("start_run", {
                "plan_id": plan["plan_id"], "approval_token": "llm-made-this-up", "trace_id": "s1",
            })).structured_content
            assert denied["error"]["code"] == "APPROVAL_REQUIRED"

    anyio.run(scenario)
    assert not list((tmp_path / "runs").glob("run_*"))
    log = (tmp_path / "logs" / "server.jsonl").read_text(encoding="utf-8")
    assert "process_started" not in log
