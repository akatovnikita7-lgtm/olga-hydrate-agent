"""Точка входа, которую вызывает бенчмарк курса."""

from src.agent.loop import build_agent
from src.agent.schemas import AgentResult, BenchContext


def run(request: str, ctx: BenchContext) -> AgentResult:
    """Выполнить один запрос через агентный контур.

    Не добавляйте сюда предметную логику. Корневой модуль остаётся тонким
    адаптером между бенчмарком и кодом из ``src/agent``.
    """
    return build_agent(ctx).run(request)
