"""Фабрика локального MCP-сервера проекта."""

from typing import Any

from mcp.server.mcpserver import MCPServer

from .settings import Settings
from .simulator import SimulatorClient


def create_server(client: SimulatorClient | None = None) -> MCPServer:
    """Создать сервер с внедряемым клиентом симулятора."""
    simulator = client or SimulatorClient(Settings.from_env())
    server = MCPServer("engineering-simulator")

    @server.tool()
    def get_simulator_status() -> dict[str, str | None]:
        """Проверить, настроено ли подключение к инженерному ПО."""
        return simulator.status()

    @server.tool()
    def run_simulation(
        case_id: str,
        parameters: dict[str, float],
    ) -> dict[str, Any]:
        """Запустить расчётный сценарий с параметрами в единицах проекта."""
        return simulator.run_case(case_id=case_id, parameters=parameters)

    return server


mcp = create_server()


def main() -> None:
    """Запустить локальный сервер по stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
