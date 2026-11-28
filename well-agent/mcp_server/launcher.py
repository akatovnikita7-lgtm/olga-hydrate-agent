"""Запуск launcher OLGA и определение фактического окончания расчёта.

Команда формируется ТОЛЬКО из шаблона настроек (``OLGA_LAUNCHER`` +
``OLGA_LAUNCHER_ARGS``) с фиксированным набором плейсхолдеров; аргументы от LLM
сюда не попадают. ``shell=False``.

Успех = (код возврата 0, если он известен и требуется) И маркер нормальной
остановки в .out И тренд доходит до ENDTIME. Одного exit code недостаточно.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .errors import ToolFailure
from .settings import Settings


def build_argv(settings: Settings, model_dir: Path, run_dir: Path, input_file: str) -> list[str]:
    if settings.launcher is None or not settings.launcher.is_file():
        raise ToolFailure("SIMULATOR_UNAVAILABLE", "launcher OLGA не настроен или не найден")
    input_path = (model_dir / input_file).resolve()
    if input_path.parent != model_dir.resolve():
        raise ToolFailure("INVALID_INPUT", "входной файл вне каталога запуска", field="input_file")
    mapping = {
        "{input}": input_file,
        "{input_path}": str(input_path),
        "{run_dir}": str(run_dir),
        "{model_dir}": str(model_dir),
    }
    argv = [str(settings.launcher)]
    for template in settings.launcher_args:
        arg = template
        for key, value in mapping.items():
            arg = arg.replace(key, value)
        if "{" in arg or "}" in arg:
            raise ToolFailure("INVALID_INPUT", f"недопустимый плейсхолдер в шаблоне: {template!r}")
        argv.append(arg)
    return argv


def start_process(argv: list[str], cwd: Path, stdout_path: Path, stderr_path: Path) -> subprocess.Popen:
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":  # pragma: no cover - проверяется на машине с OLGA
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        # Отдельная сессия: закрытие MCP-клиента (killpg группы сервера) не убьёт расчёт.
        kwargs["start_new_session"] = True
    out = stdout_path.open("wb")
    err = stderr_path.open("wb")
    try:
        return subprocess.Popen(  # noqa: S603 - argv из разрешённого шаблона, shell=False
            argv, cwd=str(cwd), stdout=out, stderr=err, stdin=subprocess.DEVNULL, shell=False, **kwargs
        )
    finally:
        out.close()
        err.close()


def watch_process(proc: subprocess.Popen, on_exit: Callable[[int], None]) -> threading.Thread:
    def _wait() -> None:
        code = proc.wait()
        on_exit(code)

    thread = threading.Thread(target=_wait, name=f"olga-watch-{proc.pid}", daemon=True)
    thread.start()
    return thread


def pid_alive(pid: int | None) -> bool:
    """Проверить, жив ли процесс с данным pid (без его завершения)."""
    if not pid:
        return False
    if sys.platform == "win32":  # pragma: no cover
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # зомби-процесс (завершён, но не «собран») считаем завершённым
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return True


def _read_tail(path: Path, nbytes: int = 65536) -> str:
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - nbytes))
        return fh.read().decode("utf-8", errors="replace")


def tpl_last_time(path: Path) -> float | None:
    """Время последней записи тренда (.tpl). Читает только хвост файла."""
    if not path.is_file():
        return None
    for line in reversed(_read_tail(path).splitlines()):
        parts = line.split()
        if not parts:
            continue
        try:
            return float(parts[0])
        except ValueError:
            return None
    return None


def evaluate_outputs(model_dir: Path, manifest: dict[str, Any], started_epoch: float) -> dict[str, Any]:
    outputs = manifest["expected_outputs"]
    out_path = model_dir / outputs["out"]
    tpl_path = model_dir / outputs["trend"]
    end_time = float(manifest["schedule"]["end_time_s"])
    tol = float(manifest.get("end_time_tolerance_s", 20.0))
    info: dict[str, Any] = {
        "out_exists": out_path.is_file(),
        "trend_exists": tpl_path.is_file(),
        "normal_stop": False,
        "trend_last_time_s": None,
        "trend_complete": False,
        "outputs_fresh": False,
        "out_mtime_age_s": None,
    }
    if out_path.is_file():
        text = out_path.read_text(encoding="utf-8", errors="replace")
        info["normal_stop"] = manifest["normal_stop_marker"] in text
        mtime = out_path.stat().st_mtime
        info["out_mtime_age_s"] = round(time.time() - mtime, 1)
        info["outputs_fresh"] = mtime >= started_epoch - 1.0
    last = tpl_last_time(tpl_path)
    info["trend_last_time_s"] = last
    info["trend_complete"] = last is not None and last >= end_time - tol
    if tpl_path.is_file():
        info["outputs_fresh"] = info["outputs_fresh"] and tpl_path.stat().st_mtime >= started_epoch - 1.0
    return info


def diagnostics_text(model_dir: Path, run_dir: Path, manifest: dict[str, Any]) -> str:
    chunks = []
    for path in (
        model_dir / manifest["expected_outputs"]["out"],
        run_dir / "launcher_stdout.log",
        run_dir / "launcher_stderr.log",
    ):
        if path.is_file():
            chunks.append(_read_tail(path, 32768))
    return "\n".join(chunks)


def classify_failure(text: str, settings: Settings) -> tuple[str, str]:
    """Код ошибки по ПОДТВЕРЖДЁННЫМ шаблонам из настроек; иначе SIMULATION_FAILED."""
    for pattern in settings.license_error_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return "LICENSE_BUSY", f"найден признак ошибки лицензии: /{pattern}/"
    for pattern in settings.no_solution_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return "NO_SOLUTION", f"найден признак отсутствия решения: /{pattern}/"
    return "SIMULATION_FAILED", "расчёт не завершился нормально; см. хвост журнала решателя"
