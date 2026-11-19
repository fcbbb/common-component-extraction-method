#!/usr/bin/env python3
"""Agent-visible workspace view.

The evaluator needs the full upstream repository and hidden tests; the agent
must not get them.  This module removes evaluator/test material while copying
a task ``work/`` tree into an attempt workspace, and supplies the mirrored
overlay used by the judge to put the agent's source changes back into the full
pristine tree.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

KYLIN_TEST_DIRS = {"test", "tests", "testsuite", "testdata", "nginx-tests", "benchmark", "benchmarks"}
KYLIN_AUTOTOOLS = {"Makefile.am", "Makefile.in", "configure.ac", "aclocal.m4", "configure"}
KYLIN_DOC_DIRS = {".github", "docs", "doc", "documentation"}
KYLIN_METADATA_DIRS = {".vscode", ".vs", ".idea", "__pycache__"}
KYLIN_METADATA_SUFFIXES = {
    ".sln", ".vcproj", ".vcxproj", ".filters", ".user", ".suo", ".ncb",
    ".aps", ".progen", ".ps1", ".cmd", ".bat", ".bash",
}
KYLIN_DOC_FILES = {
    "README", "README.md", "README.txt", "CHANGELOG", "CHANGELOG.md", "ChangeLog",
    "CONTRIBUTING", "CONTRIBUTING.md", "SECURITY", "SECURITY.md",
    "CODE_OF_CONDUCT.md", ".gitignore", ".mailmap", ".readthedocs.yaml",
    ".travis.yml", ".gitattributes",
}
KYLIN_BUILD_FILES = {"CMakeLists.txt", "Makefile.am", "Makefile.in", "configure.ac", "aclocal.m4", "configure", "meson.build", "Makefile"}
MUSA_IGNORED_DIRS = {"test", "tests", "utils"}
MUSA_IGNORED_FILES = {"eval_single_runner.py"}
GENERAL_IGNORED_FILES = {"TASK.md"}


def _sanitize_ipp_cmake(text: str) -> str:
    """Remove evaluator-only targets from the agent-facing CMake.

    The pristine ``work/CMakeLists.txt`` is used by the judge to build
    ``hidden_test`` and ``golden_gen``.  The agent must still be able to build
    the migrated source and the public test, but must not see the harness
    directory, hidden target, or golden target.
    """
    # USE_GOLD selects the evaluator reference; keep the normal source branch.
    text = re.sub(
        r"(?ms)^if\(USE_GOLD\)\n.*?^else\(\)\n(.*?)^endif\(\)\n",
        r"\1",
        text,
    )
    # Evaluator-only if-blocks, in dependency order.  The exact if(USE_IPP)
    # pattern does not match if(USE_IPP OR USE_GOLD).
    for header in (
        r"if\(USE_IPP\)",
        r"if\(BUILD_HIDDEN_TESTS\)",
        r"if\(USE_IPP OR USE_GOLD\)",
    ):
        text = re.sub(
            rf"(?ms)^{header}\n.*?^endif\(\)\n?",
            "",
            text,
        )
    # Evaluator variables and options.
    text = re.sub(
        r"(?m)^(?:set\(HARNESS_DIR|set\(IPP_ROOT|option\(USE_IPP|option\(USE_GOLD|option\(BUILD_HIDDEN_TESTS)[^\n]*\n",
        "",
        text,
    )
    # Comments that describe evaluator/golden/hidden material.
    text = "\n".join(
        line
        for line in text.splitlines()
        if not (line.lstrip().startswith("#") and re.search(
            r"(?i)evaluator|golden|hidden|HARNESS|USE_GOLD|USE_IPP", line
        ))
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _sanitize_kylin_cmake(text: str) -> str:
    """Drop test/benchmark targets and test source lists from CMake.

    Kylin repositories often keep their full test suite in the same CMake
    file as the library.  The agent view removes the test directories; this
    removes the corresponding build declarations so the file tree does not
    reveal test names or paths.
    """
    out: List[str] = []
    skip_depth = 0
    continuation_depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        if continuation_depth:
            continuation_depth += line.count("(") - line.count(")")
            continue
        if skip_depth:
            if re.match(r"^if\s*\(", stripped, re.I):
                skip_depth += 1
            elif re.match(r"^endif\s*\(", stripped, re.I):
                skip_depth -= 1
            continue
        if re.match(r"^if\s*\(", stripped, re.I) and re.search(
            r"(?i)(?:TEST|BENCH)", stripped
        ):
            skip_depth = 1
            continue
        if re.search(
            r"(?i)(?:\btest/|\btests/|\btestsuite/|\btestdata/|nginx-tests|\buv_test_|\badd_test\s*\(|test-list|\benable_testing\s*\(|BUILD_TESTING|BUILD_TESTS|ENABLE_TESTS?\b|LIBUV_BUILD_TESTS|LIBUV_BUILD_BENCH|TESTS?\b|BENCH)",
            line,
        ):
            depth = line.count("(") - line.count(")")
            if depth > 0:
                continuation_depth = depth
            continue
        out.append(line)
    return "\n".join(out).strip() + "\n"


def _sanitize_kylin_build_file(rel: str, text: str) -> str:
    name = Path(rel).name
    if name == "CMakeLists.txt":
        return _sanitize_kylin_cmake(text)
    # Autotools files are not used by CMake-based Kylin builds; for the
    # non-CMake builds, remove only test-path declarations.
    lines = []
    for line in text.splitlines():
        if re.search(r"(?i)(?:\btest/|\btests/|\btestsuite/|\btestdata/|nginx-tests)", line):
            continue
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def sanitize_agent_file(rel: str, text: str, task: Dict[str, Any]) -> str:
    """Return the agent-visible form of a text file.

    Currently only IPP CMakeLists needs rewriting.  Keeping the function
    path-aware makes it easy to add scenario-specific build-file filters.
    """
    if task_scenario(task) == "ipp_to_vsipl" and Path(rel).name == "CMakeLists.txt":
        return _sanitize_ipp_cmake(text)
    if task_scenario(task) == "windows_to_kylin" and Path(rel).name in KYLIN_BUILD_FILES:
        return _sanitize_kylin_build_file(rel, text)
    return text


def is_judge_protected(task: Dict[str, Any], rel: str) -> bool:
    """Files the judge must take from the pristine tree, not the agent copy.

    IPP build definitions contain evaluator targets.  The agent gets a
    sanitized CMakeLists, so overlaying that file would remove hidden tests
    from the judge build.
    """
    rel = rel.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    rel = rel.lstrip("/")
    if task_scenario(task) == "ipp_to_vsipl" and Path(rel).name == "CMakeLists.txt":
        return True
    if task_scenario(task) == "windows_to_kylin" and Path(rel).name in KYLIN_BUILD_FILES:
        # l3_curl_build is explicitly a build-migration task; its build files
        # are part of the submitted change.
        return str(task.get("task_id") or "") != "l3_curl_build"
    return False


def task_scenario(task: Dict[str, Any]) -> str:
    return str(task.get("scenario") or "")


def is_hidden_path(task: Dict[str, Any], rel: str) -> bool:
    """Return True when a relative path is evaluator/test-only.

    IPP's hidden harness is outside ``work/`` already (``task/harness``), so
    only public tests remain visible.  Kylin's upstream tests live inside the
    repository; MUSA's evaluator and utilities do too.
    """
    rel = rel.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    rel = rel.lstrip("/")
    parts = rel.split("/")
    scenario = task_scenario(task)
    if not rel:
        return False
    if parts[-1] in GENERAL_IGNORED_FILES:
        return True
    if scenario == "windows_to_kylin":
        if parts[-1] == "cppignore.lnx":
            return True
        if any(part in KYLIN_TEST_DIRS or "test" in part.lower() for part in parts[:-1]):
            return True
        if any(part in KYLIN_DOC_DIRS or part in KYLIN_METADATA_DIRS for part in parts[:-1]):
            return True
        if parts[-1] in KYLIN_DOC_FILES or parts[-1].upper().startswith("README"):
            return True
        if "test" in parts[-1].lower() or "benchmark" in parts[-1].lower():
            return True
        if Path(parts[-1]).suffix.lower() in KYLIN_METADATA_SUFFIXES:
            return True
        build_cmd = str((task.get("build") or {}).get("command") or "")
        if "cmake" in build_cmd.lower() and parts[-1] in (KYLIN_AUTOTOOLS | {"Makefile", "makefile"}):
            # CMake builds do not need the parallel autotools/Make files;
            # keeping them only exposes test/benchmark declarations.
            return True
        return False
    if scenario == "cuda_to_musa":
        if parts[0] in MUSA_IGNORED_DIRS:
            return True
        if rel in MUSA_IGNORED_FILES:
            return True
        return any(part in {"tests"} for part in parts[:-1])
    return False


def _walk(source: Path) -> List[str]:
    out: List[str] = []
    for current, dirs, names in os.walk(source):
        dirs.sort()
        base = Path(current)
        for name in sorted(names):
            path = base / name
            if path.is_symlink() or path.is_file():
                out.append(path.relative_to(source).as_posix())
    return out


def copy_agent_view(
    source: Path,
    destination: Path,
    task: Dict[str, Any],
    *,
    image: Optional[str] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Copy ``source`` to ``destination`` without test/evaluator material.

    ``image`` is accepted for callers that also chown the result; it is not
    used for copying.  The source is never modified.
    """
    source = Path(source)
    destination = Path(destination)
    if destination.exists():
        if not overwrite:
            shutil.rmtree(destination)
        else:
            shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    omitted: List[str] = []
    for rel in _walk(source):
        if is_hidden_path(task, rel):
            omitted.append(rel)
            continue
        src = source / rel
        dst = destination / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            dst.symlink_to(os.readlink(src))
        elif Path(rel).name == "CMakeLists.txt" or src.suffix.lower() in {".txt", ".cmake"}:
            dst.write_text(sanitize_agent_file(rel, src.read_text(encoding="utf-8", errors="replace"), task), encoding="utf-8")
            shutil.copystat(src, dst)
        else:
            shutil.copy2(src, dst)
    return {"omitted": omitted, "files": len(_walk(destination))}


