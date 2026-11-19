"""Логика инструментов MCP без привязки к транспорту.

Каждый публичный метод возвращает словарь-конверт:
    {"ok": true,  "schema_version", "adapter_mode", "adapter_version", "trace_id", ...данные}
    {"ok": false, ..., "error": {code, message, field, received_value, expected_rule, retryable}}

Все проверки повторяются здесь независимо от клиента: ошибка LLM или клиента
не обходит ограничения сервера.
"""

from __future__ import annotations

import math
import re
import subprocess
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import case_kit, launcher, results_bridge
from .approval import verify_approval_token
from .errors import ERROR_CODES, ToolFailure
from .journal import Journal, utc_now
from .registry import Registry, is_valid_id, new_id
from .settings import Settings

ADAPTER_VERSION = "olga-adapter/0.1.0"
SCHEMA_VERSION = "1.0"
_TRACE_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
ACTIVE_STATES = {"QUEUED", "RUNNING"}


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class OlgaService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = Registry(settings.runs_root)
        self.journal = Journal(settings.log_dir)
        self._procs: dict[str, subprocess.Popen] = {}
        self._start_lock = threading.Lock()
        self._finalize_lock = threading.RLock()

    # ================================================================ общее
    def _envelope(self, trace_id: Any, ok: bool, **data: Any) -> dict[str, Any]:
        return {
            "ok": ok,
            "schema_version": SCHEMA_VERSION,
            "adapter_mode": self.settings.adapter_mode,
            "adapter_version": ADAPTER_VERSION,
            "trace_id": trace_id if isinstance(trace_id, str) else None,
            **data,
        }

    def _call(self, tool: str, arguments: dict[str, Any], body: Callable[[str, str], dict[str, Any]]) -> dict[str, Any]:
        trace_id = arguments.get("trace_id")
        call_id = arguments.get("call_id")
        server_call_id = f"srv_{uuid.uuid4().hex[:12]}"
        t0 = time.perf_counter()
        self.journal.write(
            "tool_call_received", trace_id=trace_id, call_id=call_id, server_call_id=server_call_id,
            tool=tool, arguments=arguments,
        )
        try:
            if not isinstance(trace_id, str) or not _TRACE_RE.match(trace_id):
                raise ToolFailure(
                    "INVALID_INPUT", "trace_id обязателен", field="trace_id", received_value=trace_id,
                    expected_rule="строка 1-128 символов [A-Za-z0-9._:-]",
                )
            result = self._envelope(trace_id, True, **body(trace_id, server_call_id))
            error = None
        except ToolFailure as failure:
            error = failure.to_dict()
            result = self._envelope(trace_id, False, error=error)
        except Exception as exc:  # noqa: BLE001
            self.journal.write(
                "internal_error", trace_id=trace_id, server_call_id=server_call_id, tool=tool,
                error=type(exc).__name__, detail=traceback.format_exc(limit=5),
            )
            error = ToolFailure("INTERNAL_ERROR", f"внутренняя ошибка сервера: {type(exc).__name__}").to_dict()
            result = self._envelope(trace_id, False, error=error)
        self.journal.write(
            "tool_call_completed", trace_id=trace_id, call_id=call_id, server_call_id=server_call_id,
            tool=tool, ok=result["ok"], error=error,
            plan_id=result.get("plan_id"), run_id=result.get("run_id"),
            result=None if error else _summary(result),
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
        return result

    def _manifest(self, case_id: Any) -> dict[str, Any]:
        return case_kit.load_manifest(self.settings.cases_dir, case_id, self.settings.allowed_case_ids)

    def _kit_dir(self) -> Path:
        if self.settings.case_kit_dir is None or not self.settings.case_kit_dir.is_dir():
            raise ToolFailure("CASE_KIT_INVALID", "каталог комплекта модели не настроен (OLGA_CASE_KIT_DIR)")
        return self.settings.case_kit_dir

    # ================================================================ статус сервера
    def get_server_status(self, trace_id: str, call_id: str | None = None) -> dict[str, Any]:
        def body(_t: str, _c: str) -> dict[str, Any]:
            problems = self.settings.problems()
            return {
                "configured": not problems,
                "configuration_problems": problems,
                "settings": self.settings.public_view(),
                "note": "configured не доказывает доступность лицензии OLGA",
            }
        return self._call("get_server_status", {"trace_id": trace_id, "call_id": call_id}, body)

    # ================================================================ read_case_manifest
    def read_case_manifest(self, case_id: str, trace_id: str, call_id: str | None = None) -> dict[str, Any]:
        def body(t: str, c: str) -> dict[str, Any]:
            manifest = self._manifest(case_id)
            kit: dict[str, Any] = {"status": "unavailable"}
            try:
                kit_dir = self._kit_dir()
                hashes = case_kit.kit_hashes(kit_dir, manifest)
                schedule = case_kit.read_schedule(kit_dir / manifest["input_file"], manifest)
                kit = {
                    "status": "ok",
                    "model_fingerprint": case_kit.fingerprint(hashes),
                    "file_hashes": hashes,
                    "schedule_read_from_model": schedule,
                }
            except ToolFailure as failure:
                kit = {"status": "invalid", "error": failure.to_dict()}
            public = {k: v for k, v in manifest.items() if k not in ("schedule_checks",)}
            public["schedule_objects"] = [
                {k: chk[k] for k in ("object", "keyword", "label", "value_key", "values", "value_unit", "meaning") if k in chk}
                for chk in manifest["schedule_checks"]
            ]
            return {
                "case_id": manifest["case_id"],
                "model_id": manifest["model_id"],
                "manifest": public,
                "kit": kit,
                "model_fingerprint": kit.get("model_fingerprint"),
                "server_configuration_problems": self.settings.problems(),
            }
        return self._call("read_case_manifest", {"case_id": case_id, "trace_id": trace_id, "call_id": call_id}, body)

    # ================================================================ prepare_scenario
    def prepare_scenario(
        self, case_id: str, event_time_s: Any, transition_s: Any, end_time_s: Any,
        trace_id: str, call_id: str | None = None,
    ) -> dict[str, Any]:
        args = {
            "case_id": case_id, "event_time_s": event_time_s, "transition_s": transition_s,
            "end_time_s": end_time_s, "trace_id": trace_id, "call_id": call_id,
        }

        def body(t: str, c: str) -> dict[str, Any]:
            manifest = self._manifest(case_id)
            params = _validate_times(event_time_s, transition_s, end_time_s)
            self.journal.write("validation_passed", trace_id=t, server_call_id=c, normalized=params)
            for name, rule in manifest["allowed_parameters"].items():
                allowed = [float(v) for v in rule["allowed_values"]]
                if not any(abs(params[name] - a) < 1e-9 for a in allowed):
                    raise ToolFailure(
                        "UNSUPPORTED_SCENARIO_PARAMETER",
                        "изменение этого параметра пока не реализовано: разрешён только подготовленный сценарий",
                        field=name, received_value=params[name],
                        expected_rule=f"одно из {rule['allowed_values']} {rule['unit']}",
                    )
            kit_dir = self._kit_dir()
            hashes = case_kit.kit_hashes(kit_dir, manifest)
            schedule = case_kit.read_schedule(kit_dir / manifest["input_file"], manifest)
            fp = case_kit.fingerprint(hashes)
            now = time.time()
            plan_id = new_id("plan")
            plan = {
                "plan_id": plan_id,
                "case_id": manifest["case_id"],
                "model_id": manifest["model_id"],
                "trace_id": t,
                "created_at": _iso(now),
                "expires_at": _iso(now + self.settings.plan_ttl_s),
                "expires_epoch": now + self.settings.plan_ttl_s,
                "parameters": params,
                "parameters_display": manifest["schedule"]["display"],
                "model_fingerprint": fp,
                "kit_hashes": hashes,
                "schedule_read_from_model": schedule,
                "model_changes": [],
                "actions": [
                    "скопировать комплект модели в новый каталог runs/<run_id>/model",
                    "сверить хеши копии с отпечатком плана и заново прочитать расписание из копии",
                    "запустить OLGA для копии (оригинал не изменяется)",
                    "дождаться окончания: код возврата, маркер нормальной остановки, тренд до ENDTIME",
                ],
                "requires_approval": True,
                "adapter_mode": self.settings.adapter_mode,
            }
            self.registry.save_plan(plan)
            self.journal.write("plan_created", trace_id=t, server_call_id=c, plan_id=plan_id, model_fingerprint=fp)
            problems = self.settings.problems()
            return {
                "plan_id": plan_id,
                "case_id": plan["case_id"],
                "model_id": plan["model_id"],
                "normalized_parameters": params,
                "parameters_display": plan["parameters_display"],
                "model_fingerprint": fp,
                "schedule_read_from_model": schedule,
                "model_changes": [],
                "model_changes_note": "готовый сценарий: модель не изменяется, расписание уже записано в ней",
                "actions": plan["actions"],
                "requires_approval": True,
                "approval_binding": "HMAC(OLGA_APPROVAL_SECRET, plan_id|model_fingerprint|trace_id)",
                "expires_at": plan["expires_at"],
                "ready_to_run": not problems,
                "server_configuration_problems": problems,
            }
        return self._call("prepare_scenario", args, body)

    # ================================================================ start_run
    def start_run(self, plan_id: str, approval_token: str | None, trace_id: str, call_id: str | None = None) -> dict[str, Any]:
        args = {"plan_id": plan_id, "approval_token": approval_token, "trace_id": trace_id, "call_id": call_id}

        def body(t: str, c: str) -> dict[str, Any]:
            if not is_valid_id(plan_id, "plan"):
                raise ToolFailure("INVALID_INPUT", "некорректный plan_id", field="plan_id", received_value=plan_id)
            plan = self.registry.load_plan(plan_id)
            if plan is None:
                raise ToolFailure("PLAN_NOT_FOUND", "план не найден", field="plan_id", received_value=plan_id)
            if not self.settings.approval_secret:
                raise ToolFailure("APPROVAL_REQUIRED", "на сервере не настроен секрет подтверждения")
            if not verify_approval_token(
                self.settings.approval_secret, approval_token, plan_id, plan["model_fingerprint"], plan["trace_id"]
            ):
                self.journal.write("approval_rejected", trace_id=t, server_call_id=c, plan_id=plan_id)
                raise ToolFailure(
                    "APPROVAL_REQUIRED", "нет действительного подтверждения человека для этого плана",
                    field="approval_token", expected_rule="токен, выданный доверенным клиентом после ответа пользователя",
                )
            self.journal.write("approval_accepted", trace_id=t, server_call_id=c, plan_id=plan_id)

            with self._start_lock:
                existing = self.registry.claimed_run(plan_id)
                if existing:
                    run = self._refresh(existing)
                    self.journal.write("start_run_replay", trace_id=t, plan_id=plan_id, run_id=existing)
                    return {"run_id": existing, "plan_id": plan_id, "state": run.get("state") if run else "UNKNOWN",
                            "idempotent_replay": True}
                if time.time() > float(plan["expires_epoch"]):
                    raise ToolFailure("PLAN_EXPIRED", "срок действия плана истёк; подготовьте новый план",
                                      field="plan_id", received_value=plan_id)
                problems = self.settings.problems()
                if problems:
                    raise ToolFailure("SIMULATOR_UNAVAILABLE", "сервер не настроен для запуска OLGA",
                                      received_value=problems)
                manifest = self._manifest(plan["case_id"])
                kit_dir = self._kit_dir()
                current_fp = case_kit.fingerprint(case_kit.kit_hashes(kit_dir, manifest))
                if current_fp != plan["model_fingerprint"]:
                    raise ToolFailure(
                        "FINGERPRINT_MISMATCH", "модель изменилась после подготовки плана; подтверждение недействительно",
                        field="model_fingerprint", received_value=current_fp, expected_rule=plan["model_fingerprint"],
                    )
                active = [r for r in self.registry.all_runs() if r.get("state") in ACTIVE_STATES]
                active = [r for r in (self._refresh(r["run_id"]) for r in active) if r and r.get("state") in ACTIVE_STATES]
                if len(active) >= self.settings.max_concurrent_runs:
                    raise ToolFailure(
                        "RUN_LIMIT_REACHED", "достигнут лимит одновременных расчётов",
                        received_value=[r["run_id"] for r in active],
                        expected_rule=f"не более {self.settings.max_concurrent_runs}",
                    )
                run_id = new_id("run")
                claimed, owner = self.registry.claim_plan(plan_id, run_id)
                if not claimed:
                    run = self._refresh(owner)
                    return {"run_id": owner, "plan_id": plan_id, "state": run.get("state") if run else "UNKNOWN",
                            "idempotent_replay": True}
                return self._launch(plan, manifest, kit_dir, run_id, t, c)
        return self._call("start_run", args, body)

    def _launch(self, plan: dict[str, Any], manifest: dict[str, Any], kit_dir: Path, run_id: str, t: str, c: str) -> dict[str, Any]:
        run_dir = self.registry.run_dir(run_id)
        model_dir = run_dir / "model"
        now = time.time()
        run: dict[str, Any] = {
            "run_id": run_id, "plan_id": plan["plan_id"], "case_id": plan["case_id"], "trace_id": plan["trace_id"],
            "start_trace_id": t, "model_fingerprint": plan["model_fingerprint"], "adapter_mode": self.settings.adapter_mode,
            "adapter_version": ADAPTER_VERSION, "state": "QUEUED", "created_at": _iso(now), "created_epoch": now,
            "started_at": None, "finished_at": None, "exit_code": None, "pid": None, "error": None,
        }
        run_dir.mkdir(parents=True, exist_ok=False)
        self.registry.save_run(run)
        try:
            copy_hashes = case_kit.copy_kit(kit_dir, model_dir, manifest)
            if case_kit.fingerprint(copy_hashes) != plan["model_fingerprint"]:
                raise ToolFailure("FINGERPRINT_MISMATCH", "копия комплекта не совпадает с отпечатком плана")
            self.journal.write("kit_copied", trace_id=t, server_call_id=c, run_id=run_id, file_hashes=copy_hashes)
            schedule = case_kit.read_schedule(model_dir / manifest["input_file"], manifest)
            self.journal.write("schedule_verified_in_copy", trace_id=t, run_id=run_id, schedule=schedule)
            argv = launcher.build_argv(self.settings, model_dir, run_dir, manifest["input_file"])
            started = time.time()
            proc = launcher.start_process(argv, model_dir, run_dir / "launcher_stdout.log", run_dir / "launcher_stderr.log")
        except ToolFailure as failure:
            self.registry.update_run(run_id, state="FAILED", error=failure.to_dict(), finished_at=utc_now())
            self.registry.release_claim(plan["plan_id"], run_id)
            raise
        except OSError as exc:
            failure = ToolFailure("SIMULATOR_UNAVAILABLE", f"не удалось запустить launcher: {type(exc).__name__}")
            self.registry.update_run(run_id, state="FAILED", error=failure.to_dict(), finished_at=utc_now())
            self.registry.release_claim(plan["plan_id"], run_id)
            raise failure from exc

        self._procs[run_id] = proc
        safe_argv = [Path(argv[0]).name] + [_safe_arg(a, run_dir) for a in argv[1:]]
        self.registry.update_run(run_id, state="RUNNING", pid=proc.pid, started_at=_iso(started),
                                 started_epoch=started, argv=argv, safe_argv=safe_argv)
        self.journal.write("process_started", trace_id=t, server_call_id=c, run_id=run_id,
                           plan_id=plan["plan_id"], argv=safe_argv, cwd="<run_dir>/model")
        launcher.watch_process(proc, lambda code: self._on_exit(run_id, code))
        return {"run_id": run_id, "plan_id": plan["plan_id"], "state": "RUNNING", "started_at": _iso(started),
                "launcher": safe_argv, "idempotent_replay": False}

    # ================================================================ статус
    def _on_exit(self, run_id: str, code: int) -> None:
        run = self.registry.update_run(run_id, exit_code=code, launcher_exited_at=utc_now())
        self.journal.write("process_exited", trace_id=run.get("trace_id"), run_id=run_id,
                           plan_id=run.get("plan_id"), exit_code=code)
        self._finalize(run_id)

    def _finalize(self, run_id: str) -> dict[str, Any] | None:
        with self._finalize_lock:
            return self._finalize_locked(run_id)

    def _finalize_locked(self, run_id: str) -> dict[str, Any] | None:
        run = self.registry.load_run(run_id)
        if run is None or run.get("state") not in ACTIVE_STATES:
            return run
        manifest = self._manifest(run["case_id"])
        run_dir = self.registry.run_dir(run_id)
        model_dir = run_dir / "model"
        outputs = launcher.evaluate_outputs(model_dir, manifest, float(run.get("started_epoch") or 0))
        code = run.get("exit_code")
        if code is None:
            # Код возврата неизвестен (сервер перезапускался, процесс был не наш): судим по файлам.
            exit_ok = True
            self.registry.update_run(run_id, exit_code_note="код возврата неизвестен; решение по файлам результата")
        else:
            exit_ok = code == 0 or not self.settings.require_zero_exit_code
        complete = outputs["normal_stop"] and outputs["trend_complete"] and outputs["outputs_fresh"]
        if (
            self.settings.launcher_detaches and not complete
            and outputs["out_mtime_age_s"] is not None and outputs["out_mtime_age_s"] < self.settings.stale_output_after_s
        ):
            return self.registry.update_run(run_id, outputs=outputs, note="launcher завершился, решатель ещё пишет файлы")
        if complete and exit_ok:
            run = self.registry.update_run(run_id, state="SUCCEEDED", finished_at=utc_now(), outputs=outputs, error=None)
        else:
            text = launcher.diagnostics_text(model_dir, run_dir, manifest)
            code_name, why = launcher.classify_failure(text, self.settings)
            if code_name == "SIMULATION_FAILED" and outputs["normal_stop"] and not outputs["trend_complete"]:
                code_name, why = "INCOMPLETE_RESULT", "нормальная остановка есть, но тренд не доходит до ENDTIME"
            error = ToolFailure(code_name, why, received_value={"exit_code": code, **outputs}).to_dict()
            error["solver_log_tail"] = text[-1500:]
            run = self.registry.update_run(run_id, state="FAILED", finished_at=utc_now(), outputs=outputs, error=error)
        self.journal.write("run_finalized", trace_id=run.get("trace_id"), run_id=run_id,
                           plan_id=run.get("plan_id"), state=run["state"], exit_code=code,
                           error=run.get("error", {}) and {k: run["error"][k] for k in ("code", "message")})
        self._procs.pop(run_id, None)
        return run

    def _refresh(self, run_id: str) -> dict[str, Any] | None:
        run = self.registry.load_run(run_id)
        if run is None or run.get("state") not in ACTIVE_STATES:
            return run
        proc = self._procs.get(run_id)
        if proc is not None:
            if proc.poll() is None:
                return run
            if run.get("exit_code") is None:
                self.registry.update_run(run_id, exit_code=proc.returncode)
            return self._finalize(run_id)
        if run.get("state") == "RUNNING" and launcher.pid_alive(run.get("pid")):
            return run
        if run.get("state") == "QUEUED" and time.time() - float(run.get("created_epoch", 0)) < 60:
            return run
        return self._finalize(run_id)  # процесс не наш или сервер перезапускался: судим по файлам

    def get_run_status(self, run_id: str, trace_id: str, call_id: str | None = None) -> dict[str, Any]:
        def body(t: str, c: str) -> dict[str, Any]:
            if not is_valid_id(run_id, "run"):
                raise ToolFailure("INVALID_INPUT", "некорректный run_id", field="run_id", received_value=run_id)
            run = self._refresh(run_id)
            if run is None:
                raise ToolFailure("RUN_NOT_FOUND", "запуск не найден", field="run_id", received_value=run_id)
            started = run.get("started_epoch")
            elapsed = round(time.time() - started, 1) if started and run["state"] in ACTIVE_STATES else None
            data: dict[str, Any] = {
                "run_id": run_id, "plan_id": run.get("plan_id"), "case_id": run.get("case_id"),
                "state": run["state"], "created_at": run.get("created_at"), "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"), "elapsed_s": elapsed, "exit_code": run.get("exit_code"),
                "error": run.get("error"), "outputs_check": run.get("outputs"), "note": run.get("note"),
                "progress": None, "progress_note": "OLGA не сообщает процент готовности; прогресс не оценивается",
            }
            if elapsed is not None and elapsed > self.settings.run_timeout_s:
                data["timeout_exceeded"] = True
                data["timeout"] = ToolFailure(
                    "TIMEOUT", "превышено время ожидания расчёта; процесс не остановлен",
                    received_value=elapsed, expected_rule=f"<= {self.settings.run_timeout_s} с",
                ).to_dict()
                data["instruction"] = (
                    "Расчёт продолжает выполняться. Повторите get_run_status позже с тем же run_id. "
                    "Автоматическая отмена не реализована: остановку выполняет человек вручную "
                    "только для процесса с указанным pid."
                )
                data["pid"] = run.get("pid")
                self.journal.write("timeout_exceeded", trace_id=t, run_id=run_id, elapsed_s=elapsed)
            return data
        return self._call("get_run_status", {"run_id": run_id, "trace_id": trace_id, "call_id": call_id}, body)

    # ================================================================ результаты
    def read_run_results(self, run_id: str, trace_id: str, call_id: str | None = None) -> dict[str, Any]:
        def body(t: str, c: str) -> dict[str, Any]:
            if not is_valid_id(run_id, "run"):
                raise ToolFailure("INVALID_INPUT", "некорректный run_id", field="run_id", received_value=run_id)
            run = self._refresh(run_id)
            if run is None:
                raise ToolFailure("RUN_NOT_FOUND", "запуск не найден", field="run_id", received_value=run_id)
            if run["state"] in ACTIVE_STATES:
                raise ToolFailure("RUN_NOT_FINISHED", "расчёт ещё выполняется", field="run_id", received_value=run_id)
            if run["state"] != "SUCCEEDED":
                err_code = (run.get("error") or {}).get("code")
                raise ToolFailure(
                    err_code if err_code in ERROR_CODES else "SIMULATION_FAILED",
                    f"результаты недоступны: запуск в состоянии {run['state']}",
                    field="run_id", received_value=run_id,
                )
            manifest = self._manifest(run["case_id"])
            run_dir = self.registry.run_dir(run_id)
            model_dir = run_dir / "model"
            outputs = launcher.evaluate_outputs(model_dir, manifest, float(run.get("started_epoch") or 0))
            if not (outputs["normal_stop"] and outputs["trend_complete"] and outputs["outputs_fresh"]):
                raise ToolFailure("INCOMPLETE_RESULT", "файлы результата этого запуска неполны", received_value=outputs)
            copy_fp = case_kit.fingerprint({n: case_kit.sha256_file(model_dir / n) for n in manifest["kit_files"]})
            if copy_fp != run["model_fingerprint"]:
                raise ToolFailure("FINGERPRINT_MISMATCH", "входные файлы в каталоге запуска изменены после расчёта")
            out_text = (model_dir / manifest["expected_outputs"]["out"]).read_text(encoding="utf-8", errors="replace")
            m = re.search(r"VERSION\s*:\s*(.+)", out_text)
            software_version = m.group(1).strip() if m else None
            run_info = {k: run.get(k) for k in ("run_id", "plan_id", "case_id", "trace_id", "model_fingerprint")}
            analysis = results_bridge.analyze(self.settings.results_analyzer, model_dir, manifest, run_info)
            artifacts = []
            for kind, name in manifest["expected_outputs"].items():
                p = model_dir / name
                if p.is_file():
                    artifacts.append({"artifact_id": f"{run_id}:{kind}", "kind": kind,
                                      "path": f"runs/{run_id}/model/{name}", "sha256": case_kit.sha256_file(p),
                                      "size_bytes": p.stat().st_size})
            self.journal.write("results_read", trace_id=t, server_call_id=c, run_id=run_id,
                               plan_id=run.get("plan_id"), artifacts=[a["artifact_id"] for a in artifacts],
                               assessment=analysis.get("assessment"))
            return {
                "run": {
                    "case_id": run["case_id"], "plan_id": run["plan_id"], "run_id": run_id,
                    "trace_id": run["trace_id"], "model_fingerprint": run["model_fingerprint"],
                    "software_version": software_version, "adapter_version": ADAPTER_VERSION,
                    "adapter_mode": run.get("adapter_mode"), "execution_status": run["state"],
                    "created_at": run.get("created_at"), "finished_at": run.get("finished_at"),
                    "artifact_ids": [a["artifact_id"] for a in artifacts],
                },
                "run_id": run_id,
                "statuses": {
                    "execution": run["state"],
                    "results_read": "OK",
                    "engineering_assessment": analysis.get("assessment", {}).get("status", "NOT_ASSESSED"),
                },
                "outputs_check": outputs,
                "artifacts": artifacts + list(analysis.get("artifacts", [])),
                "metrics": analysis.get("metrics", []),
                "series": analysis.get("series", []),
                "assessment": analysis.get("assessment"),
                "trend_catalog": analysis.get("trend_catalog"),
                "analyzer": analysis.get("analyzer"),
            }
        return self._call("read_run_results", {"run_id": run_id, "trace_id": trace_id, "call_id": call_id}, body)


