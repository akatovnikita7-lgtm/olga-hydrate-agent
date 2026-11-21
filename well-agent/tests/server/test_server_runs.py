"""Запуск, подтверждение, идемпотентность, статусы и ошибки — на ТЕСТОВОМ адаптере (fake_olga).

Эти тесты не подтверждают работу настоящей OLGA: это отдельная проверка на машине с лицензией.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from mcp_server import case_kit
from mcp_server.approval import make_approval_token
from mcp_server.service import OlgaService

from .conftest import CASE, SECRET, prepare, run_dirs, token_for, wait_terminal


def test_start_without_or_with_wrong_token_does_not_launch(make_service) -> None:
    svc = make_service()
    plan = prepare(svc)
    for token in (None, "", "0" * 64, token_for(plan, trace="other-trace")):
        res = svc.start_run(plan["plan_id"], token, "trace-1")
        assert res["error"]["code"] == "APPROVAL_REQUIRED"
    assert run_dirs(svc) == []


def test_unknown_or_malformed_plan(make_service) -> None:
    svc = make_service()
    assert svc.start_run("plan_" + "0" * 32, "x", "t")["error"]["code"] == "PLAN_NOT_FOUND"
    assert svc.start_run("../../etc", "x", "t")["error"]["code"] == "INVALID_INPUT"


def test_model_changed_after_prepare_invalidates_approval(make_service, kit: Path) -> None:
    svc = make_service()
    plan = prepare(svc)
    tab = kit / "Novosam_T1_HeaderFix.tab"
    tab.write_text(tab.read_text() + "changed\n")
    res = svc.start_run(plan["plan_id"], token_for(plan), "trace-1")
    assert res["error"]["code"] == "FINGERPRINT_MISMATCH"
    assert run_dirs(svc) == []


def test_successful_fake_run_and_results(make_service, kit: Path) -> None:
    svc = make_service()
    before = case_kit.kit_hashes(kit, svc._manifest(CASE))
    plan = prepare(svc)
    run = svc.start_run(plan["plan_id"], token_for(plan), "trace-1")
    assert run["ok"] is True and run["state"] == "RUNNING"
    st = wait_terminal(svc, run["run_id"])
    assert st["state"] == "SUCCEEDED", st
    assert st["exit_code"] == 0
    res = svc.read_run_results(run["run_id"], "trace-1")
    assert res["ok"] is True
    assert res["adapter_mode"] == "fake"
    assert res["statuses"] == {"execution": "SUCCEEDED", "results_read": "OK", "engineering_assessment": "NOT_ASSESSED"}
    assert res["run"]["run_id"] == run["run_id"] and res["run"]["plan_id"] == plan["plan_id"]
    assert res["run"]["software_version"].startswith("FAKE")
    assert len(res["metrics"]) == 20
    bypass = next(m for m in res["metrics"] if m["name"] == "final" and "BYPASS" in m["location_id"])
    assert bypass["value"] == 10.0
    assert any(a["kind"] == "plot" for a in res["artifacts"])
    # оригинал не изменился, выходные файлы появились только в каталоге запуска
    assert case_kit.kit_hashes(kit, svc._manifest(CASE)) == before
    assert not (kit / "case1_obhod.out").exists()
    assert (svc.registry.run_dir(run["run_id"]) / "model" / "case1_obhod.out").is_file()


def test_repeat_start_returns_same_run(make_service) -> None:
    svc = make_service()
    plan = prepare(svc)
    tok = token_for(plan)
    first = svc.start_run(plan["plan_id"], tok, "trace-1")
    second = svc.start_run(plan["plan_id"], tok, "trace-1")
    assert second["run_id"] == first["run_id"]
    assert second["idempotent_replay"] is True
    wait_terminal(svc, first["run_id"])
    third = svc.start_run(plan["plan_id"], tok, "trace-1")
    assert third["run_id"] == first["run_id"] and third["state"] == "SUCCEEDED"
    assert len(run_dirs(svc)) == 1


def test_concurrency_limit(make_service) -> None:
    svc = make_service("slow")
    p1, p2 = prepare(svc), prepare(svc, trace="trace-2")
    r1 = svc.start_run(p1["plan_id"], token_for(p1), "trace-1")
    r2 = svc.start_run(p2["plan_id"], token_for(p2, "trace-2"), "trace-2")
    assert r1["ok"] and r2["error"]["code"] == "RUN_LIMIT_REACHED"
    assert svc.read_run_results(r1["run_id"], "trace-1")["error"]["code"] == "RUN_NOT_FINISHED"
    wait_terminal(svc, r1["run_id"])
    r2b = svc.start_run(p2["plan_id"], token_for(p2, "trace-2"), "trace-2")
    assert r2b["ok"] is True  # план не был израсходован отказом
    wait_terminal(svc, r2b["run_id"], "trace-2")


def _run(svc: OlgaService) -> dict:
    plan = prepare(svc)
    run = svc.start_run(plan["plan_id"], token_for(plan), "trace-1")
    return wait_terminal(svc, run["run_id"])


def test_failure_is_generic_without_confirmed_pattern(make_service) -> None:
    st = _run(make_service("license"))
    assert st["state"] == "FAILED"
    assert st["error"]["code"] == "SIMULATION_FAILED"  # без подтверждённого признака LICENSE_BUSY не ставим


def test_license_busy_only_by_configured_pattern(make_service) -> None:
    st = _run(make_service("license", license_error_patterns=(r"FAKE LICENSE ERROR",)))
    assert st["error"]["code"] == "LICENSE_BUSY" and st["error"]["retryable"] is True


def test_no_solution_by_configured_pattern(make_service) -> None:
    st = _run(make_service("no_solution", no_solution_patterns=(r"no convergence",)))
    assert st["error"]["code"] == "NO_SOLUTION"


def test_nonzero_exit_is_failure_even_with_normal_stop(make_service) -> None:
    st = _run(make_service("nonzero"))
    assert st["state"] == "FAILED" and st["exit_code"] == 7


def test_incomplete_trend_is_failure(make_service) -> None:
    st = _run(make_service("incomplete"))
    assert st["state"] == "FAILED" and st["error"]["code"] == "INCOMPLETE_RESULT"


def test_failed_run_results_not_available(make_service) -> None:
    svc = make_service("fail")
    plan = prepare(svc)
    run = svc.start_run(plan["plan_id"], token_for(plan), "trace-1")
    wait_terminal(svc, run["run_id"])
    res = svc.read_run_results(run["run_id"], "trace-1")
    assert res["ok"] is False and res["error"]["code"] == "SIMULATION_FAILED"


def test_plan_expiry(make_service) -> None:
    svc = make_service(plan_ttl_s=0.01)
    plan = prepare(svc)
    time.sleep(0.05)
    assert svc.start_run(plan["plan_id"], token_for(plan), "trace-1")["error"]["code"] == "PLAN_EXPIRED"


def test_misconfigured_server_does_not_launch(make_service) -> None:
    svc = make_service(adapter_mode="real")
    plan = prepare(svc)
    res = svc.start_run(plan["plan_id"], token_for(plan), "trace-1")
    assert res["error"]["code"] == "SIMULATOR_UNAVAILABLE"
    assert run_dirs(svc) == []


def test_state_survives_server_restart(make_service) -> None:
    svc = make_service("slow")
    plan = prepare(svc)
    run = svc.start_run(plan["plan_id"], token_for(plan), "trace-1")
    fresh = OlgaService(svc.settings)  # «новый процесс сервера» без Popen-дескриптора
    assert fresh.get_run_status(run["run_id"], "trace-1")["state"] == "RUNNING"
    time.sleep(3)
    st = wait_terminal(fresh, run["run_id"])
    assert st["state"] == "SUCCEEDED"
    assert fresh.start_run(plan["plan_id"], token_for(plan), "trace-1")["run_id"] == run["run_id"]


def test_unknown_run(make_service) -> None:
    svc = make_service()
    assert svc.get_run_status("run_" + "1" * 32, "t")["error"]["code"] == "RUN_NOT_FOUND"
    assert svc.get_run_status("../x", "t")["error"]["code"] == "INVALID_INPUT"


def test_journal_links_events_and_hides_token(make_service) -> None:
    svc = make_service()
    plan = prepare(svc)
    tok = token_for(plan)
    run = svc.start_run(plan["plan_id"], tok, "trace-1")
    wait_terminal(svc, run["run_id"])
    svc.read_run_results(run["run_id"], "trace-1")
    text = svc.journal.path.read_text(encoding="utf-8")
    assert tok not in text and SECRET not in text
    events = [json.loads(line) for line in text.splitlines()]
    names = [e["event"] for e in events]
    for needed in ("plan_created", "approval_accepted", "kit_copied", "schedule_verified_in_copy",
                   "process_started", "process_exited", "run_finalized", "results_read"):
        assert needed in names, needed
    assert all(e.get("trace_id") == "trace-1" for e in events if e["event"] != "internal_error")
    started = next(e for e in events if e["event"] == "process_started")
    assert started["run_id"] == run["run_id"] and started["plan_id"] == plan["plan_id"]


def test_negative_time_leaves_no_start_in_journal(make_service) -> None:
    svc = make_service()
    res = prepare(svc, trace="neg-trace", event_time_s=-3600)
    assert res["error"]["code"] == "INVALID_INPUT"
    events = [json.loads(x) for x in svc.journal.path.read_text(encoding="utf-8").splitlines()]
    assert not any(e["event"] in ("process_started", "plan_created") for e in events)
    assert not any(e.get("tool") == "start_run" for e in events)


def test_token_helper_is_bound_to_plan() -> None:
    a = make_approval_token("s", "plan_a", "fp", "t")
    assert a != make_approval_token("s", "plan_b", "fp", "t")
    assert a != make_approval_token("s", "plan_a", "fp2", "t")
