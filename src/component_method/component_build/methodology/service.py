"""Agent-facing tasks for transformation extraction and review."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import CARD_FIELDS, digest
from .corpus import HistoryExample

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    path = PROMPT_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"methodology prompt is missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def _role_block(example: HistoryExample) -> str:
    files = example.files
    context = files.get("context") or []
    tests = files.get("tests") or []
    lines = [
        "## Migration example",
        "",
        "Before (source-side implementation), workspace-relative:",
        *[f"- `{item}`" for item in files.get("before") or []],
        "",
        "After (completed target-side implementation), workspace-relative:",
        *[f"- `{item}`" for item in files.get("after") or []],
        "",
        f"Context: {len(context)} shared/caller files. "
        + "The workspace root is the project's real source layout; explore it directly.",
        f"Tests: {len(tests)} files.",
        "",
    ]
    spec = str(example.metadata.get("spec") or "").strip()
    if spec:
        lines.extend(["## Migration statement", "", spec, ""])
    return "\n".join(lines)


def build_extraction_task(example: HistoryExample, system_prompt: str) -> str:
    return "\n\n".join(
        [
            system_prompt.strip(),
            _role_block(example),
            "Write `manifest.json` for this example.",
        ]
    )


def _card(transformation: dict[str, Any]) -> dict[str, Any]:
    card = {
        key: transformation.get(key)
        for key in CARD_FIELDS
        if key in transformation
    }
    applicability = card.get("applicability")
    if isinstance(applicability, dict):
        card["applicability"] = {
            "constraints": applicability.get("constraints") or []
        }
    return card


def build_review_task(
    entry: dict[str, Any],
    example: HistoryExample,
    system_prompt: str,
) -> str:
    transformation = entry["transformation"]
    return "\n\n".join(
        [
            system_prompt.strip(),
            _role_block(example),
            "## Proposal under review",
            "",
            "```json",
            json.dumps(_card(transformation), ensure_ascii=False, indent=2),
            "```",
            "",
            f"Review `{transformation['transformation_id']}` against this example. "
            "Write `manifest.json` with the review schema. "
            "The workspace stays read-only.",
        ]
    )


REVIEW_EVIDENCE_FIELDS = ("verdict", "summary", "must_change")


def _must_change_block(review: dict[str, Any]) -> str:
    lines: list[str] = []
    for index, item in enumerate(review.get("must_change") or [], 1):
        if not isinstance(item, dict):
            lines.append(f"{index}. {item}")
            continue
        lines.extend(
            [
                f"{index}. field: `{item.get('field')}`",
                f"   quote: {item.get('quote')}",
                f"   instruction: {item.get('instruction')}",
            ]
        )
    return "\n".join(lines)


def build_revision_task(
    entry: dict[str, Any],
    review: dict[str, Any],
    example: HistoryExample,
    system_prompt: str,
) -> str:
    """Repair brief: the component plus the must-change list."""
    transformation = entry["transformation"]
    return "\n\n".join(
        [
            system_prompt.strip(),
            _role_block(example),
            "## Component under revision",
            "",
            "```json",
            json.dumps(_card(transformation), ensure_ascii=False, indent=2),
            "```",
            "",
            "## Must change",
            "",
            _must_change_block(review),
            "",
            f"Repair `{transformation['transformation_id']}` against this example; "
            "the pipeline keeps the component id. Write `manifest.json` with the "
            "revised component. The workspace stays read-only.",
        ]
    )


def build_finalize_task(
    entry: dict[str, Any],
    review: dict[str, Any],
    example: HistoryExample,
    system_prompt: str,
) -> str:
    """Final check: resolve every must-change item and return the last version."""
    transformation = entry["transformation"]
    return "\n\n".join(
        [
            system_prompt.strip(),
            _role_block(example),
            "## Component after rework",
            "",
            "```json",
            json.dumps(_card(transformation), ensure_ascii=False, indent=2),
            "```",
            "",
            "## Must change",
            "",
            _must_change_block(review),
            "",
            f"Finalize `{transformation['transformation_id']}` against this example. "
            "Write `manifest.json` with the final component. "
            "The workspace stays read-only.",
        ]
    )


def extraction_input_digest(example: HistoryExample, system_prompt: str) -> str:
    return digest(
        {
            "example": example.task_id,
            "commit": example.source.get("commit"),
            "files": example.files,
            "prompt": system_prompt,
        }
    )


def run_extraction(
    example: HistoryExample,
    *,
    runner: Any,
    output_dir: Path,
    system_prompt: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    task = build_extraction_task(example, system_prompt)
    (output_dir / "extraction_task.txt").write_text(task, encoding="utf-8")
    response = runner.run_workspace_agent(
        workspace_root=example.workspace,
        task=task,
        output_dir=output_dir,
        task_label=f"methodology-extract:{example.task_id}",
        agent_role="methodology",
    )
    (output_dir / "extraction_response.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "input_digest.txt").write_text(
        extraction_input_digest(example, system_prompt) + "\n", encoding="utf-8"
    )
    return response


def run_revision(
    entry: dict[str, Any],
    review: dict[str, Any],
    example: HistoryExample,
    *,
    runner: Any,
    output_dir: Path,
    system_prompt: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    task = build_revision_task(entry, review, example, system_prompt)
    (output_dir / "revision_task.txt").write_text(task, encoding="utf-8")
    response = runner.run_workspace_agent(
        workspace_root=example.workspace,
        task=task,
        output_dir=output_dir,
        task_label=f"methodology-revise:{entry['transformation_id']}",
        agent_role="methodology",
    )
    (output_dir / "revision_response.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return response


def run_finalize(
    entry: dict[str, Any],
    review: dict[str, Any],
    example: HistoryExample,
    *,
    runner: Any,
    output_dir: Path,
    system_prompt: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    task = build_finalize_task(entry, review, example, system_prompt)
    (output_dir / "finalize_task.txt").write_text(task, encoding="utf-8")
    response = runner.run_workspace_agent(
        workspace_root=example.workspace,
        task=task,
        output_dir=output_dir,
        task_label=f"methodology-finalize:{entry['transformation_id']}",
        agent_role="methodology",
    )
    (output_dir / "finalize_response.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return response


def run_review(
    entry: dict[str, Any],
    example: HistoryExample,
    *,
    runner: Any,
    output_dir: Path,
    system_prompt: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    task = build_review_task(entry, example, system_prompt)
    (output_dir / "review_task.txt").write_text(task, encoding="utf-8")
    review = runner.run_workspace_agent(
        workspace_root=example.workspace,
        task=task,
        output_dir=output_dir,
        task_label=f"methodology-review:{entry['transformation']['transformation_id']}",
        agent_role="methodology_review",
    )
    (output_dir / "review_response.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return review