# ==================================================================== вспомогательные
def _num(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolFailure("INVALID_INPUT", f"{name} должно быть числом в секундах", field=name,
                          received_value=value, expected_rule="число (int/float), единица — секунды")
    value = float(value)
    if not math.isfinite(value):
        raise ToolFailure("INVALID_INPUT", f"{name} должно быть конечным числом", field=name,
                          received_value=value, expected_rule="конечное число")
    return value


def _validate_times(event_time_s: Any, transition_s: Any, end_time_s: Any) -> dict[str, float]:
    event = _num("event_time_s", event_time_s)
    trans = _num("transition_s", transition_s)
    end = _num("end_time_s", end_time_s)
    if event < 0:
        raise ToolFailure("INVALID_INPUT", "начало переключения не может быть отрицательным",
                          field="event_time_s", received_value=event, expected_rule="event_time_s >= 0")
    if trans <= 0:
        raise ToolFailure("INVALID_INPUT", "длительность перехода должна быть положительной",
                          field="transition_s", received_value=trans, expected_rule="transition_s > 0")
    if end <= 0:
        raise ToolFailure("INVALID_INPUT", "окончание расчёта должно быть положительным",
                          field="end_time_s", received_value=end, expected_rule="end_time_s > 0")
    if event + trans >= end:
        raise ToolFailure("INVALID_INPUT", "переход должен закончиться раньше окончания расчёта",
                          field="end_time_s", received_value=end,
                          expected_rule="event_time_s + transition_s < end_time_s")
    return {"event_time_s": event, "transition_s": trans, "transition_end_s": event + trans, "end_time_s": end}


def _safe_arg(arg: str, run_dir: Path) -> str:
    """Скрыть локальные пути в журнале/ответе: каталог запуска -> <run_dir>, прочее -> имя файла."""
    arg = arg.replace(str(run_dir), "<run_dir>")
    if not arg.startswith("<run_dir>") and Path(arg).is_absolute():
        return f"<path>/{Path(arg).name}"
    return arg


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    keep = ("plan_id", "run_id", "state", "case_id", "model_fingerprint", "idempotent_replay", "statuses",
            "requires_approval", "ready_to_run", "configured", "timeout_exceeded")
    return {k: result[k] for k in keep if k in result}
