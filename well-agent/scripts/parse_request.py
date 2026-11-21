"""Проверить разбор запроса к OLGA отдельно от MCP."""

import argparse
import sys

from src.agent.config import load_context
from src.agent.intent import parse_request
from src.agent.llm import LlmError


def main() -> int:
    parser = argparse.ArgumentParser(description="Извлечь параметры запроса на расчёт обхода МБСНУ.")
    parser.add_argument("request", help="Текст запроса")
    args = parser.parse_args()

    try:
        intent = parse_request(args.request, load_context())
    except (LlmError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    print(intent.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
