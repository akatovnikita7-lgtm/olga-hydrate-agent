"""Структурированные ошибки сервера (формат из командного контракта, стр. 8)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Коды из руководства команды + уточнения адаптера. Описания — в docs/olga_adapter.md.
ERROR_CODES = {
    "INVALID_INPUT": False,
    "UNIT_AMBIGUOUS": False,
    "UNSUPPORTED_SCENARIO_PARAMETER": False,
    "APPROVAL_REQUIRED": False,
    "PLAN_NOT_FOUND": False,
    "PLAN_EXPIRED": False,
    "FINGERPRINT_MISMATCH": False,
    "MODEL_SCHEDULE_MISMATCH": False,
    "CASE_KIT_INVALID": False,
    "SIMULATOR_UNAVAILABLE": True,
    "RUN_LIMIT_REACHED": True,
    "LICENSE_BUSY": True,
    "TIMEOUT": True,
    "NO_SOLUTION": False,
    "SIMULATION_FAILED": False,
    "INCOMPLETE_RESULT": False,
    "RESULT_PARSE_ERROR": False,
    "RUN_NOT_FOUND": False,
    "RUN_NOT_FINISHED": True,
    "INTERNAL_ERROR": False,
}


@dataclass(slots=True)
class ToolFailure(Exception):
    """Ожидаемая ошибка инструмента; превращается в поле ``error`` ответа."""

    code: str
    message: str
    field: str | None = None
    received_value: Any = None
    expected_rule: str | None = None
    retryable: bool | None = None

    def __post_init__(self) -> None:
        if self.code not in ERROR_CODES:
            raise ValueError(f"неизвестный код ошибки {self.code}")
        if self.retryable is None:
            self.retryable = ERROR_CODES[self.code]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "received_value": _jsonable(self.received_value),
            "expected_rule": self.expected_rule,
            "retryable": self.retryable,
        }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and value != value:  # NaN
            return "NaN"
        if isinstance(value, float) and value in (float("inf"), float("-inf")):
            return str(value)
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return repr(value)
