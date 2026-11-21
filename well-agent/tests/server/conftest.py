"""Общие фикстуры серверных тестов.

Используется СИНТЕТИЧЕСКИЙ мини-комплект (не реальная модель) и тестовый
fake_olga. Все тесты здесь проверяют сервер, а не OLGA.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from mcp_server.approval import make_approval_token
from mcp_server.service import OlgaService
from mcp_server.settings import Settings

WELL_AGENT = Path(__file__).resolve().parents[2]
FAKE_OLGA = WELL_AGENT / "mcp_server" / "testing" / "fake_olga.py"
CASE = "mbsnu_bypass_96h"
SECRET = "test-secret"

SYNTHETIC_GENKEY = """\
! синтетический комплект для тестов сервера
OPTIONS TEMPERATURE=ADIABATIC, FLOWMODEL=OLGAHD
FILES PVTFILE=./Novosam_T1_HeaderFix.tab
INTEGRATION ENDTIME=96 h, MAXDT=3600 s, MINDT=0.001 s, STARTTIME=0 s, DTSTART=600 s
TREND DTPLOT=10 s
NETWORKCOMPONENT TYPE=FLOWPATH, TAG=FLOWPATH_1
 PARAMETERS LABEL=ByPass
 VALVE LABEL="VALVE-2", MODEL=HYDROVALVE, TIME=(0, 172800, 172860) s, ABSPOSITION=10 m, \\
        OPENING=(0, 0, 1), PHASE=LIQUID
ENDNETWORKCOMPONENT
NETWORKCOMPONENT TYPE=FLOWPATH, TAG=FLOWPATH_6
 PARAMETERS LABEL="Separator Tube"
 VALVE LABEL="VALVE Separator", MODEL=HYDROVALVE, TIME=(0, 48, 48.0166666667) h, ABSPOSITION=10 m, \\
        OPENING=(1, 1, 0), PHASE=LIQUID
ENDNETWORKCOMPONENT
NETWORKCOMPONENT TYPE=NODE, TAG=NODE_7
 PARAMETERS LABEL=Pump, TYPE=MASSFLOW, TOTALWATERFRACTION=(0.16912, 0.16912, 0.16912) -, \\
        GASFRACTION=(0, 0, 0) -, MASSFLOW=(9.989051, 9.989051, 0) kg/s, TEMPERATURE=(23, \\
        23, 23) C, TIME=(0, 172800, 172860) s
ENDNETWORKCOMPONENT
ENDCASE
"""


@pytest.fixture()
def kit(tmp_path: Path) -> Path:
    d = tmp_path / "kit"
    d.mkdir()
    (d / "case1_obhod.genkey").write_text(SYNTHETIC_GENKEY, encoding="utf-8")
    (d / "Novosam_T1_HeaderFix.tab").write_text("synthetic pvt table\n", encoding="utf-8")
    return d


@pytest.fixture()
def make_service(tmp_path: Path, kit: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., OlgaService]:
    def factory(behavior: str = "ok", **overrides: Any) -> OlgaService:
        monkeypatch.setenv("FAKE_OLGA_BEHAVIOR", behavior)
        monkeypatch.setenv("FAKE_OLGA_SLEEP_S", "2")
        params: dict[str, Any] = dict(
            adapter_mode="fake",
            case_kit_dir=kit,
            launcher=Path(sys.executable),
            launcher_args=(str(FAKE_OLGA), "{input}"),
            runs_root=tmp_path / "runs",
            log_dir=tmp_path / "logs",
            approval_secret=SECRET,
            run_timeout_s=600,
        )
        params.update(overrides)
        return OlgaService(Settings(**params))

    return factory


def prepare(svc: OlgaService, trace: str = "trace-1", **times: float) -> dict[str, Any]:
    args = {"event_time_s": 172800, "transition_s": 60, "end_time_s": 345600, **times}
    return svc.prepare_scenario(CASE, trace_id=trace, **args)


def token_for(plan: dict[str, Any], trace: str = "trace-1") -> str:
    return make_approval_token(SECRET, plan["plan_id"], plan["model_fingerprint"], trace)


def wait_terminal(svc: OlgaService, run_id: str, trace: str = "trace-1", timeout: float = 30) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = svc.get_run_status(run_id, trace)
        if st.get("state") not in ("QUEUED", "RUNNING"):
            return st
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} не завершился за {timeout} с")


def run_dirs(svc: OlgaService) -> list[Path]:
    root = svc.settings.runs_root
    return sorted(root.glob("run_*")) if root.exists() else []
