"""Загрузка локальных настроек LLM."""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

from .schemas import BenchContext


_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_LLM_VARIABLES = ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY")


def load_context() -> BenchContext:
    """Прочитать настройки LLM из окружения и well-agent/.env."""
    load_dotenv(_ENV_FILE, override=False, interpolate=False)
    file_values = dotenv_values(_ENV_FILE, interpolate=False)
    settings = {name: os.environ.get(name, file_values.get(name)) for name in _LLM_VARIABLES}
    missing = [name for name, value in settings.items() if not (value or "").strip()]
    if missing:
        raise ValueError(f"Заполните настройки в well-agent/.env или окружении ({', '.join(missing)}).")

    return BenchContext(
        llm_base_url=settings["LLM_BASE_URL"],
        llm_model=settings["LLM_MODEL"],
        llm_api_key=settings["LLM_API_KEY"],
        mcp_timeout_s=120,
        mcp_case_id=os.environ.get("MCP_CASE_ID", file_values.get("MCP_CASE_ID")) or None,
    )
