#!/usr/bin/env python3
"""Freeze the migration examples of one V3 scenario as read-only history packets.

This is the first step of the transformation-extraction path.  The examples,
repository policy, language and scanner backend all come from the scenario's
``spec.yaml``; the same tool serves ``windows_to_kylin``, ``cuda_to_musa`` and
``ipp_to_vsipl``.  The corpus is build-time material only: it is not a task
workspace and is never staged into the published methodology library.

Layout per example::

    examples/<task_id>/
      EXAMPLE.md                 # what the example is and how to read it
      example.json               # provenance, roles, API surface, selected files
      repo/<repo path>           # the migration tree in the real source layout
      inputs/focus_context_packets.json

``repo/`` merges all four roles at their upstream paths so local ``#include``
directives resolve exactly as they do in the project:

* ``before`` — source-platform implementation and private headers (from ``work/``)
* ``after``  — completed target-platform implementation (from ``gold/``)
* ``context``— shared headers, callers and contract files
* ``tests``  — tests that exercise the layer

The packet file is produced by the existing migration scanner
(``prepare_migration_inputs.build_inputs``) and then re-labelled: units from
``after`` become focus units, everything else becomes context.  Files the
parser cannot turn into symbols (source-platform-only sources, generated-config
headers) keep a single whole-file unit so no role file disappears.  The scanner
semantics are unchanged; this tool only classifies its output by role.

Usage::

    python3 tools/build_history_corpus.py \
        --spec v3/windows_to_kylin/history/spec.yaml --force

    python3 tools/build_history_corpus.py \
        --spec v3/windows_to_kylin/history/spec.yaml --verify
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
if str(PROJECT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Imported after the path adjustment above.
from component_method.source_scan.prepare_migration_inputs import build_inputs  # noqa: E402
from shared.harness import agent_view  # noqa: E402


SPEC_SCHEMA = "migration-history-spec-v1"
CORPUS_SCHEMA = "migration-history-corpus-v1"
EXAMPLE_SCHEMA = "migration-history-example-v1"
LOCK_SCHEMA = "migration-history-lock-v1"

# Default policy for the windows_to_kylin corpus.  Any other scenario must
# declare its repository policy in the spec: adding a library_source repository
# is a deliberate SPLIT.md change, not something this tool infers.
DEFAULT_ALLOWED_REPOS = {"libuv", "libarchive"}
DEFAULT_HELD_OUT_REPOS = {"poco", "nginx", "curl", "opencv"}

# Scanner identity per language.  A scenario may override ``language`` and
# ``backend_id``; the extension list only controls which files are scanned.
LANGUAGE_DEFAULTS: dict[str, dict[str, Any]] = {
    "cpp": {
        "backend_id": "cpp@1",
        "extensions": [".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"],
        "caller_suffixes": [".c"],
        "header_scan": True,
    },
    "python": {
        "backend_id": "python@1",
        "extensions": [".py"],
        "caller_suffixes": [".py"],
        "header_scan": False,
    },
}

ROLE_DIRS = ("before", "after", "context", "tests")

INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.MULTILINE)
HEADER_SUFFIXES = {".h", ".hh", ".hpp", ".hxx"}
MAX_HEADER_DEPTH = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _repo_name(url: str) -> str:
    name = str(url or "").rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def _language_profile(spec: dict[str, Any]) -> dict[str, Any]:
    scenario = str(spec.get("scenario") or "")
    language = str(
        spec.get("language") or ("python" if scenario == "cuda_to_musa" else "cpp")
    )
    defaults = LANGUAGE_DEFAULTS.get(language)
    if defaults is None:
        raise RuntimeError(
            f"unsupported history language {language!r}; "
            f"expected one of {sorted(LANGUAGE_DEFAULTS)}"
        )
    backend_id = str(spec.get("backend_id") or defaults["backend_id"])
    if not backend_id.startswith(f"{language}@"):
        raise RuntimeError(f"backend_id must start with {language}@: {backend_id!r}")
    return {
        "language": language,
        "backend_id": backend_id,
        "scan_extensions": [
            str(item) for item in spec.get("scan_extensions") or defaults["extensions"]
        ],
        "caller_suffixes": [
            str(item) for item in spec.get("caller_suffixes") or defaults["caller_suffixes"]
        ],
        "header_scan": bool(
            defaults["header_scan"] if spec.get("header_scan") is None else spec["header_scan"]
        ),
    }


def _load_spec(path: Path) -> dict[str, Any]:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or spec.get("schema") != SPEC_SCHEMA:
        raise RuntimeError(f"history spec must use schema {SPEC_SCHEMA}: {path}")
    scenario = str(spec.get("scenario") or "").strip()
    if not scenario:
        raise RuntimeError(f"history spec needs a scenario: {path}")
    allowed = spec.get("library_source_repos")
    if allowed is None:
        if scenario == "windows_to_kylin":
            allowed = sorted(DEFAULT_ALLOWED_REPOS)
        else:
            raise RuntimeError(
                f"history spec for {scenario} must declare library_source_repos"
            )
    if not isinstance(allowed, list) or not allowed:
        raise RuntimeError("library_source_repos must be a non-empty list")
    held_out = spec.get("held_out_repos")
    if held_out is None:
        held_out = sorted(DEFAULT_HELD_OUT_REPOS) if scenario == "windows_to_kylin" else []
    if not isinstance(held_out, list):
        raise RuntimeError("held_out_repos must be a list")
    overlap = {str(item).lower() for item in allowed} & {str(item).lower() for item in held_out}
    if overlap:
        raise RuntimeError(f"a repository cannot be both source and held out: {sorted(overlap)}")
    examples = spec.get("examples")
    if not isinstance(examples, list) or not examples:
        raise RuntimeError(f"history spec has no examples: {path}")
    seen: set[str] = set()
    for example in examples:
        task_id = example.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError(f"history example has no task_id: {example!r}")
        if task_id in seen:
            raise RuntimeError(f"duplicate history task_id: {task_id}")
        seen.add(task_id)
    return {
        **spec,
        "scenario": scenario,
        "library_id": str(
            spec.get("library_id")
            or f"{scenario.replace('_', '-')}-transformations"
        ),
        "library_source_repos": [str(item) for item in allowed],
        "held_out_repos": [str(item) for item in held_out],
        **_language_profile(spec),
    }


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _example_roots(task_root: Path) -> tuple[Path, Path]:
    work = task_root / "work"
    gold = task_root / "gold"
    if not work.is_dir():
        raise RuntimeError(
            f"task workspace is missing: {work}; run prepare.sh for {task_root.name} first"
        )
    if not gold.is_dir():
        raise RuntimeError(
            f"task gold is missing: {gold}; run prepare.sh for {task_root.name} first"
        )
    return work, gold


def _load_task(
    task_root: Path,
    *,
    allowed_repos: Iterable[str],
    held_out_repos: Iterable[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    task_yaml_path = task_root / "task.yaml"
    provenance_path = task_root / "provenance.json"
    if not task_yaml_path.is_file():
        raise RuntimeError(f"task.yaml is missing: {task_yaml_path}")
    if not provenance_path.is_file():
        raise RuntimeError(f"provenance.json is missing: {provenance_path}")
    task = yaml.safe_load(task_yaml_path.read_text(encoding="utf-8")) or {}
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    source = task.get("source") or provenance.get("source") or {}
    repo = _repo_name(str(source.get("repo") or provenance.get("repo") or ""))
    allowed = {str(item).lower() for item in allowed_repos}
    held_out = {str(item).lower() for item in held_out_repos}
    if repo.lower() in held_out:
        raise RuntimeError(f"held-out repository cannot enter history: {repo}")
    if repo.lower() not in allowed:
        raise RuntimeError(
            f"repository {repo!r} is not declared in this spec's library_source_repos; "
            "update SPLIT.md and the spec together"
        )
    return task, provenance


def _copy_file(work_root: Path, relative: str, workspace: Path) -> Path:
    source = (work_root / relative).resolve()
    if not source.is_file():
        raise RuntimeError(f"history source file is missing: {source}")
    destination = workspace / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if _sha256_file(destination) != _sha256_file(source):
            raise RuntimeError(
                "two roles claim the same path with different content: "
                f"{relative}"
            )
        return destination
    shutil.copy2(source, destination)
    return destination


def _header_index(work_root: Path) -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    """Map repo-relative paths and basenames to local header files."""
    by_relative: dict[str, list[Path]] = {}
    by_name: dict[str, list[Path]] = {}
    for path in sorted(work_root.rglob("*")):
        if not path.is_file() or path.suffix not in HEADER_SUFFIXES:
            continue
        relative = path.relative_to(work_root).as_posix()
        by_relative.setdefault(relative, []).append(path)
        by_name.setdefault(path.name, []).append(path)
    return by_relative, by_name


def _resolve_header(
    name: str,
    including_relative: str,
    work_root: Path,
    include_roots: Iterable[str],
    by_relative: dict[str, list[Path]],
    by_name: dict[str, list[Path]],
) -> Path | None:
    """Resolve a local include without leaving the example workspace."""
    including_dir = Path(including_relative).parent
    candidates = [
        including_dir / name,
        *(Path(root) / name for root in include_roots),
        Path(name),
    ]
    for candidate in candidates:
        for path in by_relative.get(candidate.as_posix().lstrip("./"), []):
            return path
    matches = by_name.get(Path(name).name, [])
    if len(matches) == 1:
        return matches[0]
    return None


def _select_headers(
    work_root: Path,
    seeds: list[str],
    include_roots: Iterable[str],
    limit: int = 80,
) -> list[dict[str, str]]:
    """Follow local includes from the core files and return selected headers."""
    by_relative, by_name = _header_index(work_root)
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    first_seen_by: dict[str, str] = {}
    frontier = list(seeds)
    for _depth in range(MAX_HEADER_DEPTH):
        next_frontier: list[str] = []
        for relative in frontier:
            if relative in seen:
                continue
            seen.add(relative)
            path = work_root / relative
            if not path.is_file():
                continue
            for name in INCLUDE_RE.findall(_read_text(path)):
                resolved = _resolve_header(
                    name, relative, work_root, include_roots, by_relative, by_name
                )
                if resolved is None:
                    continue
                header_relative = resolved.relative_to(work_root).as_posix()
                if header_relative in seen:
                    continue
                if header_relative not in first_seen_by:
                    first_seen_by[header_relative] = relative
                    selected.append(
                        {
                            "path": header_relative,
                            "included_by": relative,
                        }
                    )
                    next_frontier.append(header_relative)
                    if len(selected) >= limit:
                        return selected
        frontier = next_frontier
        if not frontier:
            break
    return selected


def _select_callers(
    work_root: Path,
    example: dict[str, Any],
    core_relative: set[str],
    *,
    suffixes: Iterable[str] = (".c",),
) -> list[dict[str, Any]]:
    symbols = [str(item) for item in example.get("api_symbols") or []]
    roots = [str(item) for item in example.get("caller_roots") or ["."]]
    excluded_dirs = {str(item) for item in example.get("caller_exclude_dirs") or []}
    excluded_globs = [str(item) for item in example.get("caller_exclude_globs") or []]
    limit = int(example.get("caller_limit") or 8)
    suffixes = tuple(str(item) for item in suffixes)
    found: list[tuple[int, str]] = []
    for root in roots:
        root_path = work_root / root
        if not root_path.is_dir():
            continue
        for path in sorted(root_path.rglob("*")):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            relative = path.relative_to(work_root).as_posix()
            if relative in core_relative:
                continue
            parts = set(Path(relative).parts)
            if parts & excluded_dirs:
                continue
            if any(fnmatch.fnmatch(path.name, pattern) for pattern in excluded_globs):
                continue
            text = _read_text(path)
            hits = sum(text.count(symbol) for symbol in symbols)
            if hits:
                found.append((hits, relative))
    found.sort(key=lambda item: (-item[0], item[1]))
    return [{"path": relative, "symbol_hits": hits} for hits, relative in found[:limit]]


def _write_example_markdown(
    path: Path,
    task: dict[str, Any],
    example: dict[str, Any],
    files: dict[str, list[str]],
) -> None:
    source = task.get("source") or {}
    spec_text = str(task.get("spec") or "").strip()
    lines = [
        f"# Migration example: {example['task_id']}",
        "",
        f"- Capability: `{example['capability']}`",
        f"- Source: {source.get('repo', '')} @ `{source.get('commit', '')}`",
        f"- License: {source.get('license', 'unknown')}",
        f"- Removed on the target: {', '.join(task.get('prepare', {}).get('remove', []) or [])}",
        "",
        "## Layout",
        "",
        "`repo/` is the migration workspace in the project's real source layout.",
        "It contains both sides of the completed migration, so local `#include`",
        "directives resolve exactly as they do upstream.  `example.json` records",
        "which files play which role:",
        "",
        "- **before** — source-platform implementation and its private headers:",
        *[f"  - `{item}`" for item in files["before"]],
        "- **after** — completed target-platform implementation:",
        *[f"  - `{item}`" for item in files["after"]],
        "- **context** — shared headers, callers and contract files",
        f"  ({len(files['context'])} files listed in `example.json`).",
        "- **tests** — tests that exercise the layer",
        f"  ({len(files['tests'])} files listed in `example.json`).",
        "",
        "The migration is complete.  The after files are the answer to the before",
        "files; context and tests show the surrounding contract.",
        "",
        "## Task spec",
        "",
        spec_text or "(no spec recorded)",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _unit_key(unit: dict[str, Any]) -> tuple[str, str]:
    return (
        str(unit.get("file_id") or ""),
        str(unit.get("unit_key") or unit.get("unit_id") or ""),
    )


def _fallback_unit(workspace: Path, relative: str, reason: str) -> dict[str, Any]:
    """A whole-file unit for a file the parser could not turn into symbols.

    Some upstream files (Windows-only sources, generated-config headers) cannot
    be parsed without a generated ``config.h`` or a Windows toolchain.  The
    scanner reports them as gaps; the history packet still needs their identity
    and span so the extractor can read them.
    """
    path = workspace / relative
    line_count = len(_read_text(path).splitlines()) if path.is_file() else 1
    return {
        "file_id": relative,
        "unit_id": f"{relative}#file",
        "unit_key": f"file:{relative}",
        "kind": "file",
        "qualified_name": relative,
        "signature": "",
        "language": "cpp",
        "backend_id": "cpp@1",
        "line_start": 1,
        "line_end": max(1, line_count),
        "fallback": True,
        "fallback_reason": reason,
    }


def _history_payload(
    raw: dict[str, Any],
    *,
    workspace: Path,
    role_files: dict[str, list[str]],
    task_id: str,
    capability: str,
) -> dict[str, Any]:
    """Re-label scanner output: after units are focus, everything else context."""
    ordered: dict[tuple[str, str], dict[str, Any]] = {}
    visible: set[str] = set()
    for packet in raw.get("packets", []):
        visible.update(packet.get("visible_files") or [])
        for unit in [*(packet.get("focus_units") or []), *(packet.get("context_units") or [])]:
            if isinstance(unit, dict):
                ordered.setdefault(_unit_key(unit), unit)

    gap_reasons = {
        str(item.get("file_id")): str(item.get("reason") or "unparsed")
        for item in raw.get("gaps") or []
        if isinstance(item, dict)
    }
    after_set = set(role_files["after"])
    parsed_files = {str(unit["file_id"]) for unit in ordered.values()}
    fallback_files: list[str] = []
    for role in ("after", "before", "context", "tests"):
        for relative in role_files[role]:
            if relative in parsed_files:
                continue
            ordered[("file", relative)] = _fallback_unit(
                workspace, relative, gap_reasons.get(relative, "no source units")
            )
            parsed_files.add(relative)
            fallback_files.append(relative)

    units = list(ordered.values())
    if not units:
        raise RuntimeError(f"source scan produced no units for {task_id}")

    focus = [unit for unit in units if str(unit.get("file_id") or "") in after_set]
    focus_keys = {_unit_key(unit) for unit in focus}
    context = [unit for unit in units if _unit_key(unit) not in focus_keys]
    if not focus:
        raise RuntimeError(f"history example {task_id} produced no focus units")

    focus_files = sorted({str(unit["file_id"]) for unit in focus})
    context_files = sorted({str(unit["file_id"]) for unit in context})
    seed_evidence = []
    for relative in focus_files:
        path = workspace / relative
        line_count = len(_read_text(path).splitlines()) if path.is_file() else 1
        seed_evidence.append(
            {
                "file_id": relative,
                "line_start": 1,
                "line_end": max(1, line_count),
            }
        )

    packet_id = f"history_{task_id}"
    packet = {
        "packet_id": packet_id,
        "candidate_ids": [f"history:{task_id}"],
        "candidate_ranks": [1],
        "focus_groups": [
            {
                "candidate_id": f"history:{task_id}",
                "candidate_rank": 1,
                "focus_units": focus,
                "seed_evidence": seed_evidence,
                "candidate_unit_count": len(focus),
                "expanded_unit_count": 0,
            }
        ],
        "focus_units": focus,
        "context_units": context,
        "focus_files": focus_files,
        "context_files": context_files,
        "visible_files": sorted(visible | set(focus_files) | set(context_files)),
        "visible_unit_count": len(units),
        "focus_unit_count": len(focus),
        "context_unit_count": len(context),
        "fallback_file_count": len(fallback_files),
        "role": "history",
        "example_id": task_id,
    }
    return {
        **raw,
        "schema": raw.get("schema", "migration-focus-context-packets-v1"),
        "task_id": task_id,
        "packet_count": 1,
        "packets": [packet],
        "history": {
            "schema": "migration-history-packet-v1",
            "example_id": task_id,
            "capability": capability,
            "workspace": workspace.name,
            "roles": {role: list(items) for role, items in role_files.items()},
            "focus_role": "after",
            "fallback_files": fallback_files,
            "focus_files": focus_files,
            "context_files": context_files,
        },
    }


def _build_packets(
    workspace: Path,
    example: dict[str, Any],
    task_id: str,
    role_files: dict[str, list[str]],
    *,
    scenario: str,
    language: str,
    backend_id: str,
    scan_extensions: list[str],
) -> dict[str, Any]:
    config = {
        "task_id": task_id,
        "scenario": scenario,
        "language": language,
        "backend_id": backend_id,
        "repository_root": str(workspace),
        "packet_config": {
            "extensions": scan_extensions,
            "excluded_directory_names": [".git", "__pycache__"],
            "excluded_filenames": [],
            "max_file_bytes": 8 * 1024 * 1024,
            "max_files_per_packet": 1_000_000,
            "max_units_per_packet": 1_000_000,
        },
    }
    with tempfile.TemporaryDirectory(prefix=f"history-scan-{task_id}-") as temporary:
        scan_root = Path(temporary)
        build_inputs(config, task_root=scan_root)
        raw_path = scan_root / "inputs" / "focus_context_packets.json"
        raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))

    example_root = workspace.parent
    inputs = example_root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "source_scan_packets.json").write_text(
        json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    payload = _history_payload(
        raw_payload,
        workspace=workspace,
        role_files=role_files,
        task_id=task_id,
        capability=str(example.get("capability") or ""),
    )
    packet_path = inputs / "focus_context_packets.json"
    packet_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    packet = payload["packets"][0]
    return {
        "path": packet_path.relative_to(example_root).as_posix(),
        "sha256": _sha256_file(packet_path),
        "packet_id": packet["packet_id"],
        "focus_file_count": len(packet["focus_files"]),
        "context_file_count": len(packet["context_files"]),
        "focus_unit_count": packet["focus_unit_count"],
        "context_unit_count": packet["context_unit_count"],
        "source_unit_count": payload.get("source_unit_count"),
        "fallback_file_count": packet["fallback_file_count"],
        "gaps": len(payload.get("gaps") or []),
    }


def _materialize_example(
    *,
    task_root: Path,
    output_root: Path,
    example: dict[str, Any],
    spec: dict[str, Any],
    force: bool,
) -> dict[str, Any]:
    task_id = example["task_id"]
    task, provenance = _load_task(
        task_root,
        allowed_repos=spec["library_source_repos"],
        held_out_repos=spec["held_out_repos"],
    )
    work_root, gold_root = _example_roots(task_root)

    example_root = output_root / "examples" / task_id
    if example_root.exists() and any(example_root.iterdir()):
        metadata_path = example_root / "example.json"
        generated = None
        if metadata_path.is_file():
            try:
                generated = json.loads(metadata_path.read_text(encoding="utf-8")).get(
                    "generated_by"
                )
            except (OSError, json.JSONDecodeError):
                generated = None
        if generated != "tools/build_history_corpus.py" and not force:
            raise RuntimeError(
                f"refusing to replace non-generated history example: {example_root}"
            )
        shutil.rmtree(example_root)
    example_root.mkdir(parents=True, exist_ok=True)
    workspace = example_root / "repo"

    before_files = list(provenance.get("source_files") or [])
    after_files = list(provenance.get("gold_files") or [])
    test_files = list(provenance.get("test_files") or [])
    if not before_files or not after_files:
        raise RuntimeError(f"{task_id} has no source_files or gold_files in provenance")

    core_relative = set(before_files) | set(after_files)
    with tempfile.TemporaryDirectory(prefix=f"history-context-{task_id}-") as temporary:
        # Context is selected from the same filtered tree the migration agent
        # would see.  The raw work/ also contains evaluator backends and
        # alternative-target prompt families; those are not migration context.
        context_work = Path(temporary) / "work"
        agent_view.copy_agent_view(work_root, context_work, task)
        headers = (
            _select_headers(
                context_work,
                seeds=[*before_files, *after_files, *test_files],
                include_roots=[str(item) for item in example.get("include_roots") or ["."]],
            )
            if spec["header_scan"]
            else []
        )
        callers = _select_callers(
            context_work,
            example,
            core_relative,
            suffixes=spec["caller_suffixes"],
        )
    context_relative: set[str] = set()
    for item in headers:
        if item["path"] not in core_relative:
            context_relative.add(item["path"])
    for item in callers:
        if item["path"] not in core_relative:
            context_relative.add(item["path"])

    role_files = {
        "before": before_files,
        "after": after_files,
        "context": sorted(context_relative),
        "tests": test_files,
    }
    # Copy into one source-layout tree so local includes resolve upstream-like.
    for role, source_root in (
        ("context", work_root),
        ("tests", work_root),
        ("before", work_root),
        ("after", gold_root),
    ):
        for relative in role_files[role]:
            _copy_file(source_root, relative, workspace)

    packet = _build_packets(
        workspace,
        example,
        task_id,
        role_files,
        scenario=spec["scenario"],
        language=spec["language"],
        backend_id=spec["backend_id"],
        scan_extensions=spec["scan_extensions"],
    )

    source = task.get("source") or {}
    metadata = {
        "schema": EXAMPLE_SCHEMA,
        "generated_by": "tools/build_history_corpus.py",
        "generated_at": _now(),
        "task_id": task_id,
        "capability": example.get("capability"),
        "scenario": spec["scenario"],
        "library_id": spec["library_id"],
        "source": {
            "repo": source.get("repo") or provenance.get("repo"),
            "commit": source.get("commit") or provenance.get("commit"),
            "tag": source.get("tag") or provenance.get("tag"),
            "license": source.get("license") or provenance.get("license"),
        },
        "target": task.get("target") or {},
        "spec": str(task.get("spec") or "").strip(),
        "api_symbols": list(example.get("api_symbols") or []),
        "removed_paths": list(provenance.get("remove") or []),
        "workspace": workspace.name,
        "files": role_files,
        "context_selection": {
            "headers": headers,
            "callers": callers,
        },
        "packet": packet,
    }
    (example_root / "example.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_example_markdown(example_root / "EXAMPLE.md", task, example, role_files)
    return metadata


def _tree_files(root: Path, *, exclude: set[str] | None = None) -> list[Path]:
    excluded = exclude or set()

    def is_excluded(relative: str) -> bool:
        return any(
            relative == item or relative.startswith(item + "/") for item in excluded
        )

    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not is_excluded(path.relative_to(root).as_posix())
    )


def _tree_digest(root: Path, *, exclude: set[str] | None = None) -> tuple[str, dict[str, str]]:
    digest = hashlib.sha256()
    files = _tree_files(root, exclude=exclude)
    hashes: dict[str, str] = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        file_hash = _sha256_file(path)
        hashes[relative] = file_hash
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), hashes


def _write_index(
    output_root: Path,
    spec_path: Path,
    spec: dict[str, Any],
    examples: list[dict[str, Any]],
) -> dict[str, Any]:
    index = {
        "schema": CORPUS_SCHEMA,
        "generated_by": "tools/build_history_corpus.py",
        "generated_at": _now(),
        "scenario": spec["scenario"],
        "library_id": spec["library_id"],
        "language": spec["language"],
        "backend_id": spec["backend_id"],
        "policy": {
            "library_source_repos": spec["library_source_repos"],
            "held_out_repos": spec["held_out_repos"],
        },
        "spec": spec_path.name,
        "spec_sha256": _sha256_file(spec_path),
        "examples": examples,
        "totals": {
            "examples": len(examples),
            "focus_files": sum(item["packet"]["focus_file_count"] for item in examples),
            "context_files": sum(item["packet"]["context_file_count"] for item in examples),
            "focus_units": sum(item["packet"]["focus_unit_count"] for item in examples),
            "context_units": sum(item["packet"]["context_unit_count"] for item in examples),
            "fallback_files": sum(
                item["packet"].get("fallback_file_count", 0) for item in examples
            ),
        },
    }
    (output_root / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sources = ", ".join(spec["library_source_repos"])
    held_out = ", ".join(spec["held_out_repos"]) or "none"
    (output_root / "README.md").write_text(
        "\n".join(
            [
                f"# Migration history corpus: {spec['scenario']}",
                "",
                f"Generated by `tools/build_history_corpus.py` from {len(examples)}",
                f"`library_source` tasks ({sources}).  This is",
                "build-time material for transformation extraction; it is not a",
                "task workspace and is not part of the published library.",
                "",
                "Each `examples/<task_id>/` directory contains:",
                "",
                "- `repo/` — the migration workspace in the project's real source",
                "  layout, containing both sides of the completed migration;",
                "- `example.json` — role assignment for every file: `before`",
                "  (source platform), `after` (completed target platform),",
                "  `context` (shared headers, callers, contracts) and `tests`;",
                "- `EXAMPLE.md` — the same roles in prose, plus the task spec;",
                "- `inputs/source_scan_packets.json` — raw scanner output;",
                "- `inputs/focus_context_packets.json` — the same scan re-labelled",
                "  with `after` units as focus and everything else as context.",
                "",
                f"Split rule: only `library_source` repositories ({sources}) may",
                f"appear here.  Held-out repositories ({held_out}) must not be",
                "added.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return index


def _write_lock(output_root: Path, spec_path: Path) -> dict[str, Any]:
    lock_path = output_root / "lock.json"
    digest, hashes = _tree_digest(output_root, exclude={"lock.json", "runs"})
    lock = {
        "schema": LOCK_SCHEMA,
        "created_at": _now(),
        "spec_sha256": _sha256_file(spec_path),
        "tool_sha256": _sha256_file(Path(__file__).resolve()),
        "digest": digest,
        "file_count": len(hashes),
        "files": hashes,
    }
    lock_path.write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return lock


def _verify(output_root: Path) -> int:
    lock_path = output_root / "lock.json"
    if not lock_path.is_file():
        raise RuntimeError(f"history lock is missing: {lock_path}")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    digest, hashes = _tree_digest(output_root, exclude={"lock.json", "runs"})
    changed = sorted(
        path
        for path in set(hashes) | set(lock.get("files") or {})
        if hashes.get(path) != (lock.get("files") or {}).get(path)
    )
    ok = digest == lock.get("digest") and not changed
    print(
        json.dumps(
            {
                "status": "ok" if ok else "drift",
                "digest": digest,
                "expected": lock.get("digest"),
                "file_count": len(hashes),
                "changed": changed[:20],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


def build(spec_path: Path, *, force: bool) -> dict[str, Any]:
    spec = _load_spec(spec_path)
    spec_dir = spec_path.parent
    dataset_root = _resolve(spec_dir, str(spec.get("dataset_root") or "../tasks"))
    output_root = _resolve(spec_dir, str(spec.get("output_root") or "."))
    output_root.mkdir(parents=True, exist_ok=True)

    examples: list[dict[str, Any]] = []
    for example in spec["examples"]:
        task_id = example["task_id"]
        task_root = dataset_root / task_id
        if not task_root.is_dir():
            raise RuntimeError(f"history task is missing: {task_root}")
        metadata = _materialize_example(
            task_root=task_root,
            output_root=output_root,
            example=example,
            spec=spec,
            force=force,
        )
        examples.append(
            {
                "task_id": task_id,
                "capability": metadata["capability"],
                "repo": metadata["source"]["repo"],
                "commit": metadata["source"]["commit"],
                "before_files": len(metadata["files"]["before"]),
                "after_files": len(metadata["files"]["after"]),
                "context_files": len(metadata["files"]["context"]),
                "test_files": len(metadata["files"]["tests"]),
                "packet": metadata["packet"],
            }
        )

    index = _write_index(output_root, spec_path, spec, examples)
    lock = _write_lock(output_root, spec_path)
    return {"index": index, "lock": lock}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec",
        default=str(ROOT / "v3" / "windows_to_kylin" / "history" / "spec.yaml"),
        help="history spec path",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace generated examples even when they already exist",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify the existing corpus against lock.json instead of rebuilding",
    )
    args = parser.parse_args()
    spec_path = Path(args.spec).expanduser().resolve()
    spec = _load_spec(spec_path)
    output_root = _resolve(spec_path.parent, str(spec.get("output_root") or "."))
    if args.verify:
        return _verify(output_root)

    result = build(spec_path, force=args.force)
    print(
        json.dumps(
            {
                "output": str(output_root),
                "examples": [
                    {
                        "task_id": item["task_id"],
                        "capability": item["capability"],
                        "focus_files": item["packet"]["focus_file_count"],
                        "context_files": item["packet"]["context_file_count"],
                        "focus_units": item["packet"]["focus_unit_count"],
                        "context_units": item["packet"]["context_unit_count"],
                        "fallback_files": item["packet"]["fallback_file_count"],
                        "gaps": item["packet"]["gaps"],
                    }
                    for item in result["index"]["examples"]
                ],
                "totals": result["index"]["totals"],
                "digest": result["lock"]["digest"],
                "file_count": result["lock"]["file_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())