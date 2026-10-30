"""Тонкий адаптер к API инженерного симулятора."""

from typing import Any

from ..settings import Settings


class SimulatorNotConfigured(RuntimeError):
    """Проект ещё не подключён к выбранному симулятору."""


class SimulatorClient:
    """Заготовка клиента для OpenServer, Python API или другого SDK."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def status(self) -> dict[str, str | None]:
        """Вернуть состояние конфигурации без запуска расчёта."""
        configured = self._settings.simulator_name != "not-configured"
        return {
            "status": "configured" if configured else "not_configured",
            "simulator": self._settings.simulator_name,
            "model_path": self._settings.simulator_model_path,
        }

    def run_case(
        self,
        case_id: str,
        parameters: dict[str, float],
    ) -> dict[str, Any]:
        """Запустить один расчётный сценарий.

        TODO: замените тело вызовом выбранного ПО. Сохраняйте единицы во
        входной и выходной схемах, обрабатывайте таймаут и ошибки лицензии.
        """
        raise SimulatorNotConfigured(
            "Подключите API симулятора в mcp_server/simulator/client.py "
            f"перед запуском case_id={case_id!r}, parameters={parameters!r}."
        )
