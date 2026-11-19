"""Клиентский JSONL одного запроса."""
import json
import math
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from uuid import uuid4

from pydantic import BaseModel


_SENSITIVE = re.compile(r"authorization|api[-_ ]?key|token|password|secret|cookie", re.I)
# Заголовки и присваивания могут встретиться в запросе или тексте ошибки.
_ASSIGNMENT = re.compile(
    r"""(?ix)(["']?[\w-]*(?:authorization|api[_-]?key|token|password|secret|cookie)["']?\s*[:=]\s*)"""
    r"""(?:(?:bearer|basic)\s+)?(?:"[^"]*"|'[^']*'|[^\s,;}]+)"""
)
_CREDENTIAL = re.compile(r"(?i)\b(?:Bearer\s+\S+|(?:gsk_|sk-|github_pat_|ghp_)[\w-]+)")


class Journal:
    def __init__(self, directory: Path, api_key: str):
        self.trace_id = uuid4().hex
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{self.trace_id}.jsonl"
        self.secrets = {api_key} if api_key else set()
        self.plan_id = None
        self.run_id = None
        self.path.touch(mode=0o600, exist_ok=False)

    def clean(self, value):
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json", by_alias=True)
        if isinstance(value, dict):
            return {
                key: "[скрыто]" if _SENSITIVE.search(key) else self.clean(item)
                for key, item in value.items()
            }
        if isinstance(value, (tuple, list)):
            return [self.clean(item) for item in value]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[скрыто]")
            return _CREDENTIAL.sub("[скрыто]", _ASSIGNMENT.sub(r"\1[скрыто]", value))
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return value

    def write(self, event, *, component="client", **fields):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": self.trace_id, "component": component, "event": event,
        }
        if self.plan_id:
            record["plan_id"] = self.plan_id
        if self.run_id:
            record["run_id"] = self.run_id
        record.update(fields)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(self.clean(record), ensure_ascii=False, allow_nan=False) + "\n")

    @contextmanager
    def call(self, component, tool, arguments):
        fields = dict(component=component, tool=tool, call_id=uuid4().hex)
        self.write("call", arguments=arguments, **fields)
        started = monotonic()
        response = {}
        try:
            yield response
        except BaseException as exc:
            response["error"] = str(exc) or type(exc).__name__
            raise
        finally:
            self.write("response", duration_ms=round((monotonic() - started) * 1000), **response, **fields)
