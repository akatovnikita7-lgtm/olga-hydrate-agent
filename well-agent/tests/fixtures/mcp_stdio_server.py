"""Отдельный тестовый MCP-процесс. Stdout используется только протоколом."""

import asyncio
import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel


server = MCPServer("olga-stdio-test")


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
def read_case_manifest(case_id: str, trace_id: str) -> TestManifest:
    """Вернуть тестовый манифест для проверки транспорта."""
    return TestManifest(
        case_id=case_id,
        trace_id=trace_id,
        schedule={"event_time_s": 172800, "transition_s": 60, "end_time_s": 345600},
        allowed_parameters={},
        control_points=[],
    )


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


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(str(os.getpid()), encoding="utf-8")
    server.run(transport="stdio")
