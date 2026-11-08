"""Structured validators for single-response model decisions."""

from __future__ import annotations

from typing import Any


def validate_leakage_decision(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != {"decision", "reasons"}:
        raise ValueError("leakage decision must contain exactly decision and reasons")
    decision = value["decision"]
    reasons = value["reasons"]
    if decision not in {"pass", "reject"}:
        raise ValueError("leakage decision must be pass or reject")
    if not isinstance(reasons, list) or not all(
        isinstance(reason, str) and reason.strip() for reason in reasons
    ):
        raise ValueError("leakage reasons must be a list of non-empty strings")
    if decision == "reject" and not reasons:
        raise ValueError("rejected leakage decisions must include at least one reason")
    return {
        "decision": decision,
        "reasons": [reason.strip() for reason in reasons],
    }
