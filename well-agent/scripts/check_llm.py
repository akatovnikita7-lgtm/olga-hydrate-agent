"""Проверить доступ к LLM и поддержку строгого структурированного ответа."""

import sys

from pydantic import BaseModel, ConfigDict

from src.agent.config import load_context
from src.agent.llm import LlmError, request_structured


class CheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: int


def main() -> int:
    try:
        context = load_context()
        answer = request_structured(
            context,
            [{"role": "user", "content": "Чему равно 2 + 2? Верни число в поле result."}],
            CheckResponse,
        )
    except (LlmError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    if answer.result != 4:
        print("LLM вернула неверный результат проверки.", file=sys.stderr)
        return 1

    print(f"LLM доступна. Модель {context.llm_model}, результат по JSON Schema — {answer.result}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
