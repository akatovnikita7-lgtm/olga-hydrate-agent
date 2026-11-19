"""Подключение модуля анализа результатов (участник 3).

Сервер НЕ считает метрики сам. Он вызывает функцию, указанную в настройке
``OLGA_RESULTS_ANALYZER`` (по умолчанию ``src.results:analyze_run``), с сигнатурой::

    analyze_run(model_dir: Path, manifest: dict, run_info: dict) -> dict

Ожидаемые ключи ответа: ``metrics`` (список метрик формата стр. 8),
``series`` (необязательно), ``assessment`` ({"status": OK|OUT_OF_TOLERANCE|NOT_ASSESSED, ...}),
``artifacts`` (пути к графикам и т. п. внутри каталога запуска).

Пока модуля нет, возвращается NOT_ASSESSED с явной причиной — без выдуманных чисел.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

from .errors import ToolFailure

Analyzer = Callable[[Path, dict[str, Any], dict[str, Any]], dict[str, Any]]


def load_analyzer(spec: str) -> Analyzer | None:
    module_name, _, func_name = spec.partition(":")
    if not module_name or not func_name:
        return None
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and module_name.startswith(exc.name):
            return None  # модуль ещё не создан
        raise
    func = getattr(module, func_name, None)
    return func if callable(func) else None


def trend_catalog(tpl_path: Path) -> dict[str, Any]:
    """Описание каталога переменных .tpl (без чтения рядов)."""
    with tpl_path.open(encoding="utf-8", errors="replace") as fh:
        lines = []
        for line in fh:
            lines.append(line.rstrip("\r\n"))
            if line.startswith("TIME SERIES"):
                break
            if len(lines) > 5000:
                break
    try:
        idx = lines.index("CATALOG ") if "CATALOG " in lines else lines.index("CATALOG")
        count = int(lines[idx + 1])
    except (ValueError, IndexError) as exc:
        raise ToolFailure("RESULT_PARSE_ERROR", "в .tpl не найден блок CATALOG") from exc
    entries = lines[idx + 2 : idx + 2 + count]
    variables = sorted({e.split()[0] for e in entries if e.strip()})
    return {"variables_count": count, "variable_names": variables, "header": lines[0] if lines else None}


def analyze(spec: str, model_dir: Path, manifest: dict[str, Any], run_info: dict[str, Any]) -> dict[str, Any]:
    tpl = model_dir / manifest["expected_outputs"]["trend"]
    catalog = trend_catalog(tpl)
    analyzer = load_analyzer(spec)
    if analyzer is None:
        return {
            "analyzer": None,
            "trend_catalog": catalog,
            "metrics": [],
            "series": [],
            "assessment": {
                "status": "NOT_ASSESSED",
                "reason": f"модуль анализа результатов ({spec}) ещё не подключён",
            },
            "artifacts": [],
        }
    try:
        result = analyzer(model_dir, manifest, run_info)
    except ToolFailure:
        raise
    except Exception as exc:  # noqa: BLE001 - отдаём структурированную ошибку
        raise ToolFailure(
            "RESULT_PARSE_ERROR", f"анализатор результатов завершился ошибкой: {type(exc).__name__}"
        ) from exc
    if not isinstance(result, dict) or "assessment" not in result:
        raise ToolFailure("RESULT_PARSE_ERROR", "анализатор вернул ответ без поля assessment")
    result.setdefault("trend_catalog", catalog)
    result["analyzer"] = spec
    return result
