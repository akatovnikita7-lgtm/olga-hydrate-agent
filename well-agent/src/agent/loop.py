"""Композиция и основной цикл агента."""

from dataclasses import dataclass
from contextlib import nullcontext
from uuid import uuid4

from pydantic import ValidationError

from .intent import parse_request
from .journal import Journal
from .llm import LlmError
from .schemas import AgentResult, BenchContext, CaseManifest, ToolCall
from .tools import McpGatewayError, McpToolGateway, ToolGateway
from .validation import ManifestError, RequestRefused, normalize_times, resolve_request, select_case, validate_manifest


@dataclass(slots=True)
class EngineeringAgent:
    """Разобрать запрос и проверить его по манифесту MCP."""

    context: BenchContext
    tools: ToolGateway

    def run(self, request: str, journal: Journal | None = None) -> AgentResult:
        trace_id = journal.trace_id if journal else uuid4().hex
        trace = []
        try:
            if not request.strip():
                raise RequestRefused("INVALID_INPUT", "request", "Запрос не должен быть пустым.")
            llm_call = journal.call("llm", self.context.llm_model, {"request": request}) if journal else nullcontext({})
            with llm_call as response:
                intent = parse_request(request, self.context)
                response["result"] = intent
            if journal:
                journal.write("intent", result=intent)
            explicit_times = normalize_times(intent)
            case_id = select_case(intent, self.context.mcp_case_id)
            arguments = {"case_id": case_id, "trace_id": trace_id}
            call = ToolCall(tool="read_case_manifest", arguments=arguments)
            trace.append(call)
            mcp_call = journal.call("mcp", call.tool, arguments) if journal else nullcontext({})
            with mcp_call as response:
                payload = self.tools.call_tool(call.tool, arguments, check_schema=True)
                response["result"] = payload
            if "manifest" in payload:
                kit = payload.get("kit", {})
                if kit.get("status") != "ok":
                    error = kit.get("error", {})
                    raise McpGatewayError(error.get("code", "INVALID_KIT"), error.get("message", "Комплект модели не готов."))
                raw = payload["manifest"]
                payload = {**raw, "schedule": {k: raw["schedule"][k] for k in
                    ("event_time_s", "transition_s", "end_time_s")},
                    "model_fingerprint": payload["model_fingerprint"],
                    "trace_id": payload["trace_id"], "mode": payload["adapter_mode"]}
            manifest = CaseManifest.model_validate(payload)
            validate_manifest(manifest, case_id, trace_id)
            call.result = manifest.model_dump(mode="json")
            validated = resolve_request(intent, explicit_times, manifest)
        except RequestRefused as error:
            return AgentResult(
                status="refused", answer=str(error), trace_id=trace_id, trace=trace,
                rejection=error.rejection,
            )
        except McpGatewayError as error:
            if error.code == "CASE_NOT_FOUND":
                message = f"Сервер MCP не знает сценарий {case_id}."
                call.error = message
                refusal = RequestRefused("UNSUPPORTED_SCENARIO", "case_id", message, case_id)
                return AgentResult(
                    status="refused", answer=str(refusal), trace_id=trace_id, trace=trace,
                    rejection=refusal.rejection,
                )
            call.error = f"Не удалось прочитать MCP-манифест ({error.code})."
            return AgentResult(status="error", answer=call.error, trace_id=trace_id, trace=trace)
        except (ValidationError, ManifestError) as error:
            call.error = str(error) if isinstance(error, ManifestError) else "Некорректная схема MCP-манифеста."
            return AgentResult(status="error", answer=call.error, trace_id=trace_id, trace=trace)
        except LlmError as error:
            return AgentResult(status="error", answer=str(error), trace_id=trace_id)

        schedule = validated.schedule
        mode = "TEST MODE. " if manifest.mode == "test" else ""
        return AgentResult(
            status="ok",
            answer=(
                f"{mode}Параметры сценария {case_id} проверены по манифесту. "
                f"Начало {schedule.event_time_s:g} с, длительность {schedule.transition_s:g} с, "
                f"конец расчёта {schedule.end_time_s:g} с."
            ),
            trace_id=trace_id,
            trace=trace,
            validated_request=validated,
        )


def build_agent(context: BenchContext) -> EngineeringAgent:
    """Собрать зависимости агента в одном месте."""
    return EngineeringAgent(
        context=context,
        tools=McpToolGateway(
            server_url=context.mcp_server_url,
            server_args=context.mcp_server_args,
            timeout_s=context.mcp_timeout_s,
        ),
    )
