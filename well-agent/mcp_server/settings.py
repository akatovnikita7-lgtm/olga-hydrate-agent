"""Настройки MCP-сервера из переменных окружения."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """Конфигурация локального адаптера симулятора."""

    simulator_name: str
    simulator_model_path: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            simulator_name=os.getenv("SIMULATOR_NAME", "not-configured"),
            simulator_model_path=os.getenv("SIMULATOR_MODEL_PATH"),
        )
