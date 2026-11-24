#!/usr/bin/env python3
"""Minimal agent-facing prompt construction.

The prompt carries only what someone doing the work needs:

- the task title,
- the external contract (``task.yaml:spec``),
- the target environment,
- where the repository is and how to build it,
- how to submit.

It must never carry benchmark metadata (scenario, level, family, sequence),
provenance (repository URL, commit), evaluator commands, gate names, or the
existence and content of hidden tests.  ``tools/lint_dataset.py`` renders
every task through this module and fails on those markers, so the rule is
enforced by a check rather than by convention.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:  # package import
    from . import taskmodel
except ImportError:  # direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from shared.harness import taskmodel  # type: ignore

COMPLETION_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

TOOL_LINE = (
    "Use the controlled_bash tool for every inspection, edit, and build command; "
    "you have no other tool."
)
# The method arm has the workflow tools as well, so it swaps the sentence above.
METHOD_TOOL_LINE = (
    "Use controlled_bash for every inspection, edit, and build command; the "
    "component-method workflow tools described below are also available."
)

# The target statement is part of the contract; some specs already spell it
# out.  Render the environment section only when they do not.
_SPEC_TARGET = "target environment"


def system_prompt(environment: str = "") -> str:
    """Return the fixed system prompt, optionally with a target note."""
    extra = f"{environment.strip()}\n" if environment and environment.strip() else ""
    return (
        "You are a software engineer working on the task below.\n"
        f"{TOOL_LINE}\n"
        f"{extra}"
        "The repository is at /workspace and it is the repository root. Work inside it.\n"
        "External network access is disabled: every source file you need is already "
        "present, and no package can be downloaded.\n"
        "When the work is complete, submit by calling controlled_bash once with a "
        "command that exits 0 and prints a line that is exactly "
        f"`{COMPLETION_MARKER}`."
    )


SYSTEM_PROMPT = system_prompt()


def target_line(task: Dict[str, Any]) -> str:
    """Render ``task.yaml:target`` as one neutral environment sentence."""
    target = task.get("target") or {}
    if not isinstance(target, dict):
        return ""
    parts: List[str] = []
    for key, value in target.items():
        if value in (None, "", False):
            continue
        if isinstance(value, (list, tuple, dict)):
            continue
        parts.append(f"{key}={value}")
    if not parts:
        return ""
    return "Target environment: " + ", ".join(parts) + "."


def _path_note(spec: str, workspace: str) -> str:
    """Explain the ``work/`` prefix only when the task text uses it."""
    if "work/" not in spec:
        return ""
    return (
        f"Paths written as `work/...` in the task text are relative to `{workspace}`. "
        "Do not create a nested `work/` directory. "
        f"For example, `work/foo` means `{workspace}/foo`, not `{workspace}/work/foo`."
    )


def render_task_prompt(
    task: Dict[str, Any],
    *,
    root: Optional[os.PathLike | str] = None,
    workspace: str = "/workspace",
    build_dir: str = "/tmp/build",
    extra_environment: Iterable[str] = (),
) -> str:
    """Build the user-facing task message.

    ``extra_environment`` lets a harness add neutral installation facts (for
    example where a target library is installed).  It must not name the
    evaluator, tests, gates or the dataset.
    """
    root_path = Path(root) if root is not None else Path(".")
    title = str(task.get("title") or taskmodel.task_id(task))
    spec = str(task.get("spec") or "").strip()
    build = taskmodel.agent_build_command(task) or ""
    if build:
        build = taskmodel.expand_command(
            build,
            root=root_path,
            work=Path(workspace),
            build=Path(build_dir),
            golden=Path(workspace),
        )

    lines: List[str] = [f"# {title}", "", spec, ""]

    environment = []
    if _SPEC_TARGET not in spec.lower():
        environment.append(target_line(task))
    environment += [str(item).strip() for item in extra_environment if str(item).strip()]
    environment = [item for item in environment if item]
    if environment:
        lines += ["## Environment", ""] + environment + [""]

    # The repository location is stated once, in the system prompt.  Only the
    # task-specific path note (for specs that use a ``work/`` prefix) belongs
    # here.
    note = _path_note(spec, workspace)
    if note:
        lines += [note, ""]

    if build:
        lines += ["## Build", "", "```bash", build, "```", ""]
    else:
        lines += [
            "There is no local build step for this task; check your work as far as "
            "the environment allows.",
            "",
        ]

    lines.append(f"Submit with: `echo {COMPLETION_MARKER}`")
    return "\n".join(lines).rstrip() + "\n"