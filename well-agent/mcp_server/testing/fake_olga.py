"""ТЕСТОВЫЙ заменитель OLGA. НЕ ВЫПОЛНЯЕТ РАСЧЁТ.

Нужен только для проверки сервера и MCP-цепочки без лицензии OLGA. Пишет файлы
.out/.tpl в формате, похожем на OLGA, с явной пометкой FAKE. Числа синтетические
и не имеют физического смысла.

Использование: python fake_olga.py case1_obhod.genkey
Поведение задаётся переменной FAKE_OLGA_BEHAVIOR:
    ok (по умолчанию) | fail | license | no_solution | incomplete | slow | nonzero
FAKE_OLGA_SLEEP_S — длительность «расчёта» для slow (по умолчанию 3 с).
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

BRANCHES = ["SEPARATOR TUBE", "BYPASS", "MBSNU - AGZU 2", "PUMP TUBE - COPY", "MBSNU TUBE"]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: fake_olga.py <case.genkey>", file=sys.stderr)
        return 2
    genkey = Path(argv[1])
    behavior = os.getenv("FAKE_OLGA_BEHAVIOR", "ok")
    stem = genkey.stem
    text = genkey.read_text(encoding="utf-8")
    m = re.search(r"ENDTIME=([0-9.eE+-]+)\s*s", text)
    end = float(m.group(1)) if m else 345600.0

    if behavior == "slow":
        time.sleep(float(os.getenv("FAKE_OLGA_SLEEP_S", "3")))

    out_lines = [
        "FAKE OLGA TEST ADAPTER - THIS IS NOT A SIMULATION",
        "     VERSION         :   FAKE-OLGA test adapter (not OLGA)",
        f"     INPUT FILE      :   {genkey.name}",
    ]
    if behavior == "license":
        out_lines.append("FAKE LICENSE ERROR: no license available")
        Path(f"{stem}.out").write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        return 3
    if behavior == "no_solution":
        out_lines.append("FAKE SOLVER ERROR: no convergence")
        Path(f"{stem}.out").write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        return 4
    if behavior == "fail":
        Path(f"{stem}.out").write_text("\n".join(out_lines + ["unexpected failure"]) + "\n", encoding="utf-8")
        return 1

    last = end if behavior != "incomplete" else end / 2
    times = sorted({0.0, *[t for t in range(0, int(last) + 1, 3600)], last})
    catalog = [f"GT 'BOUNDARY:' 'BRANCH:' '{b}' 'PIPE:' 'PIPE-1' 'NR:' '2'  '(KG/S)' 'Total mass flow'" for b in BRANCHES]
    rows = []
    for t in times:
        after = t >= end / 2
        values = [0.0 if after else 10.0, 10.0 if after else 0.0, 10.0, 0.0 if after else -10.0, 10.0]
        rows.append(" ".join(f"{v:.6e}" for v in [t, *values]))
    tpl = ["'FAKE OLGA TEST ADAPTER'", "TIME PLOT", "CATALOG ", str(len(catalog)), *catalog, "TIME SERIES  ' (S)  '", *rows]
    Path(f"{stem}.tpl").write_text("\n".join(tpl) + "\n", encoding="utf-8")
    out_lines.append("     ****************  NORMAL STOP IN EXECUTION  ****************")
    Path(f"{stem}.out").write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return 7 if behavior == "nonzero" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
