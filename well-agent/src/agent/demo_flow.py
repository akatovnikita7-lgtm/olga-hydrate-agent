"""Продолжение проверенного запроса по черновику контракта тестового MCP."""
import asyncio
import hashlib
import json
from collections.abc import Callable
from time import monotonic
from typing import Literal

from anyio import fail_after
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError

from .journal import Journal
from .schemas import ScenarioSchedule, ValidatedRequest
from .tools import McpGatewayError, McpToolSession


class TestPlan(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    mode: Literal["test"]
    plan_id: str = Field(min_length=1)
    case_id: str
    trace_id: str
    model_id: str
    model_version: str
    model_fingerprint: str
    parameters: ScenarioSchedule
    actions: list[str] = Field(min_length=1)
    copy_name: str = Field(alias="model_copy")
    requires_approval: Literal[True]


class RunStatus(BaseModel):
    run_id: str = Field(min_length=1)
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
    error: str | None = None


class Metric(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str
    location_id: str
    value: FiniteFloat | None
    unit: str
    source: str
    reason: str | None = None


class TestResults(BaseModel):
    mode: Literal["test"]
    run_id: str
    case_id: str
    metrics: list[Metric]
    assessment: Literal["OK", "OUT_OF_TOLERANCE", "NOT_ASSESSED"]
    assessment_reason: str
    plots: dict[str, str]


async def run_test_plan(
    session: McpToolSession, request: ValidatedRequest, journal: Journal,
    ask: Callable[[str], str], show: Callable[[str], None],
    poll_interval: float, timeout: float,
) -> str:
    """Показать проверенный план, получить решение и дождаться тестового результата."""
    async def call(name, arguments, schema):
        arguments = {**arguments, "trace_id": journal.trace_id}
        with journal.call("mcp", name, arguments) as response:
            raw = await session.call_tool(name, arguments, check_schema=True)
            try:
                parsed = schema.model_validate(raw)
            except ValidationError:
                raise McpGatewayError("INVALID_RESPONSE", f"Неверный формат ответа {name}.") from None
            response["result"] = parsed
        return parsed

    plan = await call("prepare_scenario", {"case_id": request.case_id, **request.schedule.model_dump()}, TestPlan)
    if (plan.trace_id != journal.trace_id or plan.case_id != request.case_id
            or plan.model_fingerprint != request.model_fingerprint or plan.parameters != request.schedule):
        raise McpGatewayError("PLAN_MISMATCH", "План отличается от проверенного запроса.")

    journal.plan_id = plan.plan_id
    journal.write("needs_approval", plan=plan)
    show(f"TEST MODE · План {plan.plan_id}\nМодель {plan.model_id} ({plan.model_version}), "
         f"fingerprint {plan.model_fingerprint}\nКопия {plan.copy_name}")
    show(f"Начало переключения {plan.parameters.event_time_s / 3600:g} ч, "
         f"длительность {plan.parameters.transition_s:g} с, конец расчёта {plan.parameters.end_time_s / 3600:g} ч.")
    for action in plan.actions:
        show(f"  • {action}")
    try:
        approved = ask("Запустить этот тестовый план? [да/нет] ").strip().casefold() in {"да", "yes"}
    except (EOFError, KeyboardInterrupt):
        approved = False
    journal.write("approval_decision", approved=approved, model_fingerprint=plan.model_fingerprint)
    if not approved:
        show("Запуск отклонён.")
        return "refused"

    # Демонстрационное подтверждение привязано ко всему показанному плану.
    canonical = json.dumps(plan.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
    token = hashlib.sha256(canonical.encode()).hexdigest()
    journal.secrets.add(token)
    state = await call("start_run", {"plan_id": plan.plan_id, "approval_token": token}, RunStatus)
    journal.run_id = state.run_id
    deadline = monotonic() + timeout
    while True:
        journal.write("run_status", status=state.status, error=state.error)
        show(f"Расчёт {state.run_id} — {state.status}")
        if state.status == "SUCCEEDED":
            break
        if state.status in {"FAILED", "CANCELLED"}:
            show(state.error or "Сервер не передал подробности.")
            return state.status.lower()
        try:
            with fail_after(max(0.0, deadline - monotonic())):
                await asyncio.sleep(poll_interval)
                next_state = await call("get_run_status", {"run_id": state.run_id}, RunStatus)
        except (TimeoutError, McpGatewayError) as error:
            if isinstance(error, McpGatewayError) and error.code != "MCP_TIMEOUT":
                raise
            show(f"Истёк срок ожидания. run_id={state.run_id}, последний статус {state.status}.")
            journal.write("wait_timeout", last_status=state.status)
            return "timeout"
        if next_state.run_id != journal.run_id:
            raise McpGatewayError("RUN_MISMATCH", "Сервер вернул статус другого запуска.")
        state = next_state

    result = await call("read_run_results", {"run_id": state.run_id}, TestResults)
    if result.run_id != state.run_id or result.case_id != request.case_id:
        raise McpGatewayError("RESULT_MISMATCH", "Сервер вернул результат другого запуска.")
    show("Результаты прочитаны · синтетические данные\nПоказатель | Точка | Значение | Единица | Источник")
    for metric in result.metrics:
        value = f"{metric.value:g}" if metric.value is not None else f"нет данных ({metric.reason or 'причина не указана'})"
        show(f"{metric.name} | {metric.location_id} | {value} | {metric.unit} | {metric.source}")
    show(f"Инженерная оценка {result.assessment}. {result.assessment_reason}")
    for label, path in result.plots.items():
        show(f"График {label} — {path}")
    journal.write("results_read", assessment=result.assessment, plots=result.plots)
    return "ok"
