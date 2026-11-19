"""Проверка запроса и заполнение расписания из манифеста."""

from math import isfinite
from typing import Any, Literal

from .schemas import (
    CaseManifest,
    RequestIntent,
    RequestRejection,
    ScenarioSchedule,
    ValidatedRequest,
)


_SECONDS_PER_UNIT = {"s": 1, "min": 60, "h": 3600, "d": 86400}


class RequestRefused(ValueError):
    def __init__(self, code: str, field: str, reason: str, received: Any = None) -> None:
        self.rejection = RequestRejection(
            code=code, field=field, reason=reason, received_value=received
        )
        message = f"{code}. Поле {field}. {reason}"
        if received is not None:
            message += f" Получено {received}."
        super().__init__(message)


class ManifestError(ValueError):
    """Сервер вернул данные, которые клиент не может использовать."""


def select_case(intent: RequestIntent, configured_case: str | None) -> str:
    if intent.action == "unsupported":
        raise RequestRefused("UNSUPPORTED_ACTION", "action", "Поддерживается сценарий обхода МБСНУ.")
    if intent.action == "unclear":
        raise RequestRefused("CLARIFICATION_REQUIRED", "action", "Уточните, какой расчёт нужен.")

    explicit_case = intent.case_id
    if explicit_case is not None and not explicit_case.strip():
        raise RequestRefused("CLARIFICATION_REQUIRED", "case_id", "Укажите ID сценария.", explicit_case)
    if explicit_case and configured_case and explicit_case != configured_case:
        raise RequestRefused(
            "UNSUPPORTED_SCENARIO", "case_id", f"Настроен сценарий {configured_case}.", explicit_case
        )
    case_id = explicit_case or configured_case
    if not case_id or not case_id.strip():
        raise RequestRefused("CLARIFICATION_REQUIRED", "case_id", "Укажите ID сценария.")
    return case_id


def normalize_times(intent: RequestIntent) -> dict[str, float]:
    fields = {
        "event_time_s": intent.event_time,
        "transition_s": intent.transition_duration,
        "end_time_s": intent.end_time,
    }
    seconds = {}
    for field, time in fields.items():
        if time is None:
            continue
        factor = _SECONDS_PER_UNIT.get(time.unit) if time.unit is not None else None
        received = time.model_dump()
        if factor is None:
            raise RequestRefused(
                "INVALID_UNIT", field, "Укажите однозначную единицу времени (s, min, h, d).", received
            )
        value = time.value * factor
        if not isfinite(value):
            raise RequestRefused("INVALID_INPUT", field, "Время в секундах должно быть конечным.", received)
        if field == "event_time_s" and value < 0:
            raise RequestRefused("INVALID_INPUT", field, "Начало переключения должно быть неотрицательным.", received)
        if field != "event_time_s" and value <= 0:
            raise RequestRefused("INVALID_INPUT", field, "Время должно быть больше нуля.", received)
        seconds[field] = value

    if seconds.keys() == fields.keys():
        _check_window(seconds)
    return seconds


def _check_window(seconds: dict[str, float]) -> None:
    if seconds["event_time_s"] + seconds["transition_s"] >= seconds["end_time_s"]:
        raise RequestRefused(
            "INVALID_INPUT", "end_time_s", "Конец расчёта должен быть позже конца переключения.",
            seconds["end_time_s"],
        )


def validate_manifest(manifest: CaseManifest, case_id: str, trace_id: str) -> None:
    if manifest.case_id != case_id or manifest.trace_id not in (None, trace_id):
        raise ManifestError("Манифест MCP относится к другому сценарию или запросу.")
    schedule = manifest.schedule
    if (
        schedule.event_time_s < 0
        or schedule.transition_s <= 0
        or schedule.event_time_s + schedule.transition_s >= schedule.end_time_s
    ):
        raise ManifestError("Расписание в MCP-манифесте некорректно.")


def resolve_request(
    intent: RequestIntent, explicit_times: dict[str, float], manifest: CaseManifest
) -> ValidatedRequest:
    defaults = manifest.schedule.model_dump()
    for field, value in explicit_times.items():
        if value == defaults[field]:
            continue
        if manifest.allowed_parameters.get(field) is not None and manifest.allowed_parameters[field] is not False:
            raise ManifestError(f"Правило изменения {field} в манифесте пока не поддерживается клиентом.")
        raise RequestRefused(
            "UNSUPPORTED_SCENARIO_PARAMETER", field,
            f"Манифест фиксирует значение {defaults[field]:g} с.", {"value": value, "unit": "s"},
        )

    seconds = defaults | explicit_times
    _check_window(seconds)
    sources: dict[str, Literal["request", "manifest"]] = {
        field: "request" if field in explicit_times else "manifest" for field in seconds
    }
    return ValidatedRequest(
        case_id=manifest.case_id,
        model_fingerprint=manifest.model_fingerprint,
        schedule=ScenarioSchedule.model_validate(seconds),
        parameter_sources=sources,
        requested_outputs=intent.requested_outputs,
    )
