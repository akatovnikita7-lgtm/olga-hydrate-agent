"""Сервер сам отклоняет некорректный вход ДО создания процесса (обход клиентской валидации)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from mcp_server import case_kit
from mcp_server.settings import Settings

from .conftest import CASE, prepare, run_dirs


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_time_s", -3600),
        ("event_time_s", -1e-9),
        ("transition_s", 0),
        ("transition_s", -60),
        ("end_time_s", 0),
        ("event_time_s", math.nan),
        ("event_time_s", math.inf),
        ("event_time_s", "172800"),
        ("event_time_s", True),
        ("event_time_s", None),
    ],
)
def test_invalid_times_rejected_before_plan(make_service, field, value) -> None:
    svc = make_service()
    res = prepare(svc, **{field: value})
    assert res["ok"] is False
    assert res["error"]["code"] == "INVALID_INPUT"
    assert res["error"]["field"] == field
    assert run_dirs(svc) == []
    assert not (svc.registry.plans_dir.exists() and any(svc.registry.plans_dir.iterdir()))


def test_transition_must_end_before_simulation_end(make_service) -> None:
    res = prepare(make_service(), event_time_s=345590, transition_s=60)
    assert res["error"]["code"] == "INVALID_INPUT"
    assert res["error"]["expected_rule"] == "event_time_s + transition_s < end_time_s"


def test_other_valid_time_is_unsupported_not_silently_replaced(make_service) -> None:
    res = prepare(make_service(), event_time_s=36000)
    assert res["ok"] is False
    assert res["error"]["code"] == "UNSUPPORTED_SCENARIO_PARAMETER"
    assert res["error"]["received_value"] == 36000.0


@pytest.mark.parametrize("case_id", ["unknown_case", "../mbsnu_bypass_96h", "", "MBSNU"])
def test_unknown_case_id(make_service, case_id) -> None:
    res = make_service().prepare_scenario(case_id, 172800, 60, 345600, trace_id="t")
    assert res["error"]["code"] == "INVALID_INPUT"
    assert res["error"]["field"] == "case_id"


def test_trace_id_required(make_service) -> None:
    res = make_service().prepare_scenario(CASE, 172800, 60, 345600, trace_id="")
    assert res["error"]["code"] == "INVALID_INPUT"
    assert res["error"]["field"] == "trace_id"


def test_valid_plan_reads_schedule_from_model(make_service) -> None:
    res = prepare(make_service())
    assert res["ok"] is True, res
    assert res["requires_approval"] is True
    assert res["model_changes"] == []
    assert res["normalized_parameters"]["transition_end_s"] == 172860
    objects = {o["object"]: o for o in res["schedule_read_from_model"]["objects"]}
    assert objects["VALVE Separator"]["time_s"] == pytest.approx([0, 172800, 172860])  # из часов
    assert res["schedule_read_from_model"]["end_time_s"] == 345600


def test_schedule_mismatch_in_model_is_reported(make_service, kit: Path) -> None:
    genkey = kit / "case1_obhod.genkey"
    genkey.write_text(genkey.read_text(encoding="utf-8").replace("OPENING=(0, 0, 1)", "OPENING=(0, 0, 0.5)"))
    res = prepare(make_service())
    assert res["error"]["code"] == "MODEL_SCHEDULE_MISMATCH"
    assert any("VALVE-2" in m for m in res["error"]["received_value"])


def test_missing_kit_file(make_service, kit: Path) -> None:
    (kit / "Novosam_T1_HeaderFix.tab").unlink()
    assert prepare(make_service())["error"]["code"] == "CASE_KIT_INVALID"


def test_genkey_parser_handles_continuations_and_units() -> None:
    from .conftest import SYNTHETIC_GENKEY

    sts = case_kit.parse_genkey(SYNTHETIC_GENKEY)
    pump = next(s for s in sts if s.keyword == "PARAMETERS" and s.params.get("LABEL") == "Pump")
    assert case_kit.parse_value(pump.params["MASSFLOW"]) == ([9.989051, 9.989051, 0.0], "kg/s")
    assert case_kit.parse_value(pump.params["TEMPERATURE"]) == ([23.0, 23.0, 23.0], "C")


def test_settings_reject_unknown_placeholder(kit: Path) -> None:
    s = Settings(adapter_mode="fake", case_kit_dir=kit, launcher=Path(__file__),
                 launcher_args=("fake_olga.py", "{anything}"), approval_secret="x")
    assert any("плейсхолдер" in p for p in s.problems())


def test_real_mode_refuses_fake_launcher(make_service) -> None:
    svc = make_service(adapter_mode="real")
    assert any("fake_olga" in p for p in svc.settings.problems())
    plan = prepare(svc)
    assert plan["ok"] is True and plan["ready_to_run"] is False
