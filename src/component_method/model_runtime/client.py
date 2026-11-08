"""Framework-independent client for bounded single-response model calls."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import hashlib
import importlib.metadata
import json
from typing import Any, Generic, TypeVar

from openai import OpenAI


T = TypeVar("T")
JsonValidator = Callable[[dict[str, Any]], T]


def _request_model_name(model: str) -> str:
    value = model.strip()
    if value.startswith("openai/"):
        value = value.removeprefix("openai/")
    if not value:
        raise ValueError("model must not be empty")
    return value


def _json_object(content: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for match_index, character in enumerate(content):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(content[match_index:])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("model response contains no JSON object")


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class ModelResult(Generic[T]):
    content: str
    value: T
    model_calls: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    reported_cost_usd: float | None
    attempts: tuple[dict[str, Any], ...]
    runtime_identity: dict[str, Any]


class ModelValidationError(ValueError):
    """Raised after all bounded JSON validation attempts are exhausted."""

    def __init__(
        self,
        message: str,
        *,
        attempts: tuple[dict[str, Any], ...],
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens


class ModelClient:
    """Issue bounded chat-completion requests and validate JSON responses."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 600,
        transport_retries: int = 0,
        max_output_tokens: int = 2_048,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not base_url:
            raise ValueError("base_url is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if transport_retries < 0:
            raise ValueError("transport_retries must not be negative")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        self.base_url = base_url.rstrip("/")
        self.configured_model = model
        self.request_model = _request_model_name(model)
        self.timeout_seconds = timeout_seconds
        self.transport_retries = transport_retries
        self.max_output_tokens = max_output_tokens
        self._owns_client = client is None
        self._client = client or OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=timeout_seconds,
            max_retries=transport_retries,
        )

    def runtime_identity(self) -> dict[str, Any]:
        try:
            sdk_version = importlib.metadata.version("openai")
        except importlib.metadata.PackageNotFoundError:
            sdk_version = None
        return {
            "client": "openai_compatible",
            "openai_sdk_version": sdk_version,
            "configured_model": self.configured_model,
            "request_model": self.request_model,
            "base_url_sha256": hashlib.sha256(self.base_url.encode()).hexdigest(),
            "timeout_seconds": self.timeout_seconds,
            "transport_retries": self.transport_retries,
            "max_output_tokens": self.max_output_tokens,
        }

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "ModelClient":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def complete_json(
        self,
        messages: Iterable[Mapping[str, Any]],
        *,
        validator: JsonValidator[T],
        max_validation_attempts: int = 2,
        temperature: float = 0.0,
    ) -> ModelResult[T]:
        if not 1 <= max_validation_attempts <= 5:
            raise ValueError("max_validation_attempts must be between 1 and 5")
        conversation = [dict(message) for message in messages]
        if not conversation:
            raise ValueError("messages must not be empty")
        attempts: list[dict[str, Any]] = []
        input_total = 0
        output_total = 0
        token_total = 0
        usage_complete = True
        last_error = "model response did not pass validation"

        for attempt_number in range(1, max_validation_attempts + 1):
            response = self._client.chat.completions.create(
                model=self.request_model,
                messages=conversation,
                temperature=temperature,
                max_tokens=self.max_output_tokens,
            )
            if len(response.choices) != 1:
                raise ValueError("model response must contain exactly one choice")
            choice = response.choices[0]
            content = choice.message.content
            if not isinstance(content, str) or not content.strip():
                content = ""
                validation_error = "model response content is empty"
                parsed = None
            else:
                try:
                    parsed = validator(_json_object(content))
                except (TypeError, ValueError, KeyError) as exc:
                    parsed = None
                    validation_error = str(exc) or type(exc).__name__
                else:
                    validation_error = None

            usage = response.usage
            prompt_tokens = _optional_int(
                getattr(usage, "prompt_tokens", None) if usage is not None else None
            )
            completion_tokens = _optional_int(
                getattr(usage, "completion_tokens", None) if usage is not None else None
            )
            response_tokens = _optional_int(
                getattr(usage, "total_tokens", None) if usage is not None else None
            )
            if None in (prompt_tokens, completion_tokens, response_tokens):
                usage_complete = False
            else:
                input_total += prompt_tokens
                output_total += completion_tokens
                token_total += response_tokens
            attempts.append(
                {
                    "attempt": attempt_number,
                    "response_id": getattr(response, "id", None),
                    "response_model": getattr(response, "model", None),
                    "finish_reason": getattr(choice, "finish_reason", None),
                    "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "total_tokens": response_tokens,
                    "validation_error": validation_error,
                }
            )
            if validation_error is None:
                return ModelResult(
                    content=content,
                    value=parsed,
                    model_calls=attempt_number,
                    input_tokens=input_total if usage_complete else None,
                    output_tokens=output_total if usage_complete else None,
                    total_tokens=token_total if usage_complete else None,
                    reported_cost_usd=None,
                    attempts=tuple(attempts),
                    runtime_identity=self.runtime_identity(),
                )

            last_error = validation_error
            if attempt_number < max_validation_attempts:
                conversation.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "The previous response failed JSON validation: "
                                f"{validation_error}. Return only one corrected JSON object "
                                "matching the requested schema."
                            ),
                        },
                    ]
                )

        raise ModelValidationError(
            f"model response failed validation after {max_validation_attempts} attempts: {last_error}",
            attempts=tuple(attempts),
            input_tokens=input_total if usage_complete else None,
            output_tokens=output_total if usage_complete else None,
            total_tokens=token_total if usage_complete else None,
        )
