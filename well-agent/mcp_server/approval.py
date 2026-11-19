"""Токен подтверждения запуска.

Токен = HMAC-SHA256(секрет, plan_id | model_fingerprint | trace_id).

* Секрет ``OLGA_APPROVAL_SECRET`` знают только доверенный код клиента (CLI
  участника 1) и сервер. Его нельзя передавать LLM и печатать в журнал.
* CLI вычисляет токен ТОЛЬКО после явного «да» человека и передаёт его в
  ``start_run``. LLM не может сама выдать себе разрешение: секрета у неё нет.
* Токен привязан к плану, отпечатку модели и trace_id: смена модели или плана
  делает старое подтверждение недействительным.

Модуль использует только стандартную библиотеку, поэтому клиент может
импортировать ``make_approval_token`` без зависимостей сервера.
"""

from __future__ import annotations

import hashlib
import hmac


def approval_message(plan_id: str, model_fingerprint: str, trace_id: str) -> bytes:
    return f"olga-approval/v1|{plan_id}|{model_fingerprint}|{trace_id}".encode("utf-8")


def make_approval_token(secret: str, plan_id: str, model_fingerprint: str, trace_id: str) -> str:
    if not secret:
        raise ValueError("секрет подтверждения не задан")
    digest = hmac.new(
        secret.encode("utf-8"), approval_message(plan_id, model_fingerprint, trace_id), hashlib.sha256
    )
    return digest.hexdigest()


def verify_approval_token(
    secret: str, token: str | None, plan_id: str, model_fingerprint: str, trace_id: str
) -> bool:
    if not secret or not token:
        return False
    expected = make_approval_token(secret, plan_id, model_fingerprint, trace_id)
    return hmac.compare_digest(expected, token)
