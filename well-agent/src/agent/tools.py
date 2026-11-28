"""Синхронный шлюз агента к локальному MCP-серверу по stdio."""

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from math import isfinite
from pathlib import Path
from typing import Any, Protocol, TypeVar

from anyio import fail_after
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, PaginatedRequestParams, TextContent
from referencing import Registry
from referencing.exceptions import Unresolvable


_PROJECT_DIR = Path(__file__).resolve().parents[2]
_SERVER_ENV = ("SIMULATOR_NAME", "SIMULATOR_MODEL_PATH", "PYTHONDONTWRITEBYTECODE")
_Result = TypeVar("_Result")


class ToolGateway(Protocol):
    """Порт, через который агент работает с внешними инструментами."""

    def list_tools(self) -> list[dict[str, Any]]:
        """Вернуть описания доступных инструментов."""
        ...

    def call_tool(
        self, name: str, arguments: dict[str, Any], *, check_schema: bool = False
    ) -> dict[str, Any]:
        """Вызвать инструмент и вернуть структурированный результат."""
        ...


class McpGatewayError(RuntimeError):
    """Ошибка конфигурации, транспорта, протокола или инструмента."""

    def __init__(self, code: str | int, message: str, details: Any = None) -> None:
        self.code = code
        self.details = details
        super().__init__(f"{code}: {message}")


@contextmanager
def _mcp_errors(operation: str, timeout_s: float) -> Iterator[None]:
    try:
        yield
    except McpGatewayError:
        raise
    except TimeoutError as error:
        raise McpGatewayError(
            "MCP_TIMEOUT", f"{operation}: время ожидания MCP истекло ({timeout_s:g} с)."
        ) from error
    except MCPError as error:
        raise McpGatewayError(error.code, error.message, error.data) from error
    except Exception as error:
        raise McpGatewayError("MCP_SESSION_ERROR", f"{operation}: {error}") from error


class McpToolSession:
    """Операции в одной инициализированной MCP-сессии."""

    def __init__(self, session: ClientSession, timeout_s: float) -> None:
        self._session = session
        self._timeout_s = timeout_s

    async def list_tools(self) -> list[dict[str, Any]]:
        tools = []
        cursors = set()
        params = None
        with _mcp_errors("tools/list", self._timeout_s), fail_after(self._timeout_s):
            while True:
                page = await self._session.list_tools(params=params)
                tools.extend(
                    tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for tool in page.tools
                )
                cursor = page.next_cursor
                if cursor is None:
                    return tools
                if cursor in cursors:
                    raise McpGatewayError("INVALID_TOOL_LIST", "MCP повторил курсор списка инструментов.")
                cursors.add(cursor)
                params = PaginatedRequestParams(cursor=cursor)

    async def _check_tool_arguments(self, name: str, arguments: dict[str, Any]) -> None:
        tools = await self.list_tools()
        tool = next((item for item in tools if item["name"] == name), None)
        if tool is None:
            raise McpGatewayError("TOOL_NOT_ADVERTISED", f"Сервер MCP не объявил инструмент {name}.")
        schema = tool["inputSchema"]
        try:
            validator = validator_for(schema)
            validator.check_schema(schema)
            validator(schema, registry=Registry()).validate(arguments)
        except (SchemaError, ValidationError, Unresolvable) as error:
            raise McpGatewayError(
                "INCOMPATIBLE_MCP_SCHEMA", f"Аргументы {name} несовместимы с объявленной схемой MCP."
            ) from error

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, check_schema: bool = False
    ) -> dict[str, Any]:
        if check_schema:
            await self._check_tool_arguments(name, arguments)
        with _mcp_errors("tools/call", self._timeout_s), fail_after(self._timeout_s):
            result = await self._session.call_tool(name, arguments)

        if not isinstance(result, CallToolResult):
            raise McpGatewayError("INVALID_TOOL_RESULT", "MCP вернул неожиданный тип ответа.")

        payload = result.structured_content
        if result.is_error:
            details = payload if isinstance(payload, dict) else {}
            code = details.get("code")
            message = details.get("message")
            if not isinstance(message, str) or not message:
                message = "\n".join(
                    item.text for item in result.content if isinstance(item, TextContent)
                ) or f"Инструмент {name} сообщил об ошибке."
            raise McpGatewayError(
                code if isinstance(code, (str, int)) else "TOOL_ERROR", message, details
            )

        if not isinstance(payload, dict):
            raise McpGatewayError(
                "INVALID_TOOL_RESULT", f"Инструмент {name} должен вернуть структурированный объект."
            )
        if payload.get("ok") is False:
            error = payload.get("error") or {}
            raise McpGatewayError(error.get("code", "TOOL_ERROR"), error.get("message", str(error)), error)
        return payload


class McpToolGateway:
    """Запускает локальный сервер через Python, которым запущен клиент."""

    def __init__(
        self,
        server_url: str | None = None,
        *,
        server_args: Sequence[str] | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._server_url = server_url
        self._timeout_s = 10.0 if timeout_s is None else timeout_s
        if not isfinite(self._timeout_s) or self._timeout_s <= 0:
            raise ValueError("Таймаут MCP должен быть конечным положительным числом.")
        self._server_args = (
            ["-m", "mcp_server.server"] if server_args is None else list(server_args)
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[McpToolSession]:
        """Открыть stdio, инициализировать MCP и освободить ресурсы при выходе."""
        if self._server_url:
            raise McpGatewayError(
                "UNSUPPORTED_TRANSPORT", "Для stdio оставьте mcp_server_url пустым."
            )
        if not self._server_args:
            raise McpGatewayError("INVALID_SERVER_COMMAND", "Укажите аргументы запуска MCP-сервера.")
        parameters = StdioServerParameters(
            command=sys.executable,
            args=self._server_args,
            cwd=_PROJECT_DIR,
            env=server_environment(),
        )
        stack = AsyncExitStack()
        try:
            with _mcp_errors("initialize", self._timeout_s):
                streams = await stack.enter_async_context(stdio_client(parameters))
                client = await stack.enter_async_context(ClientSession(*streams))
                with fail_after(self._timeout_s):
                    await client.initialize()
            yield McpToolSession(client, self._timeout_s)
        finally:
            # Close the SDK task groups without injecting request errors into them.
            with _mcp_errors("stdio shutdown", self._timeout_s):
                await stack.aclose()

    def list_tools(self) -> list[dict[str, Any]]:
        return self._run(McpToolSession.list_tools)

    def call_tool(
        self, name: str, arguments: dict[str, Any], *, check_schema: bool = False
    ) -> dict[str, Any]:
        return self._run(lambda session: session.call_tool(name, arguments, check_schema=check_schema))

    def _run(self, operation: Callable[[McpToolSession], Awaitable[_Result]]) -> _Result:
        async def execute() -> _Result:
            async with self.session() as session:
                return await operation(session)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(execute())

        # The benchmark entry point is synchronous even when called from async code.
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(execute())).result()


def server_environment():
    # Forward solver/license settings, never the LLM API key.
    from scripts.smoke_client import server_env
    return {**server_env(), **{name: os.environ[name] for name in _SERVER_ENV if name in os.environ}}
