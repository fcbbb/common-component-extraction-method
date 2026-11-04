"""Experiment-local prompt and component bundle configuration."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .workspace import neutral_agent_text


PROMPT_FILES = {
    "extraction/extract_system.txt": Path(__file__).resolve().parent
    / "extraction/prompts/extract_system.txt",
    "discovery/merge_system.txt": Path(__file__).resolve().parents[1]
    / "library_publish/prompts/merge_system.txt",
    "validation/review_system.txt": Path(__file__).resolve().parent
    / "validation/prompts/review_system.txt",
    "validation/validate_component_system.txt": Path(__file__).resolve().parent
    / "validation/prompts/validate_component_system.txt",
    "usage/agent_bundle_prompt.txt": Path(__file__).resolve().parents[1]
    / "library_publish/prompts/agent_bundle_prompt.txt",
}
DEFAULT_BUNDLE_CONFIG: dict[str, Any] = {
    "deduplicate_similar_components": False,
    "index_format": "markdown",
    "library_layout": "per_component",
    "include_guidance": False,
    "summary_max_chars": 240,
    "sort_by": "original",
}

DEFAULT_COMMUNITY_CONFIG: dict[str, Any] = {
    "leiden_resolution": 1.0,
}

DEFAULT_COMPONENT_CONTRACT = {
    "required_fields": [
        "component_id", "status", "name", "summary", "type", "confidence",
        "members", "evidence", "library", "entrypoints"
    ],
    "optional_fields": [
        "relationships", "invariants", "variation_points", "dependencies",
        "limitations", "guidance", "applicability", "integration_steps"
    ],
}
CORE_REQUIRED_COMPONENT_FIELDS = set(DEFAULT_COMPONENT_CONTRACT["required_fields"])
ALLOWED_COMPONENT_FIELDS = {
    "component_id", "status", "name", "summary", "type", "confidence",
    "relationships", "invariants", "variation_points", "members", "evidence",
    "library", "entrypoints", "dependencies", "limitations", "guidance",
    "applicability", "integration_steps"
}


def resolve_prompt(experiment_dir: Path | str | None, prompt_key: str) -> str:
    """Read a prompt override from an experiment, falling back to the shipped default."""
    if prompt_key not in PROMPT_FILES:
        raise KeyError(f"unknown component prompt: {prompt_key}")
    if experiment_dir is not None:
        root = Path(experiment_dir).expanduser().resolve()
        override = root / "prompts" / prompt_key
        if override.is_file():
            return neutral_agent_text(override.read_text(encoding="utf-8"))
    default_path = PROMPT_FILES[prompt_key]
    return neutral_agent_text(default_path.read_text(encoding="utf-8")) if default_path is not None else ""


def load_bundle_config(experiment_dir: Path | str | None) -> dict[str, Any]:
    """Load and validate the bundle representation settings for an experiment."""
    config = dict(DEFAULT_BUNDLE_CONFIG)
    if experiment_dir is not None:
        config_path = Path(experiment_dir).expanduser().resolve() / "bundle_config.json"
        if config_path.is_file():
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("bundle_config.json must contain a JSON object")
            config.update(loaded)

    unknown = sorted(set(config) - set(DEFAULT_BUNDLE_CONFIG))
    if unknown:
        raise ValueError(f"unsupported bundle config fields: {unknown}")

    if not isinstance(config.get("deduplicate_similar_components"), bool):
        raise ValueError("bundle deduplicate_similar_components must be a boolean")
    if config.get("index_format") != "markdown":
        raise ValueError("bundle index_format must be markdown")
    if config.get("library_layout") != "per_component":
        raise ValueError("bundle library_layout must be per_component")
    if config.get("sort_by") not in {"original", "name", "members_count"}:
        raise ValueError("bundle sort_by must be original, name, or members_count")
    if not isinstance(config.get("include_guidance"), bool):
        raise ValueError("bundle include_guidance must be a boolean")
    max_chars = config.get("summary_max_chars")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 0:
        raise ValueError("bundle summary_max_chars must be a non-negative integer")
    return config


def load_community_config(experiment_dir: Path | str | None) -> dict[str, Any]:
    """Load the bounded, candidate-specific community partition settings."""
    config = dict(DEFAULT_COMMUNITY_CONFIG)
    if experiment_dir is not None:
        config_path = Path(experiment_dir).expanduser().resolve() / "community_config.json"
        if config_path.is_file():
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("community_config.json must contain a JSON object")
            config.update(loaded)

    unknown = sorted(set(config) - set(DEFAULT_COMMUNITY_CONFIG))
    if unknown:
        raise ValueError(f"unsupported community config fields: {unknown}")
    resolution = config.get("leiden_resolution")
    if isinstance(resolution, bool) or not isinstance(resolution, (int, float)):
        raise ValueError("community leiden_resolution must be a numeric value")
    if not math.isfinite(float(resolution)) or float(resolution) <= 0:
        raise ValueError("community leiden_resolution must be a finite positive number")
    config["leiden_resolution"] = float(resolution)
    return config


def load_component_contract(experiment_dir: Path | str | None) -> dict[str, list[str]]:
    contract = {
        "required_fields": list(DEFAULT_COMPONENT_CONTRACT["required_fields"]),
        "optional_fields": list(DEFAULT_COMPONENT_CONTRACT["optional_fields"]),
    }
    if experiment_dir is not None:
        contract_path = Path(experiment_dir).expanduser().resolve() / "component_contract.json"
        if contract_path.is_file():
            loaded = json.loads(contract_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("component_contract.json must contain a JSON object")
            contract.update(loaded)
    for key in ("required_fields", "optional_fields"):
        value = contract.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"component contract {key} must be a list of strings")
        unknown = sorted(set(value) - ALLOWED_COMPONENT_FIELDS)
        if unknown:
            raise ValueError(f"unsupported component contract fields: {unknown}")
        contract[key] = list(dict.fromkeys(value))
    missing_core = sorted(CORE_REQUIRED_COMPONENT_FIELDS - set(contract["required_fields"]))
    if missing_core:
        raise ValueError(f"component contract cannot remove core required fields: {missing_core}")
    if set(contract["required_fields"]) & set(contract["optional_fields"]):
        raise ValueError("component contract fields cannot be both required and optional")
    return contract


def experiment_prompt_files() -> dict[str, str]:
    """Return the shipped prompt set used to seed an editable experiment."""
    result = {}
    for key, default_path in PROMPT_FILES.items():
        if default_path is None:
            result[key] = ""
        else:
            result[key] = default_path.read_text(encoding="utf-8")
    return result
