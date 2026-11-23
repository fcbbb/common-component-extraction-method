"""Deterministic admission of extracted transformations.

The extraction agent is allowed to be wrong.  Curate re-validates every
component against the corpus, drops anything that is not `draft_ready`, and
deduplicates across examples.  No model is involved.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .contracts import digest, normalize_response
from .corpus import corpus_digest, file_sha256, load_corpus

CURATION_SCHEMA = "methodology-curation-v1"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_response(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read extraction response {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"extraction response must be an object: {path}")
    return value


def curate(
    history_root: Path,
    extract_root: Path,
    output_root: Path,
    *,
    clean: bool = True,
) -> dict[str, Any]:
    corpus = load_corpus(history_root)
    extract_root = extract_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if output_root.exists() and clean:
        shutil.rmtree(output_root)

    entries: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    example_reports: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    for example in corpus.examples:
        response_path = extract_root / example.task_id / "extraction_response.json"
        report: dict[str, Any] = {
            "task_id": example.task_id,
            "response": response_path.as_posix(),
        }
        if not response_path.is_file():
            report.update(status="missing", accepted=0, rejected=0)
            rejected.append(
                {"task_id": example.task_id, "reason": "extraction response is missing"}
            )
            example_reports.append(report)
            continue
        try:
            response = load_response(response_path)
            status, accepted, audit, problems = normalize_response(
                response, example=example.metadata
            )
        except (RuntimeError, ValueError) as exc:
            report.update(status="invalid", accepted=0, rejected=0, error=str(exc))
            rejected.append({"task_id": example.task_id, "reason": str(exc)})
            example_reports.append(report)
            continue

        input_digest = digest(
            {
                "response_sha256": file_sha256(response_path),
                "example": example.task_id,
                "commit": example.source.get("commit"),
                "files": example.files,
            }
        )
        kept = 0
        for transformation in accepted:
            transformation_id = transformation["transformation_id"]
            if transformation_id in seen:
                rejected.append(
                    {
                        "task_id": example.task_id,
                        "transformation_id": transformation_id,
                        "reason": (
                            "duplicate transformation_id across examples; "
                            f"first retained from {seen[transformation_id]}"
                        ),
                    }
                )
                continue
            seen[transformation_id] = example.task_id
            entry = {
                "schema": "methodology-transformation-entry-v1",
                "transformation_id": transformation_id,
                "example_id": example.task_id,
                "capability": transformation["capability"],
                "source": example.source,
                "files": example.files,
                "input_digest": input_digest,
                "extraction": {
                    "response": str(response_path),
                    "response_sha256": file_sha256(response_path),
                },
                "workspace_audit": audit,
                "transformation": transformation,
            }
            entry["entry_digest"] = digest(
                {
                    "transformation": transformation,
                    "example_id": example.task_id,
                    "source_commit": example.source.get("commit"),
                }
            )
            entries.append(entry)
            kept += 1
        for problem in problems:
            rejected.append({"task_id": example.task_id, **problem})
        report.update(
            status=status,
            accepted=kept,
            rejected=len(problems),
            input_digest=input_digest,
        )
        example_reports.append(report)

    entries.sort(key=lambda item: (item["capability"], item["transformation_id"]))
    summary = {
        "schema": CURATION_SCHEMA,
        "history_root": str(corpus.root),
        "history_digest": corpus_digest(corpus.root),
        "extract_root": str(extract_root),
        "example_count": len(corpus.examples),
        "responses_present": sum(
            1 for report in example_reports if report.get("status") != "missing"
        ),
        "accepted_count": len(entries),
        "rejected_count": len(rejected),
        "policy": {
            "model_used": False,
            "requires_focus_evidence": True,
            "requires_provenance": True,
            "rejects_code_paths": True,
            "duplicate_ids": "keep_first_by_corpus_order",
        },
        "examples": example_reports,
        "entries": [
            {
                "transformation_id": entry["transformation_id"],
                "example_id": entry["example_id"],
                "capability": entry["capability"],
                "entry_digest": entry["entry_digest"],
            }
            for entry in entries
        ],
        "rejected": rejected,
    }
    _write_json(output_root / "transformations.json", entries)
    _write_json(output_root / "summary.json", summary)
    return summary