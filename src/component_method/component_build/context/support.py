"""Small prompt, logging, and JSON helpers used by component review."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


_MODEL_ID_ALIASES = {
    "deepseek/deepseek-v4.1-flash": "deepseek/deepseek-flash",
    "deepseek-v4.1-flash": "deepseek-flash",
}


def canonicalize_model_id(model_id: Any) -> str:
    """Normalize known aliases for cache matching while preserving unknown IDs."""
    value = str(model_id or "").strip()
    return _MODEL_ID_ALIASES.get(value.casefold(), value)

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def build_user_prompt(template_path: Path, payload: dict[str, Any]) -> str:
    return read_text(template_path).replace(
        "{payload}", json.dumps(payload, indent=2, ensure_ascii=False)
    )

def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

def save_call_log(
    path: Path, response: Any, method: str, candidate_id: str,
    prompt_paths: dict[str, str],
) -> None:
    write_json(
        path,
        {
            "provider": "deepseek",
            "model": response.model,
            "temperature": 0,
            "candidate_id": candidate_id,
            "method": method,
            "prompt_path": prompt_paths,
            "latency_sec": response.latency_sec,
            "usage": response.usage,
        },
    )

def status(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)
