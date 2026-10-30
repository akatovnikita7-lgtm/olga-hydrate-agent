"""Композиция и основной цикл агента."""

from dataclasses import dataclass

from .schemas import AgentResult, BenchContext
from .tools import McpToolGateway, ToolGateway


@dataclass(slots=True)
class EngineeringAgent:
    """Минимальная оболочка агента с внедряемым шлюзом инструментов."""

    context: BenchContext
    tools: ToolGateway

    def run(self, request: str) -> AgentResult:
        """Обработать инженерный запрос.

        TODO для команды:
        1. разобрать запрос моделью в типизированную задачу;
        2. проверить единицы и диапазоны;
        3. выбрать и вызвать MCP-инструменты;
        4. собрать ответ только из результатов инструментов;
        5. заполнить ``values``, ``sources`` и ``trace``.
        """
        if not request.strip():
            return AgentResult(status="refused", answer="Запрос не должен быть пустым.")

        return AgentResult(
            status="refused",
            answer=(
                "Это шаблон проекта. Реализуйте разбор запроса и агентный цикл "
                "в src/agent/loop.py."
            ),
        )


def build_agent(context: BenchContext) -> EngineeringAgent:
    """Собрать зависимости агента в одном месте."""
    return EngineeringAgent(
        context=context,
        tools=McpToolGateway(server_url=context.mcp_server_url),
    )
