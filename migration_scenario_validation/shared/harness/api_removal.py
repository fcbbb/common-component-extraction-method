#!/usr/bin/env python3
"""Generic source/API-removal gate shared by all migration scenarios.

Examples
--------
IPP -> VSIPL::

    python3 shared/harness/api_removal.py \
        --symbol-regex '^(ipps|ippi|ippvm|ippcore)' \
        build/libconvcc.a

Windows -> Kylin::

    python3 shared/harness/api_removal.py \
        --source-dir work --source-regex 'windows\\.h|__declspec|_MSC_VER|CreateFile|WSAStartup' \
        --symbol-regex '^(__imp_|CreateFile|WaitForSingleObject|WSAStartup)'

CUDA -> Ascend::

    python3 shared/harness/api_removal.py \
        --source-dir work --source-regex 'cuda|__global__|cudaMalloc|nvcc' \
        --symbol-regex '^(cuda|cu|nv)'
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "build",
    "build_hidden",
    "work/.cache",
    "gold",
    "harness/golden",
    "node_modules",
}

SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".py",
    ".sh",
    ".cmake",
    ".txt",
    ".yaml",
    ".yml",
}


C_LIKE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".m",
    ".mm",
}


def strip_c_comments(text: str) -> str:
    """Blank out C/C++ comments while preserving line numbering.

    The source scan is a *code* gate: a comment that explains which Win32
    call a POSIX function replaces ("matching GetFileSize behaviour") is
    documentation, not a use of the removed API.  Flagging it makes a
    correct port fail for a sentence, so comment bodies are replaced with
    spaces (newlines are kept so reported line numbers still match the
    file).  String and character literals are left intact.
    """
    out: List[str] = []
    i, n = 0, len(text)
    state = "code"
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line"
                out.append("  ")
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block"
                out.append("  ")
                i += 2
                continue
            if ch == '"':
                state = "string"
            elif ch == "'":
                state = "char"
            out.append(ch)
            i += 1
            continue
        if state == "line":
            out.append("\n" if ch == "\n" else " ")
            if ch == "\n":
                state = "code"
            i += 1
            continue
        if state == "block":
            if ch == "*" and nxt == "/":
                state = "code"
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        # Inside a string or character literal: copy verbatim, honouring
        # backslash escapes, and return to code at the closing quote.
        out.append(ch)
        if ch == "\\" and i + 1 < n:
            out.append(text[i + 1])
            i += 2
            continue
        if state == "string" and ch == '"':
            state = "code"
        elif state == "char" and ch == "'":
            state = "code"
        i += 1
    return "".join(out)


def _nm(path: Path) -> List[str]:
    """Return symbols from a binary/archive.  Empty on missing tool."""
    symbols: List[str] = []
    commands = [
        ["nm", "-g", "--defined-only", str(path)],
        ["nm", "-u", str(path)],
    ]
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in (proc.stdout or "").splitlines():
            parts = line.split()
            if parts:
                symbols.append(parts[-1])
    if not symbols:
        try:
            proc = subprocess.run(
                ["objdump", "-t", str(path)], capture_output=True, text=True, timeout=120
            )
            for line in (proc.stdout or "").splitlines():
                parts = line.split()
                if parts:
                    symbols.append(parts[-1])
        except (OSError, subprocess.TimeoutExpired):
            pass
    return sorted(set(symbols))


def _iter_source_files(
    root: Path, exclude_dirs: Iterable[str], exclude_globs: Iterable[str] = ()
) -> Iterable[Path]:
    root = Path(root).resolve()
    excluded = set()
    for item in exclude_dirs:
        excluded.add(str((root / item).resolve()))
    globs = [g for g in exclude_globs if g]
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath).resolve()
        dirnames[:] = [
            d
            for d in dirnames
            if str((current / d).resolve()) not in excluded
            and d not in {".git", "__pycache__", "build", "build_hidden", "node_modules"}
        ]
        for name in filenames:
            path = current / name
            if path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            rel = str(path.relative_to(root)).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(path.name, g) for g in globs):
                continue
            yield path


def scan(
    *,
    artifacts: Optional[Iterable[str]] = None,
    symbol_regex: Optional[str] = None,
    source_dirs: Optional[Iterable[str]] = None,
    source_regex: Optional[str] = None,
    exclude_dirs: Optional[Iterable[str]] = None,
    exclude_globs: Optional[Iterable[str]] = None,
    expect_fail: bool = False,
    positive: bool = False,
    max_hits: int = 200,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "status": "pass",
        "symbol_regex": symbol_regex,
        "source_regex": source_regex,
        "artifacts": [],
        "symbols": [],
        "source_hits": [],
        "exclude_globs": list(exclude_globs or []),
        "expect_fail": bool(expect_fail),
        "positive": bool(positive),
        "errors": [],
    }
    if not symbol_regex and not source_regex:
        result["status"] = "error"
        result["errors"].append("at least one of symbol_regex/source_regex is required")
        return result
    if positive and expect_fail:
        result["status"] = "error"
        result["errors"].append("positive and expect_fail are mutually exclusive")
        return result

    artifact_list = list(artifacts or [])
    if artifact_list:
        sym_re = re.compile(symbol_regex) if symbol_regex else None
        for item in artifact_list:
            path = Path(item)
            entry: Dict[str, Any] = {"path": str(path), "exists": path.exists(), "symbols": []}
            if not path.exists():
                result["errors"].append(f"missing artifact: {item}")
                entry["error"] = "missing"
                result["artifacts"].append(entry)
                continue
            if sym_re:
                hits = [s for s in _nm(path) if sym_re.search(s)]
                entry["symbols"] = hits
                if hits:
                    result["symbols"].extend(hits)
            result["artifacts"].append(entry)

    if source_dirs and source_regex:
        try:
            src_re = re.compile(source_regex)
        except re.error as exc:
            result["status"] = "error"
            result["errors"].append(f"bad source_regex: {exc}")
            return result
        excluded = list(DEFAULT_EXCLUDE_DIRS) + list(exclude_dirs or [])
        globs = exclude_globs or []

        def scan_file(path: Path) -> None:
            nonlocal result
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                result["errors"].append(f"{path}: {exc}")
                return
            if path.suffix.lower() in C_LIKE_SUFFIXES:
                text = strip_c_comments(text)
            for lineno, line in enumerate(text.splitlines(), 1):
                m = src_re.search(line)
                if m:
                    result["source_hits"].append(
                        {
                            "file": str(path),
                            "line": lineno,
                            "match": m.group(0)[:120],
                        }
                    )
                    if len(result["source_hits"]) >= max_hits:
                        return

        def resolve_source_path(raw: str) -> Optional[Path]:
            root = Path(raw).resolve()
            if root.exists():
                return root
            # Task configs spell paths as they appear in the reference tree
            # (``CMake``).  An agent-authored build system may place the same
            # modules in ``cmake/``; the target filesystem is case sensitive,
            # so resolve the declared path case-insensitively before treating
            # it as absent.
            try:
                siblings = list(root.parent.iterdir())
            except OSError:
                return None
            for entry in siblings:
                if entry.name.lower() == root.name.lower():
                    return entry
            return None

        found_sources = 0
        missing_sources: List[str] = []
        for raw_dir in source_dirs:
            root = resolve_source_path(raw_dir)
            if root is None:
                missing_sources.append(raw_dir)
                continue
            found_sources += 1
            if root.is_file():
                if root.suffix.lower() not in SOURCE_SUFFIXES:
                    result["errors"].append(f"not a scanned source file: {raw_dir}")
                    continue
                if any(fnmatch.fnmatch(root.name, g) for g in globs):
                    continue
                scan_file(root)
                if len(result["source_hits"]) >= max_hits:
                    break
                continue
            for path in _iter_source_files(root, excluded, globs):
                scan_file(path)
                if len(result["source_hits"]) >= max_hits:
                    break
            if len(result["source_hits"]) >= max_hits:
                break
        if missing_sources:
            result["missing_source_dirs"] = missing_sources
            # A declared path that the agent did not create is not by itself
            # a gate failure: the build system may legitimately keep the same
            # content in fewer files.  The gate can only fail when there is
            # nothing left to scan.
            if found_sources == 0:
                result["errors"].append(
                    "none of the declared source paths exist: "
                    + ", ".join(missing_sources)
                )

    hits = bool(result["symbols"] or result["source_hits"])
    if positive:
        # Positive target-API gate: the migration must actually use the
        # requested target library/API, not merely remove the source API.
        if hits:
            result["status"] = "pass"
        else:
            result["status"] = "fail"
            result["errors"].append("required target API was not found")
    elif expect_fail:
        # Negative control: the platform API is expected to remain, because
        # there is no behaviour-preserving equivalent on the target OS.
        if hits:
            result["status"] = "pass"
        else:
            result["status"] = "fail"
            result["errors"].append(
                "negative control did not hold: no removed-API hit was found"
            )
    elif hits:
        result["status"] = "fail"
    if result["errors"] and result["status"] == "pass":
        result["status"] = "error"
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="*", help="binaries/archives to scan")
    parser.add_argument("--artifact", action="append", default=[], help="additional artifact")
    parser.add_argument("--symbol-regex", default=None)
    parser.add_argument("--source-dir", action="append", default=[])
    parser.add_argument("--source-regex", default=None)
    parser.add_argument("--exclude-dir", action="append", default=[])
    parser.add_argument(
        "--exclude-glob",
        action="append",
        default=[],
        help="fnmatch pattern (relative path or basename) to skip, e.g. '*_WIN32.cpp'",
    )
    parser.add_argument(
        "--expect-fail",
        action="store_true",
        help="negative control: pass only when removed-API hits are present",
    )
    parser.add_argument(
        "--positive",
        action="store_true",
        help="positive target gate: pass only when target-API hits are present",
    )
    parser.add_argument("--max-hits", type=int, default=200)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = scan(
        artifacts=args.artifacts + args.artifact,
        symbol_regex=args.symbol_regex,
        source_dirs=args.source_dir,
        source_regex=args.source_regex,
        exclude_dirs=args.exclude_dir,
        exclude_globs=args.exclude_glob,
        expect_fail=args.expect_fail,
        positive=args.positive,
        max_hits=args.max_hits,
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"API_REMOVAL={result['status'].upper()}")
        for entry in result["artifacts"]:
            print(f"  artifact {entry['path']}: {len(entry.get('symbols', []))} symbol(s)")
        for hit in result["source_hits"][:20]:
            print(f"  {hit['file']}:{hit['line']}: {hit['match']}")
        for err in result["errors"]:
            print(f"  ERROR {err}", file=sys.stderr)

    if result["status"] == "pass":
        return 0
    if result["status"] == "fail":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())