def copy_overlay(
    source: Path,
    destination: Path,
    task: Dict[str, Any],
    *,
    delete_missing: bool = False,
) -> Dict[str, Any]:
    """Overlay only agent files that are safe to bring into the judge tree.

    Hidden-test directories are skipped even if an agent creates new files with
    those names.  The full immutable copy remains in ``destination``.
    """
    source = Path(source)
    destination = Path(destination)
    copied: List[str] = []
    omitted: List[str] = []
    source_files = set(_walk(source))
    for rel in _walk(source):
        if is_hidden_path(task, rel) or is_judge_protected(task, rel):
            omitted.append(rel)
            continue
        src = source / rel
        dst = destination / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() or dst.is_symlink():
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        if src.is_symlink():
            dst.symlink_to(os.readlink(src))
        else:
            shutil.copy2(src, dst)
        copied.append(rel)
    deleted: List[str] = []
    if delete_missing:
        for rel in _walk(destination):
            if rel in source_files or is_hidden_path(task, rel) or is_judge_protected(task, rel):
                continue
            # A filtered agent view intentionally has no hidden-test files, so
            # only non-hidden source/build files are candidates for deletion.
            target = destination / rel
            if target.is_symlink() or target.is_file():
                target.unlink()
                deleted.append(rel)
    return {"copied": copied, "omitted": omitted, "deleted": deleted}
