"""Atomic execution blocks for the component method.

The workflow used to expose nine near-identical sub-stages whose ordering was
hard-coded in :mod:`run_stage` and :mod:`run_batch`.  Callers had to know that
``curate`` only makes sense after ``extract`` and that ``publish`` silently
depends on the review summary.

This module is the single source of truth for:

* which steps form one atomic block,
* which artifacts a block consumes and produces,
* whether a block can run in the current workspace.

Prompts and callers select blocks; feasibility is always decided here from the
files on disk, never from model output.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from component_method.runtime_paths import release_root


@dataclass(frozen=True)
class Block:
    """A group of steps that share one artifact boundary."""

    name: str
    title: str
    steps: tuple[str, ...]
    requires: tuple[str, ...]
    produces: str
    scope: str = "task"


BLOCKS: tuple[Block, ...] = (
    Block(
        name="prepare",
        title="扫描源码并冻结抽取输入",
        steps=("source_scan",),
        requires=(),
        produces="packets",
    ),
    Block(
        name="build",
        title="抽取、收敛并冻结组件",
        steps=("extract", "curate", "prepare_reviews"),
        requires=("packets",),
        produces="frozen",
    ),
    Block(
        name="audit",
        title="审核组件并应用单次审核修订",
        steps=("review", "finalize_review"),
        requires=("frozen",),
        produces="review",
    ),
    Block(
        name="publish",
        title="发布只读组件库",
        steps=("publish_library",),
        requires=("review",),  # adjusted by publish mode
        produces="library",
    ),
    Block(
        name="retrieval",
        title="检索并物化组件选择",
        steps=("retrieval",),
        requires=("library",),
        produces="retrieval",
    ),
    Block(
        name="task",
        title="运行任务并生成交付",
        steps=("task",),
        requires=("retrieval",),
        produces="task",
    ),
    Block(
        name="report",
        title="汇总工作区结果",
        steps=("report",),
        requires=(),
        produces="report",
        scope="workspace",
    ),
)

BLOCK_BY_NAME: dict[str, Block] = {block.name: block for block in BLOCKS}
PER_TASK_BLOCKS: tuple[str, ...] = tuple(
    block.name for block in BLOCKS if block.scope == "task"
)
ALL_BLOCKS: tuple[str, ...] = tuple(block.name for block in BLOCKS)

# Retired sub-stage names remain accepted so existing scripts and DSH tools do
# not break, but they now resolve to the merged block that owns them.
ALIASES: dict[str, str] = {
    "source_scan": "prepare",
    "extract": "build",
    "curate": "build",
    "prepare_reviews": "build",
    "review": "audit",
    "finalize_review": "audit",
    "publish_library": "publish",
}

# A group is a compatibility name for a sequence of atomic blocks.  ``deliver``
# used to be one block; retrieval and task have separate artifacts, so callers
# that still ask for ``deliver`` get both blocks in order.
BLOCK_GROUPS: dict[str, tuple[str, ...]] = {
    "deliver": ("retrieval", "task"),
}

STEP_ARTIFACTS: dict[str, str] = {
    "source_scan": "packets",
    "extract": "extraction",
    "curate": "curated",
    "prepare_reviews": "frozen",
    "review": "review",
    "finalize_review": "review",
    "publish_library": "library",
    "retrieval": "retrieval",
    "task": "task",
    "report": "report",
}


def resolve_block(name: str) -> Block:
    """Return the block for a current or retired stage name."""
    canonical = ALIASES.get(name, name)
    if canonical in BLOCK_GROUPS:
        raise ValueError(f"{name!r} is a block group; use resolve_blocks() to expand it")
    try:
        return BLOCK_BY_NAME[canonical]
    except KeyError as exc:
        raise ValueError(f"unknown block or stage: {name!r}") from exc


def resolve_blocks(value: str | Iterable[str] | None, *, default: Iterable[str] = PER_TASK_BLOCKS) -> tuple[str, ...]:
    """Normalize a block selection from a CLI/config value.

    ``None`` selects the default per-task sequence.  ``all`` selects every
    per-task block.  Aliases are accepted and de-duplicated in first-seen order.
    """
    if value is None:
        names: list[str] = list(default)
    elif isinstance(value, str):
        names = [item.strip() for item in value.split(",") if item.strip()]
    else:
        names = [str(item).strip() for item in value if str(item).strip()]
    if not names:
        return ()
    resolved: list[str] = []
    for name in names:
        if name == "all":
            candidates: Iterable[str] = PER_TASK_BLOCKS
        elif name == "all-blocks":
            candidates = ALL_BLOCKS
        elif name in BLOCK_GROUPS:
            candidates = BLOCK_GROUPS[name]
        else:
            candidates = (resolve_block(name).name,)
        for canonical in candidates:
            if canonical not in resolved:
                resolved.append(canonical)
    return tuple(resolved)


def artifacts(task_root: Path, config: Mapping[str, Any]) -> dict[str, Path]:
    """Resolve every artifact this block model can consume or produce."""
    task_root = Path(task_root)
    task_id = str(config.get("task_id") or task_root.name)
    retrieval = str(config.get("retrieval_attempt") or "retrieval_v1")
    task_attempt = str(config.get("task_attempt") or "task_01")
    extraction_root = task_root / "runs" / task_id / "extraction_v1"
    review_root = task_root / "runs" / task_id / "review_v1"
    return {
        "packets": task_root / "inputs" / "focus_context_packets.json",
        "extraction": extraction_root / "summary.json",
        "curated": extraction_root / "curated" / "summary.json",
        "frozen": task_root / "inputs" / "frozen_components.json",
        "review": review_root / "summary.json",
        "library": task_root / "outputs" / "full_library" / "manifest.json",
        "retrieval": task_root / "attempts" / retrieval / "result.json",
        "task": task_root / "task_attempts" / task_attempt / "run_manifest.json",
        "report": task_root / "summary.json",
    }


def publish_mode(config: Mapping[str, Any]) -> str:
    """Return ``reviewed``, ``unreviewed`` or ``migration_direct``.

    ``publish_mode`` is the historical key; ``publish.mode`` is the new nested
    form.  Missing configuration keeps the reviewed default.
    """
    nested = config.get("publish")
    if isinstance(nested, Mapping) and isinstance(nested.get("mode"), str):
        mode = nested["mode"]
    else:
        mode = config.get("publish_mode")
    if mode in {None, ""}:
        return "reviewed"
    mode = str(mode)
    if mode not in {"reviewed", "unreviewed", "migration_direct"}:
        raise ValueError(f"unknown publish mode: {mode!r}")
    return mode


def block_requirements(block: Block, config: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the artifact keys a block needs before it may run."""
    if block.name != "publish":
        return block.requires
    mode = publish_mode(config)
    if mode == "migration_direct":
        return ("curated",)
    if mode == "unreviewed":
        return ("frozen",)
    return ("review",)


