"""The single, last pass over components the first review marked ``rework``.

The finalize agent receives the component as it stands after the rework round
and the first review's must-change items.  It returns the finished component;
the pipeline then checks mechanically that every quoted statement is gone from
its field.  A component that finalize cannot return in valid form, or that
still carries a quoted statement, is recorded as ``invalid`` and is never
published.

Entries with a ``publish`` or ``discard`` verdict pass through untouched, and
their first review is copied into the final review root.  That gives publish a
single curated set and a single review set with the same shape.
"""
from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .contracts import digest, normalize_response, quote_present
from .corpus import corpus_digest, load_corpus
from .service import load_prompt, run_finalize

FINALIZE_SCHEMA = "methodology-finalize-v2"
FINALIZE_SUMMARY_SCHEMA = "methodology-finalize-summary-v1"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_reviews(review_root: Path) -> dict[str, dict[str, Any]]:
    reviews: dict[str, dict[str, Any]] = {}
    for path in sorted(review_root.glob("*/review.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("transformation_id"), str):
            reviews[value["transformation_id"]] = value
    return reviews


def _finalizable(review: dict[str, Any] | None) -> bool:
    if not review or review.get("verdict") != "rework":
        return False
    changes = review.get("review", {}).get("must_change")
    return (
        isinstance(changes, list)
        and bool(changes)
        and all(isinstance(item, dict) for item in changes)
    )


def _adopt_identity(
    entry: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """The pipeline owns component identity; finalize cannot rename a family."""
    candidate["transformation_id"] = entry["transformation_id"]
    candidate["capability"] = entry["capability"]
    return candidate


def _entry_with_finalize(
    entry: dict[str, Any],
    transformation: dict[str, Any],
    audit: dict[str, Any],
    *,
    review: dict[str, Any],
) -> dict[str, Any]:
    updated = {
        **entry,
        "transformation": transformation,
        "workspace_audit": audit,
        "finalize": {
            "from_entry_digest": entry["entry_digest"],
            "review_sha256": review.get("review_sha256"),
            "verdict": review.get("verdict"),
            "must_change": review.get("review", {}).get("must_change") or [],
        },
    }
    updated["entry_digest"] = digest(
        {
            "transformation": transformation,
            "example_id": entry["example_id"],
            "source_commit": (entry.get("source") or {}).get("commit"),
        }
    )
    return updated


def finalize_entries(
    history_root: Path,
    curated_root: Path,
    review_root: Path,
    output_root: Path,
    *,
    runner: Any,
    model: str,
    workers: int = 2,
) -> dict[str, Any]:
    corpus = load_corpus(history_root)
    curated_root = curated_root.expanduser().resolve()
    review_root = review_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    entries_path = curated_root / "transformations.json"
    if not entries_path.is_file():
        raise RuntimeError(f"curated transformations are missing: {entries_path}")
    if not review_root.is_dir():
        raise RuntimeError(f"review directory is missing: {review_root}")
    entries = json.loads(entries_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise RuntimeError(f"curated transformations must be a list: {entries_path}")
    reviews = _load_reviews(review_root)
    system_prompt = load_prompt("finalize_transformation_system.txt")

    def process(entry: dict[str, Any]) -> dict[str, Any]:
        transformation_id = entry["transformation_id"]
        review = reviews.get(transformation_id)
        if not _finalizable(review):
            return {
                "entry": entry,
                "review": review,
                "status": "unchanged",
                "errors": [],
            }

        example = corpus.example(entry["example_id"])
        input_digest = digest(
            {
                "entry_digest": entry["entry_digest"],
                "review_sha256": review.get("review_sha256"),
                "prompt": system_prompt,
                "model": model,
            }
        )
        output_dir = output_root / "work" / transformation_id
        response = run_finalize(
            entry,
            review["review"],
            example,
            runner=runner,
            output_dir=output_dir,
            system_prompt=system_prompt,
        )
        errors: list[str] = []
        final: dict[str, Any] | None = None
        audit: dict[str, Any] = {}
        try:
            _, accepted, audit, rejected = normalize_response(
                response, example=example.metadata
            )
        except ValueError as exc:
            accepted = []
            rejected = []
            errors.append(str(exc))
        if len(accepted) == 1:
            final = _adopt_identity(entry, accepted[0])
            remaining = [
                item
                for item in review["review"].get("must_change") or []
                if quote_present(
                    final, str(item.get("field") or ""), str(item.get("quote") or "")
                )
            ]
            if remaining:
                errors.append(
                    "quoted statement still present: "
                    + "; ".join(
                        f"{item.get('field')}: {item.get('quote')}"
                        for item in remaining
                    )
                )
                final = None
        elif not errors:
            errors.append(
                f"finalize must return exactly one component, got {len(accepted)}"
            )
        for problem in rejected:
            errors.append(f"component rejected by the contract: {problem.get('errors')}")

        if final is None:
            record = {
                "schema": FINALIZE_SCHEMA,
                "transformation_id": transformation_id,
                "example_id": entry["example_id"],
                "entry_digest": entry["entry_digest"],
                "input_digest": input_digest,
                "model": model,
                "verdict": "invalid",
                "finalized": False,
                "must_change": review["review"].get("must_change") or [],
                "validation_errors": errors,
                "review": {
                    "transformation_id": transformation_id,
                    "verdict": "invalid",
                    "summary": "Finalize did not return a valid component.",
                    "must_change": review["review"].get("must_change") or [],
                },
                "review_sha256": digest(response),
            }
            return {
                "entry": entry,
                "review": record,
                "status": "invalid",
                "errors": errors,
            }

        record = {
            "schema": FINALIZE_SCHEMA,
            "transformation_id": transformation_id,
            "example_id": entry["example_id"],
            "entry_digest": digest(
                {
                    "transformation": final,
                    "example_id": entry["example_id"],
                    "source_commit": (entry.get("source") or {}).get("commit"),
                }
            ),
            "input_digest": input_digest,
            "model": model,
            "verdict": "publish",
            "finalized": True,
            "must_change": review["review"].get("must_change") or [],
            "validation_errors": [],
            "review": {
                "transformation_id": transformation_id,
                "verdict": "publish",
                "summary": (
                    "Finalize returned a component with every quoted statement replaced."
                ),
                "must_change": [],
            },
            # The finalize verdict approves this exact component.
            "review_sha256": digest(final),
        }
        return {
            "entry": _entry_with_finalize(entry, final, audit, review=record),
            "review": record,
            "status": "finalized",
            "errors": [],
        }

    outcomes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(process, entry): entry for entry in entries}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                outcomes.append(future.result())
            except Exception as exc:  # noqa: BLE001 - keep the component unpublishable
                failures.append(
                    {
                        "transformation_id": entry["transformation_id"],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                outcomes.append(
                    {
                        "entry": entry,
                        "review": None,
                        "status": "failed",
                        "errors": [f"{type(exc).__name__}: {exc}"],
                    }
                )

    outcomes.sort(key=lambda item: item["entry"]["transformation_id"])
    final_entries = [item["entry"] for item in outcomes]

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    for outcome in outcomes:
        review = outcome["review"]
        if review is None:
            continue
        _write_json(
            output_root / "reviews" / outcome["entry"]["transformation_id"] / "review.json",
            review,
        )

    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome["status"]] = counts.get(outcome["status"], 0) + 1
    summary = {
        "schema": FINALIZE_SUMMARY_SCHEMA,
        "history_digest": corpus_digest(corpus.root),
        "curated_root": str(curated_root),
        "review_root": str(review_root),
        "output_root": str(output_root),
        "model": model,
        "entry_count": len(final_entries),
        "finalized_count": counts.get("finalized", 0),
        "invalid_count": counts.get("invalid", 0),
        "unchanged_count": counts.get("unchanged", 0),
        "failure_count": len(failures),
        "status_counts": counts,
        "results": [
            {
                "transformation_id": item["entry"]["transformation_id"],
                "verdict": (item["review"] or {}).get("verdict", "missing"),
                "status": item["status"],
                "errors": item["errors"],
            }
            for item in outcomes
        ],
        "failures": failures,
    }
    _write_json(output_root / "transformations.json", final_entries)
    _write_json(output_root / "summary.json", summary)
    return summary