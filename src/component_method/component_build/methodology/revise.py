"""Model-driven rework of components the first review marked ``rework``.

This is the only repair round.  The reviewer's ``must_change`` list is handed
back to an extraction agent together with the component; the result is
validated deterministically and becomes the input of the ``finalize`` stage.
There is no re-review after this stage.

A rework never invents or drops a family: the transformation id and scope must
survive.  If the agent cannot produce a valid revision the original entry is
kept unchanged, and ``finalize`` still gets the must-change items to resolve.
The revision is not checked for the quotes here: ``finalize`` owns that
mechanical check on the version it publishes.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .contracts import digest, normalize_response
from .corpus import corpus_digest, load_corpus
from .service import load_prompt, run_revision

REVISION_SCHEMA = "methodology-revision-v2"
REVISION_SUMMARY_SCHEMA = "methodology-revision-summary-v2"


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


def _revisable(review: dict[str, Any] | None) -> bool:
    """Only a valid ``rework`` verdict with concrete change objects enters."""
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
    """The pipeline owns component identity; a repair cannot rename a family."""
    candidate["transformation_id"] = entry["transformation_id"]
    candidate["capability"] = entry["transformation"]["capability"]
    return candidate


def _entry_with_revision(
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
        "revision": {
            "from_entry_digest": entry["entry_digest"],
            "review_sha256": review.get("review_sha256"),
            "review_verdict": review.get("verdict"),
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


def revise_entries(
    history_root: Path,
    curated_root: Path,
    review_root: Path,
    output_root: Path,
    *,
    runner: Any,
    model: str,
    workers: int = 2,
    resume: bool = False,
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
    system_prompt = load_prompt("revise_transformation_component.txt")

    def process(entry: dict[str, Any]) -> dict[str, Any]:
        transformation_id = entry["transformation_id"]
        review = reviews.get(transformation_id)
        if not _revisable(review):
            return {"entry": entry, "result": None}
        example = corpus.example(entry["example_id"])
        input_digest = digest(
            {
                "entry_digest": entry["entry_digest"],
                "review_sha256": review.get("review_sha256"),
                "prompt": system_prompt,
                "model": model,
            }
        )
        output_dir = output_root / transformation_id
        result_path = output_dir / "revision.json"
        if resume and result_path.is_file():
            existing = json.loads(result_path.read_text(encoding="utf-8"))
            if existing.get("input_digest") == input_digest:
                revised = existing.get("transformation")
                if existing.get("status") == "revised" and isinstance(revised, dict):
                    return {
                        "entry": _entry_with_revision(
                            entry,
                            revised,
                            existing.get("workspace_audit") or {},
                            review=review,
                        ),
                        "result": existing,
                    }
                return {"entry": entry, "result": existing}

        response = run_revision(
            entry,
            review["review"],
            example,
            runner=runner,
            output_dir=output_dir,
            system_prompt=system_prompt,
        )
        errors: list[str] = []
        revised: dict[str, Any] | None = None
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
            revised = _adopt_identity(entry, accepted[0])
        elif not errors:
            errors.append(
                f"revision must return exactly one component, got {len(accepted)}"
            )
        for problem in rejected:
            errors.append(f"component rejected by the contract: {problem.get('errors')}")

        status = "revised" if revised is not None else "kept_original"
        result = {
            "schema": REVISION_SCHEMA,
            "transformation_id": transformation_id,
            "example_id": entry["example_id"],
            "from_entry_digest": entry["entry_digest"],
            "review_sha256": review.get("review_sha256"),
            "input_digest": input_digest,
            "model": model,
            "status": status,
            "errors": errors,
            "workspace_audit": audit,
            "transformation": revised if revised is not None else None,
            "revision_sha256": digest(response),
        }
        _write_json(result_path, result)
        if revised is None:
            return {"entry": entry, "result": result}
        return {
            "entry": _entry_with_revision(entry, revised, audit, review=review),
            "result": result,
        }

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    updated_entries: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(process, entry): entry for entry in entries}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:  # noqa: BLE001 - keep the original component
                failures.append(
                    {
                        "transformation_id": entry["transformation_id"],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                updated_entries.append(entry)
                continue
            updated_entries.append(outcome["entry"])
            if outcome["result"] is not None:
                results.append(outcome["result"])

    updated_entries.sort(
        key=lambda item: (item["capability"], item["transformation_id"])
    )
    results.sort(key=lambda item: item["transformation_id"])
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    summary = {
        "schema": REVISION_SUMMARY_SCHEMA,
        "history_digest": corpus_digest(corpus.root),
        "curated_root": str(curated_root),
        "review_root": str(review_root),
        "output_root": str(output_root),
        "model": model,
        "entry_count": len(entries),
        "revised_count": counts.get("revised", 0),
        "kept_original_count": counts.get("kept_original", 0),
        # Only a rework verdict enters this round; everything else passes
        # through untouched.
        "unchanged_count": len(entries) - len(results),
        "failure_count": len(failures),
        "status_counts": counts,
        "results": [
            {
                "transformation_id": item["transformation_id"],
                "status": item["status"],
                "errors": item["errors"],
            }
            for item in results
        ],
        "failures": failures,
    }
    _write_json(output_root / "transformations.json", updated_entries)
    _write_json(output_root / "summary.json", summary)
    return summary