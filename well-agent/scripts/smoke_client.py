"""Технический MCP-клиент БЕЗ LLM для проверки сервера OLGA (контрольная точка участника 2).

Цепочка: initialize -> list_tools -> read_case_manifest -> prepare_scenario ->
подтверждение человеком в консоли -> start_run -> get_run_status (опрос) -> read_run_results.

Запуск из каталога well-agent/:
    Windows:  .\\.venv\\Scripts\\python.exe -m scripts.smoke_client
    macOS:    .venv/bin/python -m scripts.smoke_client

Ключи:
    --negative       отправить начало переключения -3600 с (ожидается INVALID_INPUT, без start_run)
    --plan-only      остановиться после prepare_scenario
    --poll S         интервал опроса статуса, с (по умолчанию 10)
    --deadline S     предельное время ожидания клиента, с (по умолчанию 3600)

Сервер получает переменные OLGA_* и FAKE_OLGA_* из окружения этого процесса.
Секрет OLGA_APPROVAL_SECRET используется только здесь, чтобы выдать токен после «да».
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import anyio

WELL_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(WELL_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(WELL_AGENT_DIR))

from mcp import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402

from mcp_server.approval import make_approval_token  # noqa: E402

CASE_ID = "mbsnu_bypass_96h"
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


# SDK MCP передаёт серверу только короткий список системных переменных (на Windows: PATH,
# SYSTEMROOT, TEMP и т. п.). OLGA может требовать переменные лицензии и системные пути,
# поэтому их передаём явно. Дополнительные имена: OLGA_PASSTHROUGH_ENV="ИМЯ1,ИМЯ2".
SYSTEM_PASSTHROUGH = (
    "COMPUTERNAME", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
    "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "WINDIR", "NUMBER_OF_PROCESSORS", "USERDOMAIN",
)


def server_env() -> dict[str, str]:
    extra = {n.strip().upper() for n in os.environ.get("OLGA_PASSTHROUGH_ENV", "").split(",") if n.strip()}
    env = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if (
            upper.startswith(("OLGA_", "FAKE_OLGA_"))
            or upper in SYSTEM_PASSTHROUGH
            or upper in extra
            or "LICENSE" in upper
        ):
            env[key] = value
    return env


def server_params() -> StdioServerParameters:
    env = server_env()
    return StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(WELL_AGENT_DIR), env=env
    )


def show(title: str, data: Any) -> None:
    print(f"\n=== {title}")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])


async def call(client: Client, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    args = {**args, "call_id": f"cli_{uuid.uuid4().hex[:8]}"}
    result = await client.call_tool(tool, args)
    if result.is_error or result.structured_content is None:
        text = result.content[0].text if result.content else ""
        raise RuntimeError(f"{tool}: ошибка протокола MCP: {text[:500]}")
    return result.structured_content


async def main(ns: argparse.Namespace) -> int:
    trace_id = f"smoke-{uuid.uuid4().hex[:12]}"
    print(f"trace_id = {trace_id}")
    async with Client(server_params(), read_timeout_seconds=120) as client:
        tools = await client.list_tools()
        print("Инструменты сервера:", [t.name for t in tools.tools])

        status = await call(client, "get_server_status", {"trace_id": trace_id})
        show("get_server_status", status)
        print(f"\nРЕЖИМ АДАПТЕРА: {status['adapter_mode'].upper()}")

        manifest = await call(client, "read_case_manifest", {"case_id": CASE_ID, "trace_id": trace_id})
        show("read_case_manifest (кратко)", {
            "ok": manifest["ok"], "model_fingerprint": manifest.get("model_fingerprint"),
            "kit": manifest.get("kit", {}).get("status"), "error": manifest.get("error"),
            "schedule": manifest.get("manifest", {}).get("schedule"),
        })
        if not manifest["ok"]:
            return 1
        sched = manifest["manifest"]["schedule"]
        event = -3600 if ns.negative else sched["event_time_s"]

        plan = await call(client, "prepare_scenario", {
            "case_id": CASE_ID, "event_time_s": event, "transition_s": sched["transition_s"],
            "end_time_s": sched["end_time_s"], "trace_id": trace_id,
        })
        show("prepare_scenario", plan)
        if not plan["ok"]:
            print("\nПлан отклонён сервером; start_run НЕ вызывается.")
            return 0 if ns.negative else 1
        if ns.plan_only:
            return 0

        answer = input("\nЗапустить OLGA по этому плану? Введите 'да' для подтверждения: ")  # ввод подтверждения человеком; LLM в этом шаге не участвует
        if answer.strip().lower() not in {"да", "yes", "y"}:
            print("Подтверждение не получено. Запуск не выполняется.")
            return 0
        secret = os.environ.get("OLGA_APPROVAL_SECRET", "")
        token = make_approval_token(secret, plan["plan_id"], plan["model_fingerprint"], trace_id)

        run = await call(client, "start_run", {"plan_id": plan["plan_id"], "approval_token": token, "trace_id": trace_id})
        show("start_run", run)
        if not run["ok"]:
            return 1
        run_id = run["run_id"]

        deadline = time.monotonic() + ns.deadline
        state = run["state"]
        while state not in TERMINAL:
            if time.monotonic() > deadline:
                print(f"\nСрок ожидания клиента истёк. Расчёт НЕ отменён. run_id = {run_id}")
                return 2
            await anyio.sleep(ns.poll)
            st = await call(client, "get_run_status", {"run_id": run_id, "trace_id": trace_id})
            state = st.get("state", "UNKNOWN")
            if state in TERMINAL:
                print(f"[{time.strftime('%H:%M:%S')}] {run_id}: {state}")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] {run_id}: {state}, прошло {st.get('elapsed_s')} с — расчёт выполняется")
        show("get_run_status (финальный)", st)
        if state != "SUCCEEDED":
            return 1

        res = await call(client, "read_run_results", {"run_id": run_id, "trace_id": trace_id})
        show("read_run_results", {k: res.get(k) for k in ("ok", "statuses", "run", "assessment", "artifacts", "error")})
        print(f"\ntrace_id = {trace_id}\nrun_id   = {run_id}\nЖурнал сервера: logs/server.jsonl")
        return 0 if res["ok"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--negative", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--poll", type=float, default=10.0)
    parser.add_argument("--deadline", type=float, default=3600.0)
    sys.exit(anyio.run(main, parser.parse_args()))
