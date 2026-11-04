from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMConfigurationError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    content: str
    raw: dict[str, Any]
    usage: dict[str, Any]
    latency_sec: float
    model: str


class DeepSeekClient:
    """Small OpenAI-compatible client using only the Python standard library."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        timeout_sec: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        self.model = model or os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash"
        self.temperature = temperature
        self.timeout_sec = timeout_sec
        raw_max_tokens = max_tokens if max_tokens is not None else os.getenv("DEEPSEEK_MAX_TOKENS")
        self.max_tokens = int(raw_max_tokens) if raw_max_tokens not in (None, "") else None
        if not self.api_key:
            raise LLMConfigurationError(
                "DEEPSEEK_API_KEY is not set. Set DEEPSEEK_API_KEY, optionally DEEPSEEK_BASE_URL and DEEPSEEK_MODEL."
            )

    def chat(self, system: str, user: str) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        start = time.time()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DeepSeek API request failed: {exc}") from exc
        latency = time.time() - start
        content = raw["choices"][0]["message"]["content"]
        return LLMResponse(
            content=content,
            raw=raw,
            usage=raw.get("usage") or {},
            latency_sec=latency,
            model=raw.get("model") or self.model,
        )
