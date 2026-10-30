"""Pydantic-схемы на границе агента и бенчмарка."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class BenchContext(BaseModel):
    """Настройки, которые передаёт бенчмарк или демо-ноутбук."""

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    mcp_server_url: str | None = None


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
