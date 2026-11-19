"""Настройки MCP-сервера OLGA.

Источники (по убыванию приоритета):
1. переменные окружения ``OLGA_*``;
2. JSON-файл, путь к которому задан в ``OLGA_SERVER_CONFIG``.

Файл ``.env`` сервер сам НЕ читает: переменные нужно задать в оболочке или
передать в ``StdioServerParameters(env=...)`` со стороны клиента.

Состояние ``configured`` означает только то, что пути заданы и файлы на месте.
Оно не доказывает доступность лицензии OLGA.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

AdapterMode = Literal["real", "fake", "not_configured"]

WELL_AGENT_DIR = Path(__file__).resolve().parent.parent
CASES_DIR = Path(__file__).resolve().parent / "cases"

# Плейсхолдеры, которые разрешено использовать в шаблоне аргументов launcher.
ALLOWED_PLACEHOLDERS = ("{input}", "{input_path}", "{run_dir}", "{model_dir}")


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("ожидался JSON-список строк")
            return [str(v) for v in parsed]
        return [text]
    raise ValueError(f"ожидался список строк, получено {type(value).__name__}")


def _as_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "да"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Конфигурация адаптера OLGA."""

    adapter_mode: AdapterMode = "not_configured"
    case_kit_dir: Path | None = None
    launcher: Path | None = None
    launcher_args: tuple[str, ...] = ()
    runs_root: Path = WELL_AGENT_DIR / "runs"
    log_dir: Path = WELL_AGENT_DIR / "logs"
    run_timeout_s: float = 3600.0
    max_concurrent_runs: int = 1
    plan_ttl_s: float = 3600.0
    approval_secret: str | None = field(default=None, repr=False)
    require_zero_exit_code: bool = True
    launcher_detaches: bool = False
    stale_output_after_s: float = 300.0
    license_error_patterns: tuple[str, ...] = ()
    no_solution_patterns: tuple[str, ...] = ()
    results_analyzer: str = "src.results:analyze_run"
    allowed_case_ids: tuple[str, ...] = ("mbsnu_bypass_96h",)
    cases_dir: Path = CASES_DIR

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if environ is None else environ)
        file_cfg: dict[str, Any] = {}
        cfg_path = env.get("OLGA_SERVER_CONFIG")
        if cfg_path:
            file_cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))

        def get(key: str, env_key: str) -> Any:
            if env.get(env_key) not in (None, ""):
                return env[env_key]
            return file_cfg.get(key)

        def path(key: str, env_key: str, default: Path | None = None) -> Path | None:
            raw = get(key, env_key)
            return Path(raw).expanduser().resolve() if raw else default

        mode = str(get("adapter_mode", "OLGA_ADAPTER_MODE") or "not_configured").lower()
        if mode not in ("real", "fake", "not_configured"):
            raise ValueError(f"OLGA_ADAPTER_MODE должен быть real или fake, получено {mode!r}")

        return cls(
            adapter_mode=mode,  # type: ignore[arg-type]
            case_kit_dir=path("case_kit_dir", "OLGA_CASE_KIT_DIR"),
            launcher=path("launcher", "OLGA_LAUNCHER"),
            launcher_args=tuple(_as_list(get("launcher_args", "OLGA_LAUNCHER_ARGS"))),
            runs_root=path("runs_root", "OLGA_RUNS_ROOT", WELL_AGENT_DIR / "runs"),  # type: ignore[arg-type]
            log_dir=path("log_dir", "OLGA_LOG_DIR", WELL_AGENT_DIR / "logs"),  # type: ignore[arg-type]
            run_timeout_s=float(get("run_timeout_s", "OLGA_RUN_TIMEOUT_S") or 3600),
            max_concurrent_runs=int(get("max_concurrent_runs", "OLGA_MAX_CONCURRENT_RUNS") or 1),
            plan_ttl_s=float(get("plan_ttl_s", "OLGA_PLAN_TTL_S") or 3600),
            approval_secret=get("approval_secret", "OLGA_APPROVAL_SECRET") or None,
            require_zero_exit_code=_as_bool(
                get("require_zero_exit_code", "OLGA_REQUIRE_ZERO_EXIT_CODE"), True
            ),
            launcher_detaches=_as_bool(get("launcher_detaches", "OLGA_LAUNCHER_DETACHES"), False),
            stale_output_after_s=float(
                get("stale_output_after_s", "OLGA_STALE_OUTPUT_AFTER_S") or 300
            ),
            license_error_patterns=tuple(
                _as_list(get("license_error_patterns", "OLGA_LICENSE_ERROR_PATTERNS"))
            ),
            no_solution_patterns=tuple(
                _as_list(get("no_solution_patterns", "OLGA_NO_SOLUTION_PATTERNS"))
            ),
            results_analyzer=str(
                get("results_analyzer", "OLGA_RESULTS_ANALYZER") or "src.results:analyze_run"
            ),
        )

    def problems(self) -> list[str]:
        """Перечень проблем конфигурации (пусто, если всё задано)."""
        issues: list[str] = []
        if self.adapter_mode == "not_configured":
            issues.append("OLGA_ADAPTER_MODE не задан (real или fake)")
        if self.case_kit_dir is None:
            issues.append("OLGA_CASE_KIT_DIR не задан")
        elif not self.case_kit_dir.is_dir():
            issues.append("каталог комплекта модели не найден")
        if self.launcher is None:
            issues.append("OLGA_LAUNCHER не задан")
        elif not self.launcher.is_file():
            issues.append("файл launcher не найден")
        if not self.launcher_args:
            issues.append("OLGA_LAUNCHER_ARGS не задан (JSON-список, например [\"{input}\"])")
        for arg in self.launcher_args:
            stripped = arg
            for ph in ALLOWED_PLACEHOLDERS:
                stripped = stripped.replace(ph, "")
            if "{" in stripped or "}" in stripped:
                issues.append(f"недопустимый плейсхолдер в OLGA_LAUNCHER_ARGS: {arg!r}")
        if not self.approval_secret:
            issues.append("OLGA_APPROVAL_SECRET не задан: подтверждение запуска невозможно")
        if self.max_concurrent_runs < 1:
            issues.append("OLGA_MAX_CONCURRENT_RUNS должен быть >= 1")
        if self.run_timeout_s <= 0:
            issues.append("OLGA_RUN_TIMEOUT_S должен быть > 0")
        command_text = " ".join(
            [self.launcher.name if self.launcher else "", *self.launcher_args]
        ).lower()
        uses_fake = "fake_olga" in command_text
        if self.adapter_mode == "real" and uses_fake:
            issues.append("в режиме real указан тестовый fake_olga: подмена OLGA запрещена")
        if self.adapter_mode == "fake" and not uses_fake:
            issues.append("в режиме fake разрешён только тестовый fake_olga")
        return issues

    def public_view(self) -> dict[str, Any]:
        """Безопасное описание настроек: без секрета и без полных локальных путей."""
        return {
            "adapter_mode": self.adapter_mode,
            "case_kit_dir_set": self.case_kit_dir is not None,
            "launcher_name": self.launcher.name if self.launcher else None,
            "launcher_args_template": [
                f"<path>/{Path(a).name}" if Path(a).is_absolute() else a for a in self.launcher_args
            ],
            "run_timeout_s": self.run_timeout_s,
            "max_concurrent_runs": self.max_concurrent_runs,
            "plan_ttl_s": self.plan_ttl_s,
            "approval_secret_set": bool(self.approval_secret),
            "require_zero_exit_code": self.require_zero_exit_code,
            "launcher_detaches": self.launcher_detaches,
            "license_error_patterns": list(self.license_error_patterns),
            "no_solution_patterns": list(self.no_solution_patterns),
            "results_analyzer": self.results_analyzer,
        }
