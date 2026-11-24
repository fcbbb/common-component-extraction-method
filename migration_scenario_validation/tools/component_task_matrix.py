#!/usr/bin/env python3
"""Build a component x task capability matrix for one V3 scenario.

The matrix is the second step of the component-first workflow: after the
transformation library is frozen, decide which tasks each component can serve
and which components each task can use.  Evidence is deliberately mechanical:

* every component card contributes the platform-API tokens mentioned in its
  title, boundary, mapping rules and pitfalls (``CreateFileW``, ``uv_fs_``,
  ``pthread_create`` ...);
* every task package contributes the source-side files under ``work/`` (the
  agent view), searched for the same tokens;
* because published cards stay abstract and often name no platform API, the
  card capability is mapped to an operation family (file / process / thread /
  build) and the family terms are searched in the task title, task id and
  source file names; card prose is compared with task text as a fallback.

The tool only reads; it never writes into a task package.  Output is a JSON
record plus a Markdown table for review.

Usage::

    python3 tools/component_task_matrix.py \
        --library-manifest v3/windows_to_kylin/library_generated/library/manifest.json \
        --tasks-root v3/windows_to_kylin/tasks \
        --output-dir v3/windows_to_kylin/library_generated/matrix
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml

SOURCE_SUFFIXES = {
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".m", ".mm",
    ".s", ".S", ".py", ".java", ".cu", ".hip",
}
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOKENS_PER_FILE = 2_000_000

# Prose tokens that pass the lexical shape test but carry no API evidence.
STOP_TOKENS = {
    "POSIX", "Windows", "Win32", "Linux", "Kylin", "C", "CXX", "API", "APIs",
    "TODO", "NOTE", "OK", "EOF", "NULL", "TRUE", "FALSE", "ID", "IDs",
    "UTF", "ASCII", "CPU", "GPU", "IO", "OS", "ABI", "IPC", "TLS", "DNS",
    "HTTP", "HTTPS", "URL", "URI", "JSON", "XML", "SQL", "SSL", "TCP", "UDP",
    "CMake", "CMakeLists", "Makefile", "GCC", "Clang", "MSVC", "glibc",
    "Source", "Target", "General", "Exception", "Fallback", "When", "Where",
    "This", "That", "The", "Its", "Use", "Keep", "Only", "Every", "Each",
    "Both", "Some", "None", "One", "Two", "Three", "First", "Second",
    "Verification", "Boundary", "Applicability", "Evidence", "Procedure",
    # Generic C types and filesystem names that would otherwise dominate the
    # IDF score without saying anything about the component's capability.
    "ssize_t", "size_t", "off_t", "int64_t", "uint64_t", "int32_t",
    "uint32_t", "errno", "EINTR", "EAGAIN", "EBADF", "EINVAL", "ENOSYS",
    "CIFS", "CephFS", "NFS", "SMB", "EXT4", "XFS",
}

# Loose affinity between card capability labels and task domains.  It is a
# hint for ranking, not a gate: a task may legitimately use a neighbouring
# capability, so a miss is reported instead of suppressed.
CAPABILITY_DOMAIN_HINTS = {
    "file-system/io": {"filesystem", "async-io", "archives"},
    "file-system/metadata": {"filesystem", "archives", "async-io"},
    "file-system": {"filesystem", "archives", "async-io"},
    "process": {"process", "runtime", "async-io"},
    "threading": {"runtime", "async-io"},
    "build": {"build-system"},
    "networking": {"networking"},
    "memory": {"runtime", "async-io"},
    "runtime": {"runtime", "async-io"},
}

# Operation families used when a card stays abstract and names no platform
# API.  Terms are matched as lower-case substrings in the card prose and in
# the task title/spec/source file names, so "directory" covers
# DirectoryIterator_WIN32.cpp and "pthread" covers pthread-thread cards.
OPERATION_FAMILIES = {
    "file": {
        "open", "read", "write", "close", "stat", "lstat", "fstat", "mkdir",
        "rmdir", "unlink", "link", "symlink", "readlink", "rename", "truncate",
        "chmod", "chown", "utime", "access", "fsync", "scandir", "directory",
        "path", "glob", "temp", "descriptor", "file", "filesystem", "dirent",
        "cursor", "iterator", "copy", "send", "seek", "offset", "permission",
        "disk", "archive", "metadata", "hardlink", "symlink",
    },
    "process": {
        "process", "spawn", "fork", "exec", "wait", "kill", "signal", "popen",
        "pipe", "stdio", "daemon", "child", "exit",
    },
    "thread": {
        "thread", "mutex", "rwlock", "semaphore", "condition", "barrier",
        "tls", "pool", "lock", "atomic", "once", "cancel", "worker",
    },
    "build": {
        "cmake", "makefile", "configure", "build", "toolchain", "linker",
        "pkgconfig", "compile",
    },
}

# Capability -> the operation family that carries its evidence.
CAPABILITY_FAMILY = {
    "file-system/io": "file",
    "file-system/metadata": "file",
    "file-system": "file",
    "process": "process",
    "threading": "thread",
    "build": "build",
}

CAMEL_RE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b")
CAPS_RE = re.compile(r"\b[A-Z]{2,}[A-Za-z0-9_]*\b")
SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}")


def api_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for pattern in (CAMEL_RE, CAPS_RE, SNAKE_RE):
        tokens.update(pattern.findall(text))
    return {t for t in tokens if t not in STOP_TOKENS and len(t) >= 4}


def operation_terms(text: str) -> set[str]:
    """Lower-case operation-family terms named by the text."""
    lowered = text.lower()
    found: set[str] = set()
    for terms in OPERATION_FAMILIES.values():
        for term in terms:
            if re.search(rf"\b{re.escape(term)}(?:s|es|ed|ing)?\b", lowered):
                found.add(term)
    return found


def prose_tokens(text: str) -> set[str]:
    return {t.lower() for t in WORD_RE.findall(text) if t.lower() not in {"this", "that", "with", "from", "into", "must", "when", "where", "which", "have", "will", "then", "than", "each", "only"}}


def read_text(path: Path) -> str:
    try:
        stat = path.stat()
        if stat.st_size > MAX_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def iter_source_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", "build", "builddir", "CMakeFiles"} for part in path.parts):
            continue
        if path.suffix not in SOURCE_SUFFIXES:
            continue
        yield path


def load_components(library_manifest: Path) -> list[dict[str, Any]]:
    manifest = json.loads(library_manifest.read_text(encoding="utf-8"))
    base = library_manifest.parent
    components: list[dict[str, Any]] = []
    for item in manifest.get("components") or []:
        meta_rel = item.get("metadata") or ""
        card: dict[str, Any] = {}
        if meta_rel:
            meta_path = (base / meta_rel).resolve()
            if meta_path.is_file():
                card = json.loads(meta_path.read_text(encoding="utf-8"))
        text = "\n".join(
            str(card.get(key) or "")
            for key in ("title", "when_to_use", "boundary")
        )
        text += "\n" + "\n".join(str(x) for x in card.get("mapping_rules") or [])
        text += "\n" + "\n".join(str(x) for x in card.get("pitfalls") or [])
        text += "\n" + "\n".join(str(x) for x in card.get("procedure") or [])
        components.append(
            {
                "bundle_id": item.get("bundle_id") or card.get("bundle_id"),
                "title": item.get("title") or card.get("title") or "",
                "capability": item.get("capability") or card.get("capability") or "",
                "provenance": card.get("provenance") or {},
                "api_tokens": sorted(api_tokens(text)),
                "op_terms": operation_terms(text),
                "prose": prose_tokens(text),
            }
        )
    return components


def load_tasks(tasks_root: Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for task_yaml in sorted(tasks_root.glob("*/task.yaml")):
        root = task_yaml.parent
        try:
            task = yaml.safe_load(task_yaml.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        work = root / "work"
        counts: Counter[str] = Counter()
        file_count = 0
        if work.is_dir():
            for path in iter_source_files(work):
                text = read_text(path)
                if not text:
                    continue
                file_count += 1
                for token in set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", text)):
                    counts[token] += 1
        title = str(task.get("title") or "")
        spec = str(task.get("spec") or "")
        source = task.get("source") or {}
        source_files = [
            str(item)
            for key in ("windows_files", "gold_files", "test_files")
            for item in (source.get(key) or [])
        ]
        title_text = " ".join([title, root.name, *source_files])
        meta_text = " ".join(
            [
                title_text,
                spec,
                str(task.get("notes") or ""),
                str(task.get("family") or ""),
                str(task.get("domain") or ""),
            ]
        )
        tasks.append(
            {
                "task_id": task.get("id") or root.name,
                "package": root.name,
                "title": title,
                "domain": str(task.get("domain") or ""),
                "family": str(task.get("family") or ""),
                "role": str(task.get("role") or ""),
                "has_work": work.is_dir(),
                "work_files": file_count,
                "token_counts": counts,
                "op_terms": operation_terms(meta_text),
                "title_terms": operation_terms(title_text),
                "prose": prose_tokens(meta_text),
            }
        )
    return tasks


def load_planned(slate_path: Path, known: set[str]) -> list[dict[str, Any]]:
    """Slate entries that have no package yet, scored from metadata only."""
    document = yaml.safe_load(slate_path.read_text(encoding="utf-8")) or {}
    planned: list[dict[str, Any]] = []
    for item in document.get("tasks") or []:
        task_id = str(item.get("id") or "")
        if not task_id or task_id in known:
            continue
        title = str(item.get("title") or "")
        source = item.get("source") or {}
        source_files = [str(x) for x in source.get("windows_files") or []]
        title_text = " ".join([title, task_id, *source_files])
        meta_text = " ".join(
            [
                title_text,
                str(item.get("notes") or ""),
                str(item.get("family") or ""),
                str(item.get("domain") or ""),
            ]
        )
        planned.append(
            {
                "task_id": task_id,
                "package": str(item.get("planned_package") or ""),
                "title": title,
                "domain": str(item.get("domain") or ""),
                "family": str(item.get("family") or ""),
                "role": str(item.get("role") or ""),
                "has_work": False,
                "planned": True,
                "work_files": 0,
                "token_counts": Counter(),
                "op_terms": operation_terms(meta_text),
                "title_terms": operation_terms(title_text),
                "prose": prose_tokens(meta_text),
            }
        )
    return planned


def build_matrix(components: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    task_count = len(tasks) or 1
    # Document frequency of each API token across task work trees.
    df: Counter[str] = Counter()
    for task in tasks:
        for token in task["token_counts"]:
            df[token] += 1

    rows: list[dict[str, Any]] = []
    for task in tasks:
        domain = task["domain"].lower()
        scored: list[dict[str, Any]] = []
        for component in components:
            capability = component["capability"].lower()
            hints = CAPABILITY_DOMAIN_HINTS.get(capability, set())
            domain_hint = bool(domain and domain in hints)
            family = CAPABILITY_FAMILY.get(capability, "")
            family_terms = OPERATION_FAMILIES.get(family, set())
            cap_match = bool(task["title_terms"] & family_terms)
            hits = []
            api_score = 0.0
            for token in component["api_tokens"]:
                count = task["token_counts"].get(token, 0)
                if not count:
                    continue
                idf = math.log(1 + task_count / max(1, df[token]))
                weight = idf * (1 + math.log(count))
                api_score += weight
                hits.append({"token": token, "count": count, "weight": round(weight, 3)})
            hits.sort(key=lambda item: item["weight"], reverse=True)
            overlap = component["prose"] & task["prose"]
            union = component["prose"] | task["prose"]
            prose_score = round(len(overlap) / len(union), 4) if union else 0.0
            op_overlap = component["op_terms"] & task["op_terms"]
            family_hit = bool(op_overlap & family_terms)
            op_score = len(op_overlap) + (2.0 if cap_match else 0.0)
            if not cap_match and not hits and prose_score < 0.08:
                continue
            scored.append(
                {
                    "bundle_id": component["bundle_id"],
                    "title": component["title"],
                    "capability": component["capability"],
                    "capability_match": cap_match,
                    "tier": "primary" if cap_match else "secondary",
                    "domain_hint": domain_hint,
                    "operation_family": family,
                    "operation_terms": sorted(op_overlap),
                    "operation_score": round(op_score, 3),
                    "api_score": round(api_score, 3),
                    "api_hits": hits[:8],
                    "prose_score": prose_score,
                    "source_tasks": (component.get("provenance") or {}).get("task_ids") or [],
                }
            )
        scored.sort(
            key=lambda item: (
                item["capability_match"],
                item["operation_score"],
                item["api_score"],
                item["prose_score"],
            ),
            reverse=True,
        )
        rows.append(
            {
                "task_id": task["task_id"],
                "package": task["package"],
                "domain": task["domain"],
                "family": task["family"],
                "has_work": task["has_work"],
                "planned": task.get("planned", False),
                "work_files": task["work_files"],
                "candidates": scored,
            }
        )

    per_component: dict[str, dict[str, Any]] = {
        component["bundle_id"]: {
            "title": component["title"],
            "capability": component["capability"],
            "tasks": [],
        }
        for component in components
    }
    for row in rows:
        for candidate in row["candidates"]:
            if candidate["tier"] != "primary":
                continue
            per_component[candidate["bundle_id"]]["tasks"].append(
                {
                    "task_id": row["task_id"],
                    "capability_match": candidate["capability_match"],
                    "operation_score": candidate["operation_score"],
                    "api_score": candidate["api_score"],
                }
            )
    for entry in per_component.values():
        entry["tasks"].sort(key=lambda item: item["api_score"], reverse=True)

    no_candidate = [
        row["task_id"]
        for row in rows
        if not any(c["tier"] == "primary" for c in row["candidates"])
    ]
    no_task = [
        bundle_id
        for bundle_id, entry in per_component.items()
        if not entry["tasks"]
    ]
    multi_task = [
        bundle_id
        for bundle_id, entry in per_component.items()
        if len(entry["tasks"]) >= 2
    ]
    multi_component = [
        row["task_id"]
        for row in rows
        if sum(1 for c in row["candidates"] if c["tier"] == "primary") >= 2
    ]
    return {
        "schema": "component-task-matrix-v1",
        "component_count": len(components),
        "task_count": len(tasks),
        "rows": rows,
        "per_component": per_component,
        "coverage": {
            "tasks_without_candidate": no_candidate,
            "components_without_task": no_task,
            "components_serving_multiple_tasks": multi_task,
            "tasks_with_multiple_components": multi_component,
        },
    }


def render_markdown(matrix: dict[str, Any], library_manifest: Path) -> str:
    lines = [
        "# Component x task capability matrix",
        "",
        f"- library manifest: `{library_manifest}`",
        f"- components: {matrix['component_count']}",
        f"- task packages scanned: {matrix['task_count']}",
        "",
        "`primary` means the task title or source file names name an operation in",
        "the component's capability family (file / process / thread / build).",
        "`secondary` candidates are shown as review material only: they are",
        "ranked by operation-term overlap and IDF-weighted API tokens found in",
        "the task's source-side `work/` tree, and do not count as coverage.",
        "",
        "## Per task",
        "",
    ]
    for row in matrix["rows"]:
        kind = "planned" if row.get("planned") else f"{row['work_files']} source files"
        lines.append(f"### `{row['task_id']}` ({row['domain'] or 'no domain'}, {kind})")
        if not row["has_work"] and not row.get("planned"):
            lines.extend(["", "_No materialized `work/`; the matrix cannot inspect this package._", ""])
            continue
        if not row["candidates"]:
            lines.extend(["", "_No candidate component._", ""])
            continue
        if not any(c["tier"] == "primary" for c in row["candidates"]):
            lines.extend(["", "_No primary candidate; secondary matches listed for review._", ""])
        if not row["has_work"]:
            lines.extend(["", "_Planned package: scored from title, notes and source file names only._", ""])
        lines.extend(
            [
                "",
                "| component | capability | tier | ops | api | evidence |",
                "|---|---|:--:|---:|---:|---|",
            ]
        )
        for candidate in row["candidates"][:5]:
            api_evidence = ", ".join(
                f"`{hit['token']}`x{hit['count']}" for hit in candidate["api_hits"][:3]
            )
            op_evidence = ", ".join(
                f"`{term}`" for term in candidate["operation_terms"][:6]
            )
            evidence = "; ".join(part for part in (op_evidence, api_evidence) if part)
            lines.append(
                f"| `{candidate['bundle_id']}` | {candidate['capability']} | "
                f"{candidate['tier']} | "
                f"{candidate['operation_score']:.1f} | {candidate['api_score']:.2f} | {evidence or '-'} |"
            )
        lines.append("")
    lines.extend(["## Per component", "", "| component | capability | tasks |", "|---|---|---|"])
    for bundle_id, entry in matrix["per_component"].items():
        tasks = ", ".join(
            f"`{item['task_id']}`" for item in entry["tasks"][:8]
        ) or "-"
        lines.append(f"| `{bundle_id}` | {entry['capability']} | {tasks} |")
    coverage = matrix["coverage"]
    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"- components serving >=2 tasks: {len(coverage['components_serving_multiple_tasks'])} "
            + (", ".join(f"`{x}`" for x in coverage["components_serving_multiple_tasks"]) or ""),
            f"- tasks with >=2 components: {len(coverage['tasks_with_multiple_components'])} "
            + (", ".join(f"`{x}`" for x in coverage["tasks_with_multiple_components"]) or ""),
            f"- tasks with no candidate: " + (", ".join(f"`{x}`" for x in coverage["tasks_without_candidate"]) or "none"),
            f"- components with no task: " + (", ".join(f"`{x}`" for x in coverage["components_without_task"]) or "none"),
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-manifest", required=True)
    parser.add_argument("--tasks-root", required=True)
    parser.add_argument("--slate", default=None, help="include slate entries without a package")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)

    library_manifest = Path(args.library_manifest).resolve()
    tasks_root = Path(args.tasks_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    components = load_components(library_manifest)
    tasks = load_tasks(tasks_root)
    if args.slate:
        known = {task["task_id"] for task in tasks}
        planned = load_planned(Path(args.slate).resolve(), known)
        tasks.extend(planned)
    matrix = build_matrix(components, tasks)
    (output_dir / "matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "matrix.md").write_text(
        render_markdown(matrix, library_manifest), encoding="utf-8"
    )
    summary = {
        "status": "ok",
        "components": matrix["component_count"],
        "tasks": matrix["task_count"],
        "output": str(output_dir),
        **matrix["coverage"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())