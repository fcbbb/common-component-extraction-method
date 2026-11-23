"""Independent model review of curated transformations.

The first review has exactly three outcomes: publish the component, discard it
as having no reusable value, or send it to one rework round with a concrete
must-change list.  There is no severity grading and no second review: the
``finalize`` stage owns the last word for a reworked component.

Deterministic validation runs first and again after the model answers, so a
malformed verdict is recorded as ``invalid`` rather than guessed at.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .contracts import CARD_FIELDS, digest, quote_present
from .corpus import corpus_digest, load_corpus
from .service import load_prompt, run_review

REVIEW_SCHEMA = "methodology-review-v2"
REVIEW_VERDICTS = {"publish", "discard", "rework"}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _must_change(review: dict[str, Any]) -> list[Any]:
    value = review.get("must_change")
    return value if isinstance(value, list) else []


def validate_review(
    review: Any,
    *,
    transformation_id: str,
    transformation: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(review, dict):
        return ["review must be a JSON object"]
    verdict = review.get("verdict")
    if verdict not in REVIEW_VERDICTS:
        errors.append(f"verdict must be one of {sorted(REVIEW_VERDICTS)}")
    if review.get("transformation_id") != transformation_id:
        errors.append("review transformation_id does not match the proposal")
    if not isinstance(review.get("summary"), str) or len(review["summary"].strip()) < 20:
        errors.append("summary must be a substantive paragraph")

    raw_changes = review.get("must_change")
    if raw_changes not in (None, "") and not isinstance(raw_changes, list):
        errors.append("must_change must be a list of change objects")
    changes = _must_change(review)
    for index, item in enumerate(changes):
        if not isinstance(item, dict):
            errors.append(
                f"must_change[{index}] must be an object with field, quote and instruction"
            )
            continue
        field = item.get("field")
        quote = item.get("quote")
        instruction = item.get("instruction")
        if field not in CARD_FIELDS:
            errors.append(f"must_change[{index}].field must name a component field")
        if not isinstance(quote, str) or len(quote.strip()) < 12:
            errors.append(
                f"must_change[{index}].quote must be verbatim text of at least "
                "12 characters"
            )
        elif transformation is not None and not quote_present(
            transformation, str(field), quote
        ):
            errors.append(f"must_change[{index}].quote does not appear in {field}")
        if not isinstance(instruction, str) or len(instruction.strip()) < 12:
            errors.append(
                f"must_change[{index}].instruction must state what the text must become"
            )
    if verdict in {"publish", "discard"} and changes:
        errors.append(f"{verdict} cannot carry a must_change list")
    if verdict == "rework" and not changes:
        errors.append("rework needs at least one must_change item")
    return errors


def review_verdict(review: dict[str, Any], errors: list[str]) -> str:
    if errors:
        return "invalid"
    return str(review.get("verdict") or "invalid")


def review_entries(
    history_root: Path,
    curated_root: Path,
    review_root: Path,
    *,
    runner: Any,
    model: str,
    workers: int = 2,
    resume: bool = False,
) -> dict[str, Any]:
    """Review the curated set once; the verdict decides the next stage."""
    corpus = load_corpus(history_root)
    curated_root = curated_root.expanduser().resolve()
    review_root = review_root.expanduser().resolve()
    entries_path = curated_root / "transformations.json"
    if not entries_path.is_file():
        raise RuntimeError(f"curated transformations are missing: {entries_path}")
    entries = json.loads(entries_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise RuntimeError(f"curated transformations must be a list: {entries_path}")
    system_prompt = load_prompt("review_transformation_system.txt")

    def process(entry: dict[str, Any]) -> dict[str, Any]:
        transformation_id = entry["transformation_id"]
        example = corpus.example(entry["example_id"])
        input_digest = digest(
            {
                "entry_digest": entry["entry_digest"],
                "prompt": system_prompt,
                "model": model,
            }
        )
        output_dir = review_root / transformation_id
        result_path = output_dir / "review.json"
        if resume and result_path.is_file():
            existing = json.loads(result_path.read_text(encoding="utf-8"))
            if existing.get("input_digest") == input_digest:
                return existing
        review = run_review(
            entry,
            example,
            runner=runner,
            output_dir=output_dir,
            system_prompt=system_prompt,
        )
        errors = validate_review(
            review,
            transformation_id=transformation_id,
            transformation=entry["transformation"],
        )
        result = {
            "schema": REVIEW_SCHEMA,
            "transformation_id": transformation_id,
            "example_id": entry["example_id"],
            "entry_digest": entry["entry_digest"],
            "input_digest": input_digest,
            "model": model,
            "verdict": review_verdict(review, errors),
            "validation_errors": errors,
            "review": review,
            "review_sha256": digest(review),
        }
        _write_json(result_path, result)
        return result

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(process, entry): entry for entry in entries}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - one bad review must not hide the rest
                failures.append(
                    {
                        "transformation_id": entry["transformation_id"],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    results.sort(key=lambda item: item["transformation_id"])
    counts: dict[str, int] = {}
    for result in results:
        counts[result["verdict"]] = counts.get(result["verdict"], 0) + 1
    summary = {
        "schema": "methodology-review-summary-v2",
        "history_digest": corpus_digest(corpus.root),
        "curated_root": str(curated_root),
        "review_root": str(review_root),
        "model": model,
        "reviewed_count": len(results),
        "failure_count": len(failures),
        "verdict_counts": counts,
        "results": [
            {
                "transformation_id": item["transformation_id"],
                "example_id": item["example_id"],
                "verdict": item["verdict"],
                "errors": item["validation_errors"],
            }
            for item in results
        ],
        "failures": failures,
    }
    _write_json(review_root / "summary.json", summary)
    return summary