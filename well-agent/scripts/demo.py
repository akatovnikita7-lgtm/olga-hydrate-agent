"""CLI валидации и тестового прогона сценария обхода МБСНУ."""
import argparse
import asyncio
import math
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from src.agent.config import load_context
from src.agent.demo_flow import run_test_plan
from src.agent.run_flow import run_plan
from src.agent.journal import Journal
from src.agent.loop import build_agent
from src.agent.tools import McpGatewayError, McpToolGateway


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("Укажите положительное конечное число секунд.")
    return seconds


def run_one(request, context, args, ask=input, show=print):
    journal = Journal(args.log_dir, context.llm_api_key)
    show(f"trace_id={journal.trace_id}\nЖурнал {journal.path}")
    journal.write("request", text=request, mode="test" if args.test_mcp else ("run" if getattr(args, "execute", False) else "validation"))
    outcome = "error"
    try:
        with TemporaryDirectory() as temp:
            if args.test_mcp:
                context = context.model_copy(update={
                    "mcp_case_id": "mbsnu_bypass_96h",
                    "mcp_server_args": (
                        "tests/fixtures/mcp_stdio_server.py", str(Path(temp) / "server.pid"),
                        "--outcome", args.test_outcome, "--artifacts", str(args.log_dir.resolve()),
                    ),
                })
                show("TEST MODE · синтетический MCP")
            result = build_agent(context).run(request, journal=journal)
            journal.write("validation", status=result.status, result=result.validated_request,
                          rejection=result.rejection, answer=result.answer)
            show(journal.clean(result.answer))
            if result.validated_request:
                for field, source in result.validated_request.parameter_sources.items():
                    show(f"{field} — {source}")
            if result.status == "ok" and (args.test_mcp or getattr(args, "execute", False)):
                gateway = McpToolGateway(server_args=context.mcp_server_args, timeout_s=context.mcp_timeout_s)

                async def continue_request():
                    async with gateway.session() as session:
                        flow = run_test_plan if args.test_mcp else run_plan
                        return await flow(
                            session, result.validated_request, journal, ask,
                            lambda text: show(journal.clean(text)), args.poll_interval, args.timeout,
                        )
                outcome = asyncio.run(continue_request())
            else:
                outcome = result.status
    except (McpGatewayError, OSError) as error:
        journal.write("error", error=str(error))
        show(journal.clean(str(error)))
    except KeyboardInterrupt:
        outcome = "interrupted"
    finally:
        journal.write("finished", status=outcome)
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", help="Один запрос вместо интерактивного цикла")
    parser.add_argument("--execute", action="store_true", help="Выполнить план через настроенный адаптер OLGA")
    parser.add_argument("--test-mcp", action="store_true", help="Использовать отдельный тестовый MCP-процесс")
    parser.add_argument("--test-outcome", choices=["success", "stuck", "failed", "cancelled"], default="success")
    parser.add_argument("--poll-interval", type=positive_seconds, default=10)
    parser.add_argument("--timeout", type=positive_seconds, default=21600)
    parser.add_argument("--log-dir", type=Path, default=Path(__file__).resolve().parents[1] / "logs")
    args = parser.parse_args()
    try:
        context = load_context()
        if args.request is not None:
            return 0 if run_one(args.request, context, args) == "ok" else 1
        while True:
            try:
                request = input("Инженерный запрос (Enter для выхода): ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not request:
                break
            run_one(request, context, args)
    except (ValueError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
