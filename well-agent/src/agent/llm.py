"""Структурированный ответ модели через OpenAI-совместимый API."""

from typing import TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
)
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError

from .schemas import BenchContext


_Response = TypeVar("_Response", bound=BaseModel)


class LlmError(RuntimeError):
    """Ошибка LLM, которую можно показать пользователю."""


def request_structured(
    context: BenchContext,
    messages: list[ChatCompletionMessageParam],
    response_model: type[_Response],
) -> _Response:
    try:
        with OpenAI(
            base_url=context.llm_base_url,
            api_key=context.llm_api_key,
            timeout=20.0,
            max_retries=0,
        ) as client:
            response = client.chat.completions.create(
                model=context.llm_model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "strict": True,
                        "schema": response_model.model_json_schema(),
                    },
                },
            )
    except (AuthenticationError, PermissionDeniedError):
        raise LlmError("Провайдер LLM отклонил авторизацию или доступ к модели.") from None
    except NotFoundError:
        raise LlmError("Провайдер LLM не нашёл endpoint или модель. Проверьте LLM_BASE_URL и LLM_MODEL.") from None
    except APITimeoutError:
        raise LlmError("Истекло время ожидания ответа LLM.") from None
    except APIConnectionError:
        raise LlmError("Не удалось подключиться к LLM. Проверьте LLM_BASE_URL и сеть.") from None
    except APIStatusError as error:
        raise LlmError(f"LLM отклонила запрос (HTTP {error.status_code}).") from None
    except (OpenAIError, ValueError):
        raise LlmError("Ошибка настройки LLM или обработки ответа SDK.") from None

    content = response.choices[0].message.content if response.choices else None
    try:
        return response_model.model_validate_json(content or "")
    except ValidationError:
        raise LlmError("Ответ LLM не соответствует ожидаемой JSON Schema.") from None
