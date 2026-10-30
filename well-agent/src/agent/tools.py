"""Интерфейс инструментов агента и заготовка MCP-клиента."""

from typing import Any, Protocol


class ToolGateway(Protocol):
    """Порт, через который агент работает с внешними инструментами."""

    def list_tools(self) -> list[dict[str, Any]]:
        """Вернуть описания доступных инструментов."""
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Вызвать инструмент и вернуть структурированный результат."""
        ...


class McpToolGateway:
    """Заготовка клиента для подключения к MCP-серверу проекта."""

    def __init__(self, server_url: str | None) -> None:
        self._server_url = server_url

    def list_tools(self) -> list[dict[str, Any]]:
        """Получить список инструментов MCP.

        TODO: подключите MCP SDK и преобразуйте схемы инструментов в формат,
        который передаётся языковой модели.
        """
        return []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Вызвать MCP-инструмент.

        Реализацию транспорта добавьте после выбора режима: stdio для
        локального запуска или streamable HTTP для удалённого сервера.
        """
        raise NotImplementedError(
            f"MCP-клиент не настроен: tool={name!r}, server={self._server_url!r}"
        )
