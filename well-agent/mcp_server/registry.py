"""Устойчивое хранение планов и запусков в JSON-файлах.

Структура каталога runs/:
    runs/_registry/plans/<plan_id>.json     план (неизменяемая часть + run_id после запуска)
    runs/_registry/plans/<plan_id>.claim    атомарная «занятость» плана: содержит run_id
    runs/<run_id>/run.json                  запись запуска (состояние, pid, коды, время)
    runs/<run_id>/model/                    копия комплекта, здесь работает OLGA
    runs/<run_id>/launcher_stdout.log, launcher_stderr.log

Потеря соединения клиента не стирает run_id: всё лежит на диске.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

_ID = re.compile(r"^(plan|run)_[0-9a-f]{32}$")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def is_valid_id(value: Any, prefix: str) -> bool:
    return isinstance(value, str) and bool(_ID.match(value)) and value.startswith(prefix + "_")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}_{threading.get_ident()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class Registry:
    def __init__(self, runs_root: Path) -> None:
        self.root = Path(runs_root).resolve()
        self.plans_dir = self.root / "_registry" / "plans"
        self._lock = threading.RLock()

    # ---- планы
    def save_plan(self, plan: dict[str, Any]) -> None:
        with self._lock:
            _atomic_write_json(self.plans_dir / f"{plan['plan_id']}.json", plan)

    def load_plan(self, plan_id: str) -> dict[str, Any] | None:
        if not is_valid_id(plan_id, "plan"):
            return None
        path = self.plans_dir / f"{plan_id}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def claim_plan(self, plan_id: str, run_id: str) -> tuple[bool, str]:
        """Атомарно закрепить план за run_id. Вернуть (успех, run_id владельца).

        Работает и между разными процессами сервера (O_CREAT | O_EXCL).
        """
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        claim = self.plans_dir / f"{plan_id}.claim"
        try:
            fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False, claim.read_text(encoding="utf-8").strip()
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(run_id)
        return True, run_id

    def release_claim(self, plan_id: str, run_id: str) -> None:
        """Снять закрепление, если запуск не был создан (например, нет launcher)."""
        claim = self.plans_dir / f"{plan_id}.claim"
        if claim.is_file() and claim.read_text(encoding="utf-8").strip() == run_id:
            claim.unlink()

    def claimed_run(self, plan_id: str) -> str | None:
        claim = self.plans_dir / f"{plan_id}.claim"
        return claim.read_text(encoding="utf-8").strip() if claim.is_file() else None

    # ---- запуски
    def run_dir(self, run_id: str) -> Path:
        if not is_valid_id(run_id, "run"):
            raise ValueError("некорректный run_id")
        path = (self.root / run_id).resolve()
        if path.parent != self.root:
            raise ValueError("run_id вне каталога runs")
        return path

    def save_run(self, run: dict[str, Any]) -> None:
        with self._lock:
            _atomic_write_json(self.run_dir(run["run_id"]) / "run.json", run)

    def load_run(self, run_id: str) -> dict[str, Any] | None:
        if not is_valid_id(run_id, "run"):
            return None
        path = self.run_dir(run_id) / "run.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def update_run(self, run_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            run = self.load_run(run_id) or {"run_id": run_id}
            run.update(changes)
            self.save_run(run)
            return run

    def all_runs(self) -> list[dict[str, Any]]:
        runs = []
        if not self.root.is_dir():
            return runs
        for path in self.root.glob("run_*/run.json"):
            try:
                runs.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return runs
