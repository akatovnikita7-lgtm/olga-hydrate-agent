"""MCP-сервер OLGA: инструменты контракта v1 (docs/olga_adapter.md).

Запуск (stdio, клиент сам стартует процесс):
    python -m mcp_server.server

stdout занят протоколом MCP. Никаких print(): служебные сообщения идут в stderr,
события — в logs/server.jsonl.
"""

from __future__ import annotations

import logging
import sys
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .service import OlgaService
from .settings import Settings

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mcp_server")

Seconds = Annotated[Any, Field(description="Время в секундах (число).", json_schema_extra={"type": "number"})]
TraceId = Annotated[str, Field(description="trace_id запроса пользователя; один на всю цепочку вызовов.")]
CallId = Annotated[str | None, Field(description="Идентификатор MCP-вызова на стороне клиента (необязательно).")]


def create_server(service: OlgaService | None = None) -> MCPServer:
    svc = service or OlgaService(Settings.from_env())
    server = MCPServer("olga-mbsnu")

    @server.tool()
    def get_server_status(trace_id: TraceId, call_id: CallId = None) -> dict[str, Any]:
        """Проверить конфигурацию адаптера OLGA (режим real/fake, launcher, каталоги).

        Только чтение. «configured» не означает, что лицензия OLGA доступна.
        """
        return svc.get_server_status(trace_id=trace_id, call_id=call_id)

    @server.tool()
    def read_case_manifest(case_id: str, trace_id: TraceId, call_id: CallId = None) -> dict[str, Any]:
        """Прочитать манифест подготовленного сценария: модель, отпечаток комплекта, расписание
        (прочитанное из самой модели), разрешённые параметры и контрольные точки. Только чтение.
        """
        return svc.read_case_manifest(case_id=case_id, trace_id=trace_id, call_id=call_id)

    @server.tool()
    def prepare_scenario(
        case_id: str,
        event_time_s: Seconds,
        transition_s: Seconds,
        end_time_s: Seconds,
        trace_id: TraceId,
        call_id: CallId = None,
    ) -> dict[str, Any]:
        """Проверить параметры и подготовить план запуска. OLGA НЕ запускается.

        Все времена в секундах: начало переключения, длительность перехода, конец расчёта.
        Отрицательное время -> INVALID_INPUT; значение, отличное от подготовленного
        сценария -> UNSUPPORTED_SCENARIO_PARAMETER. Возвращает plan_id и requires_approval.
        """
        return svc.prepare_scenario(
            case_id=case_id, event_time_s=event_time_s, transition_s=transition_s,
            end_time_s=end_time_s, trace_id=trace_id, call_id=call_id,
        )

    @server.tool()
    def start_run(
        plan_id: str,
        approval_token: Annotated[str | None, Field(description="Токен подтверждения человека; выдаёт доверенный клиент, не LLM.")],
        trace_id: TraceId,
        call_id: CallId = None,
    ) -> dict[str, Any]:
        """Запустить OLGA по подтверждённому неизменённому плану. Повтор с тем же plan_id
        возвращает прежний run_id. Без действительного токена -> APPROVAL_REQUIRED.
        """
        return svc.start_run(plan_id=plan_id, approval_token=approval_token, trace_id=trace_id, call_id=call_id)

    @server.tool()
    def get_run_status(run_id: str, trace_id: TraceId, call_id: CallId = None) -> dict[str, Any]:
        """Состояние запуска: QUEUED, RUNNING, SUCCEEDED, FAILED или CANCELLED, время и причина ошибки.
        Процент готовности не выдаётся.
        """
        return svc.get_run_status(run_id=run_id, trace_id=trace_id, call_id=call_id)

    @server.tool()
    def read_run_results(run_id: str, trace_id: TraceId, call_id: CallId = None) -> dict[str, Any]:
        """Результаты завершённого (SUCCEEDED) запуска: артефакты этого run_id, метрики и
        инженерная оценка от модуля анализа. Отдельно: execution / results_read / engineering_assessment.
        """
        return svc.read_run_results(run_id=run_id, trace_id=trace_id, call_id=call_id)

    return server


def main() -> None:
    settings = Settings.from_env()
    log.info("OLGA MCP server: mode=%s, problems=%s", settings.adapter_mode, settings.problems())
    create_server(OlgaService(settings)).run(transport="stdio")


if __name__ == "__main__":
    main()
