"""Отдельный тестовый MCP-процесс. Stdout используется только протоколом."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel


server = MCPServer("olga-stdio-test")
CASE = "mbsnu_bypass_96h"
SCHEDULE = {"event_time_s": 172800, "transition_s": 60, "end_time_s": 345600}
plans = {}
runs = {}


class TestManifest(BaseModel):
    mode: str = "test"
    schema_version: str = "0.1-test"
    case_id: str
    trace_id: str
    model_id: str = "test-model"
    model_version: str = "test-version"
    model_fingerprint: str = "test-fingerprint"
    schedule: dict[str, int]
    allowed_parameters: dict[str, bool]
    control_points: list[str]


@server.tool()
def read_case_manifest(case_id: str, trace_id: str) -> Annotated[CallToolResult, TestManifest]:
    """Вернуть тестовый манифест для проверки транспорта."""
    if case_id != CASE:
        message = "Сценарий отсутствует в тестовом манифесте."
        return CallToolResult(
            isError=True,
            content=[TextContent(type="text", text=message)],
            structuredContent={"code": "CASE_NOT_FOUND", "message": message},
        )
    manifest = TestManifest(
        case_id=case_id,
        trace_id=trace_id,
        schedule=SCHEDULE,
        allowed_parameters={},
        control_points=[],
    )
    return CallToolResult(content=[], structuredContent=manifest.model_dump(mode="json"))


@server.tool()
def report_error() -> CallToolResult:
    """Вернуть структурированную ошибку инструмента."""
    return CallToolResult(
        isError=True,
        content=[TextContent(type="text", text="Модель недоступна.")],
        structuredContent={"code": "MODEL_UNAVAILABLE", "message": "Модель недоступна."},
    )


@server.tool()
async def slow_tool() -> dict[str, bool]:
    """Задержать ответ дольше таймаута клиента."""
    await asyncio.sleep(60)
    return {"completed": True}


@server.tool()
def prepare_scenario(case_id: str, event_time_s: float, transition_s: float,
                     end_time_s: float, trace_id: str) -> dict[str, object]:
    """Подготовить неизменяемый тестовый план в текущей сессии."""
    parameters = dict(event_time_s=event_time_s, transition_s=transition_s, end_time_s=end_time_s)
    if case_id != CASE or parameters != SCHEDULE:
        raise ValueError("Сценарий или расписание отличаются от тестового манифеста.")
    plan_id = uuid4().hex
    plan = dict(
        mode="test", plan_id=plan_id, case_id=case_id, trace_id=trace_id,
        model_id="test-model", model_version="test-version", model_fingerprint="test-fingerprint",
        parameters=parameters, actions=["Открыть байпас", "Закрыть ветвь сепаратора", "Снизить Pump до нуля"],
        model_copy=f"test-copy-{plan_id}", requires_approval=True,
    )
    plans[plan_id] = plan
    return plan


@server.tool()
def start_run(plan_id: str, approval_token: str, trace_id: str) -> dict[str, str]:
    """Запустить тестовый план один раз после подтверждения."""
    plan = plans[plan_id]
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    if plan["trace_id"] != trace_id or hashlib.sha256(canonical.encode()).hexdigest() != approval_token:
        raise ValueError("План или подтверждение не совпадает.")
    run_id = f"test-{plan_id}"
    state = runs.setdefault(run_id, {"status": "QUEUED", "trace_id": trace_id, "polls": 0})
    return {"run_id": run_id, "status": state["status"]}


@server.tool()
def get_run_status(run_id: str, trace_id: str) -> dict[str, str]:
    """Вернуть очередное состояние синтетического запуска."""
    state = runs[run_id]
    if state["trace_id"] != trace_id:
        raise ValueError("Чужой запуск.")
    state["polls"] += 1
    status = "RUNNING"
    if state["polls"] >= 2:
        status = {"success": "SUCCEEDED", "stuck": "RUNNING", "failed": "FAILED",
                  "cancelled": "CANCELLED"}[options.outcome]
    state["status"] = status
    result = {"run_id": run_id, "status": status}
    if status in {"FAILED", "CANCELLED"}:
        result["error"] = "Тестовый исход, заданный при запуске."
    return result


def write_plot(path, times, series, unit):
    colors = ("#175fba", "#c54723", "#338458", "#71358b")
    limit = max(v for values in series.values() for v in values) * 1.1
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="640" height="270" viewBox="0 0 640 270">',
           '<rect width="640" height="270" fill="white"/>',
           f'<text x="15" y="24">TEST MODE · {unit}</text>',
           '<path d="M55 40 V200 H600" fill="none" stroke="#444"/>',
           '<text x="45" y="220">0</text><text x="311" y="220">48</text><text x="575" y="220">96 ч</text>',
           f'<text x="8" y="48">{limit:.1f}</text><text x="35" y="205">0</text>']
    for index, (name, values) in enumerate(series.items()):
        points = " ".join(f"{55 + t / 345600 * 545:.2f},{200 - v / limit * 160:.2f}"
                          for t, v in zip(times, values, strict=True))
        color = colors[index]
        svg.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
        svg.append(f'<text x="{50 + index * 145}" y="250" fill="{color}">{name}</text>')
    path.write_text("\n".join([*svg, "</svg>"]), encoding="utf-8")


@server.tool()
def read_run_results(run_id: str, trace_id: str) -> dict[str, object]:
    """Вернуть явно синтетические ряды и графики завершённого тестового запуска."""
    state = runs[run_id]
    if state["trace_id"] != trace_id or state["status"] != "SUCCEEDED":
        raise ValueError("Нет завершённого запуска для данного запроса.")
    folder = options.artifacts / run_id
    folder.mkdir(parents=True, exist_ok=True)
    times = [0, 172800, 172860, 345600]
    flows = {"Байпас": [0, 0, 12, 12], "Сепаратор": [12, 12, 0, 0],
             "Pump": [12, 12, 0, 0], "АГЗУ-2": [12, 12, 12, 12]}
    pressures = {"АГЗУ-2": [8, 8, 9, 8.2]}
    source = folder / "synthetic.json"
    source.write_text(json.dumps({"mode": "test", "time_s": times, "flow_kg_s": flows,
                                  "pressure_bara": pressures}, ensure_ascii=False), encoding="utf-8")
    metrics = []
    plots = {}
    for name, series, unit in (("Расход", flows, "кг/с"), ("Давление", pressures, "bara")):
        path = folder / ("flow.svg" if name == "Расход" else "pressure.svg")
        write_plot(path, times, series, unit)
        plots[name] = str(path)
        for point, values in series.items():
            for window, value in (("до события", values[0]), ("в конце расчёта", values[-1])):
                metrics.append(dict(name=f"{name} {window}", location_id=point, value=value,
                                    unit=unit, source=str(source)))
    return dict(mode="test", case_id=CASE, run_id=run_id, metrics=metrics,
                assessment="NOT_ASSESSED", assessment_reason="Для тестовых данных допуски не заданы.", plots=plots)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pid_file", type=Path)
    parser.add_argument("--outcome", choices=("success", "stuck", "failed", "cancelled"), default="success")
    parser.add_argument("--artifacts", type=Path)
    options = parser.parse_args()
    options.pid_file.write_text(str(os.getpid()), encoding="utf-8")
    if options.artifacts is None:
        options.artifacts = options.pid_file.parent
    server.run(transport="stdio")