def block_status(
    name: str,
    task_root: Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe whether a block is ready, blocked or already complete.

    This is the ``can_run`` check callers (and agents) rely on.  It only looks
    at files, so a model cannot claim a prerequisite that does not exist.
    """
    block = resolve_block(name)
    paths = artifacts(task_root, config)
    requires = block_requirements(block, config)
    missing = [
        {"artifact": key, "path": str(paths[key])}
        for key in requires
        if not paths[key].is_file()
    ]
    if block.name == "prepare" and config.get("source_scan_mode") != "migration":
        candidate = config.get("candidate_file")
        if isinstance(candidate, str):
            candidate_path = Path(candidate)
            if not candidate_path.is_absolute():
                candidate_path = release_root() / candidate_path
            if not candidate_path.is_file():
                missing.append({"artifact": "candidate", "path": str(candidate_path)})
    produced = paths[block.produces]
    return {
        "block": block.name,
        "title": block.title,
        "steps": list(block.steps),
        "requires": list(requires),
        "missing": missing,
        "produces": str(produced),
        "completed": produced.is_file(),
        "ready": not missing,
        "status": "completed" if produced.is_file() else ("ready" if not missing else "blocked"),
    }


def selected_from_config(
    config: Mapping[str, Any],
    override: str | Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Resolve the block selection from CLI override or task configuration."""
    if override is not None:
        return resolve_blocks(override)
    configured = config.get("blocks")
    if isinstance(configured, (list, tuple, str)) and configured:
        return resolve_blocks(configured)
    return resolve_blocks(None)


def step_artifact(step: str, task_root: Path, config: Mapping[str, Any]) -> Path | None:
    key = STEP_ARTIFACTS.get(step)
    if key is None:
        return None
    return artifacts(task_root, config)[key]


def step_enabled(step: str, config: Mapping[str, Any]) -> bool:
    """Whether a step is part of the selected behavior for this workspace."""
    if step == "finalize_review":
        return bool(config.get("apply_review_revisions_without_rereview"))
    return True