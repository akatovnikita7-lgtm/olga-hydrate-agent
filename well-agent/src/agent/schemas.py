"""Pydantic-схемы на границе агента и бенчмарка."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat


class BenchContext(BaseModel):
    """Настройки, которые передаёт бенчмарк или демо-ноутбук."""

    llm_base_url: str
    llm_api_key: str = Field(repr=False)
    llm_model: str
    mcp_server_url: str | None = None
    mcp_server_args: tuple[str, ...] | None = None
    mcp_timeout_s: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class RequestedTime(BaseModel):
    """Число и единица из запроса до перевода в секунды."""

    model_config = ConfigDict(strict=True, extra="forbid")

    value: FiniteFloat
    unit: str | None


class RequestedOutput(BaseModel):
    """Показатель, точка и форма вывода, которые указал пользователь."""

    model_config = ConfigDict(strict=True, extra="forbid")

    metric: str
    location: str | None
    presentation: Literal["plot", "table"] | None


class RequestIntent(BaseModel):
    """Извлечённые параметры запроса на расчёт."""

    model_config = ConfigDict(strict=True, extra="forbid")

    action: Literal["simulate_bypass", "unsupported", "unclear"]
    case_id: str | None
    event_time: RequestedTime | None
    transition_duration: RequestedTime | None
    end_time: RequestedTime | None
    requested_outputs: list[RequestedOutput]


class Value(BaseModel):
    """Число из ответа симулятора с обязательной единицей измерения."""

    name: str
    value: float
    unit: str


class ToolCall(BaseModel):
    """Одна запись журнала вызовов инструментов."""

    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


class AgentResult(BaseModel):
    """Единый результат агента для всех проектных тем."""

    status: Literal["ok", "refused", "needs_approval", "error"]
    answer: str
    values: list[Value] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    trace: list[ToolCall] = Field(default_factory=list)
