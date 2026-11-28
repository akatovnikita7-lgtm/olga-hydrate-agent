"""Серверный журнал JSONL: одна строка — одно событие.

stdout stdio-сервера занят протоколом MCP, поэтому журнал пишется в файл,
а служебные сообщения logging — в stderr.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import _jsonable

COMPONENT = "mcp_server"
SECRET_KEYS = {"approval_token", "approval_secret", "api_key", "authorization", "password"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sanitize(value: Any) -> Any:
    """Убрать секреты из аргументов и результатов перед записью."""
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS:
                clean[key] = "***" if item else item
            else:
                clean[key] = sanitize(item)
        return clean
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    return _jsonable(value)


class Journal:
    def __init__(self, log_dir: Path, filename: str = "server.jsonl") -> None:
        self.path = Path(log_dir) / filename
        self._lock = threading.Lock()

    def write(self, event: str, **fields: Any) -> dict[str, Any]:
        record: dict[str, Any] = {"timestamp": utc_now(), "component": COMPONENT, "event": event}
        record.update({k: sanitize(v) for k, v in fields.items() if v is not None})
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return record
