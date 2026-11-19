"""Манифест сценария, отпечаток комплекта и обратное чтение расписания из .genkey."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ToolFailure

TIME_UNITS_TO_S = {"s": 1.0, "sec": 1.0, "min": 60.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
_SAFE_CASE_ID = re.compile(r"^[a-z0-9_]{1,64}$")


# ---------------------------------------------------------------- манифест
def load_manifest(cases_dir: Path, case_id: str, allowed_case_ids: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(case_id, str) or not _SAFE_CASE_ID.match(case_id):
        raise ToolFailure(
            "INVALID_INPUT",
            "case_id должен состоять из строчных латинских букв, цифр и _",
            field="case_id",
            received_value=case_id,
            expected_rule="^[a-z0-9_]{1,64}$",
        )
    if case_id not in allowed_case_ids:
        raise ToolFailure(
            "INVALID_INPUT",
            "неизвестный или неразрешённый case_id",
            field="case_id",
            received_value=case_id,
            expected_rule=f"один из {list(allowed_case_ids)}",
        )
    path = cases_dir / f"{case_id}.json"
    if not path.is_file():
        raise ToolFailure("CASE_KIT_INVALID", f"нет манифеста для {case_id}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- хеши
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def kit_hashes(kit_dir: Path, manifest: dict[str, Any]) -> dict[str, str]:
    """Хеши обязательных файлов комплекта. Отсутствующий файл -> CASE_KIT_INVALID."""
    hashes: dict[str, str] = {}
    for name in manifest["kit_files"]:
        p = kit_dir / name
        if not p.is_file():
            raise ToolFailure(
                "CASE_KIT_INVALID",
                f"в комплекте модели нет обязательного файла {name}",
                field="kit_files",
                received_value=name,
            )
        hashes[name] = sha256_file(p)
    return hashes


def fingerprint(hashes: dict[str, str]) -> str:
    payload = "\n".join(f"{k}:{hashes[k]}" for k in sorted(hashes))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def copy_kit(kit_dir: Path, dest: Path, manifest: dict[str, Any]) -> dict[str, str]:
    """Скопировать обязательные (и найденные необязательные) файлы. Вернуть хеши копий."""
    dest.mkdir(parents=True, exist_ok=False)
    for name in list(manifest["kit_files"]) + list(manifest.get("optional_kit_files", [])):
        src = kit_dir / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    return {name: sha256_file(dest / name) for name in manifest["kit_files"]}


# ---------------------------------------------------------------- .genkey
@dataclass(slots=True)
class KeyStatement:
    keyword: str
    params: dict[str, str]
    line_no: int


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    parts, buf, depth, quote = [], [], 0, False
    for ch in text:
        if ch == '"':
            quote = not quote
        elif not quote and ch == "(":
            depth += 1
        elif not quote and ch == ")":
            depth -= 1
        if ch == sep and depth == 0 and not quote:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def parse_genkey(text: str) -> list[KeyStatement]:
    """Минимальный разбор входного файла OLGA (.genkey).

    Достаточен для чтения расписания: склеивает строки с переносом ``\\``,
    пропускает комментарии ``!``, разбивает ``KEY=VALUE`` на верхнем уровне.
    """
    statements: list[KeyStatement] = []
    pending, start_line = "", 0
    for no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("!", 1)[0].rstrip()
        if not line.strip():
            continue
        if not pending:
            start_line = no
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        full = (pending + line).strip()
        pending = ""
        m = re.match(r"^([A-Z][A-Z0-9_]*)\s*(.*)$", full)
        if not m:
            continue
        keyword, rest = m.group(1), m.group(2)
        params: dict[str, str] = {}
        for part in _split_top_level(rest):
            if "=" in part:
                key, value = part.split("=", 1)
                params[key.strip().upper()] = value.strip()
        statements.append(KeyStatement(keyword, params, start_line))
    return statements


def parse_value(raw: str) -> tuple[list[float] | float | str, str | None]:
    """'(0, 172800, 172860) s' -> ([0.0, 172800.0, 172860.0], 's'); '345600 s' -> (345600.0, 's')."""
    raw = raw.strip()
    if raw.startswith('"'):
        return raw.strip('"'), None
    if raw.startswith("("):
        close = raw.index(")")
        inner, unit = raw[1:close], raw[close + 1 :].strip() or None
        return [float(x) for x in _split_top_level(inner)], unit
    parts = raw.split()
    try:
        number = float(parts[0])
    except ValueError:
        return raw, None
    return number, (parts[1] if len(parts) > 1 else None)


def _to_seconds(values: list[float], unit: str | None, where: str) -> list[float]:
    if unit is None:
        raise ToolFailure("UNIT_AMBIGUOUS", f"у времени {where} в модели не указана единица")
    factor = TIME_UNITS_TO_S.get(unit.lower())
    if factor is None:
        raise ToolFailure("UNIT_AMBIGUOUS", f"неизвестная единица времени {unit!r} у {where}")
    return [v * factor for v in values]


def _label(st: KeyStatement) -> str | None:
    raw = st.params.get("LABEL")
    return raw.strip('"') if raw else None


def read_schedule(genkey_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Обратное чтение расписания из .genkey и сверка с манифестом.

    Возвращает фактически прочитанные значения. Расхождение -> MODEL_SCHEDULE_MISMATCH.
    """
    statements = parse_genkey(genkey_path.read_text(encoding="utf-8", errors="replace"))
    sched = manifest["schedule"]
    expected_times = [0.0, float(sched["event_time_s"]), float(sched["transition_end_s"])]
    mismatches: list[str] = []
    found: dict[str, Any] = {}

    integ = [s for s in statements if s.keyword == "INTEGRATION"]
    if len(integ) != 1 or "ENDTIME" not in integ[0].params:
        raise ToolFailure("MODEL_SCHEDULE_MISMATCH", "в .genkey не найден INTEGRATION ENDTIME")
    end_val, end_unit = parse_value(integ[0].params["ENDTIME"])
    end_s = _to_seconds([float(end_val)], end_unit, "ENDTIME")[0]  # type: ignore[arg-type]
    found["end_time_s"] = end_s
    if abs(end_s - float(sched["end_time_s"])) > 1e-6:
        mismatches.append(f"ENDTIME={end_s} с, ожидалось {sched['end_time_s']} с")

    trend = [s for s in statements if s.keyword == "TREND" and "DTPLOT" in s.params]
    if trend:
        dt_val, dt_unit = parse_value(trend[0].params["DTPLOT"])
        if isinstance(dt_val, float):
            found["trend_dtplot_s"] = _to_seconds([dt_val], dt_unit, "DTPLOT")[0]

    found["objects"] = []
    for check in manifest["schedule_checks"]:
        matches = [
            s for s in statements if s.keyword == check["keyword"] and _label(s) == check["label"]
        ]
        if len(matches) != 1:
            mismatches.append(f"{check['label']}: найдено объектов {len(matches)}, ожидался 1")
            continue
        st = matches[0]
        if check["time_key"] not in st.params or check["value_key"] not in st.params:
            mismatches.append(f"{check['label']}: нет {check['time_key']}/{check['value_key']}")
            continue
        t_raw, t_unit = parse_value(st.params[check["time_key"]])
        v_raw, v_unit = parse_value(st.params[check["value_key"]])
        if not isinstance(t_raw, list) or not isinstance(v_raw, list):
            mismatches.append(f"{check['label']}: ожидались ряды значений")
            continue
        times = _to_seconds(t_raw, t_unit, check["label"])
        entry = {
            "object": check["object"],
            "time_s": times,
            check["value_key"].lower(): v_raw,
            "value_unit": v_unit or check.get("value_unit"),
            "line": st.line_no,
        }
        found["objects"].append(entry)
        if len(times) != len(expected_times) or any(
            abs(a - b) > 1e-6 for a, b in zip(times, expected_times)
        ):
            mismatches.append(f"{check['label']}: TIME={times} с, ожидалось {expected_times}")
        exp_vals = [float(x) for x in check["values"]]
        if len(v_raw) != len(exp_vals) or any(abs(a - b) > 1e-9 for a, b in zip(v_raw, exp_vals)):
            mismatches.append(f"{check['label']}: {check['value_key']}={v_raw}, ожидалось {exp_vals}")
        if check.get("value_unit") not in (None, "-") and v_unit != check["value_unit"]:
            mismatches.append(f"{check['label']}: единица {v_unit!r}, ожидалась {check['value_unit']!r}")

    if mismatches:
        raise ToolFailure(
            "MODEL_SCHEDULE_MISMATCH",
            "расписание в модели не совпадает с манифестом сценария",
            received_value=mismatches,
            expected_rule="расписание из cases/<case_id>.json",
        )
    return found
