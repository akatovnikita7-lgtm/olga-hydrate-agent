"""Извлечение намерения из пользовательского запроса."""

from .llm import request_structured
from .prompts import INTENT_PROMPT
from .schemas import BenchContext, RequestIntent


def parse_request(request: str, context: BenchContext) -> RequestIntent:
    if not request.strip():
        raise ValueError("Запрос не должен быть пустым.")

    return request_structured(
        context,
        [{"role": "system", "content": INTENT_PROMPT}, {"role": "user", "content": request}],
        RequestIntent,
    )
