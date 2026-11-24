#!/usr/bin/env python3
"""Agent-visible workspace view.

The evaluator needs the full upstream repository and hidden tests; the agent
must not get them.  This module removes evaluator/test material while copying
a task ``work/`` tree into an attempt workspace, and supplies the mirrored
overlay used by the judge to put the agent's source changes back into the full
pristine tree.
"""
from __future__ import annotations

import fnmatch
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
# A file name marks a test when "test"/"tests" is a whole word (``test-list.h``,
# ``runLibTests.sh``), a CamelCase suffix before the extension (``FileTest.cpp``,
# ``PathTest.h``), or a CamelCase prefix (``TestCase.cpp``).  A plain substring
# is not enough: it also hides library sources such as ``RotateStrategy.cpp``,
# ``CreateStatement.cpp`` and ``TextTestResult.cpp``.
KYLIN_TEST_NAME_RE = re.compile(
    r"(?i)(?:"
    r"(?:^|[_\-. ])tests?(?:[_\-. ]|$)"
    r"|tests?\.(?:c|cc|cpp|cxx|h|hh|hpp|hxx|sh|bash|py|bat|cmd|ps1|txt|in|am|ac)$"
    r"|^tests?[A-Z_.]"
    r")"
)


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


KYLIN_CMAKE_TEST_RE = re.compile(
    r"(?i)(?:\btest/|\btests/|\btestsuite/|\btestdata/|nginx-tests|\buv_test_|"
    r"\badd_test\s*\(|test-list|\benable_testing\s*\(|\bBUILD_TESTING\b|"
    r"\bBUILD_TESTS\b|\bENABLE_TESTS?\b|LIBUV_BUILD_TESTS|LIBUV_BUILD_BENCH|"
    r"\btests?\b|BENCH)"
)


def _cmake_depth(line: str, quoted: bool = False) -> tuple[int, bool]:
    """Paren depth of one CMake line, ignoring comments and quoted strings.

    ``quoted`` is carried in and out because a CMake quoted argument may span
    several lines (``check_c_source_compiles("...")``).  Resetting it per line
    makes the closing quote look like an opening one, so the call's final ``)``
    is mistaken for quoted text and the statement never ends.
    """
    depth = 0
    escaped = False
    for ch in line:
        if escaped:
            # ``\"`` and ``\#`` are literals in unquoted arguments too.
            escaped = False
        elif ch == "\\":
            escaped = True
        elif quoted:
            if ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == "#":
            break
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
    return depth, quoted


def _cmake_statements(lines: List[str]) -> List[List[str]]:
    """Group physical lines into statements by their open parentheses.

    A CMake command may continue over several lines (``option(X`` then its
    description) and a quoted argument may span lines.  Consecutive comment
    lines form one block, so a block that mentions tests disappears whole
    instead of leaving a dangling continuation.  ``_sanitize_kylin_cmake``
    must drop or keep a whole statement: dropping only one continuation line
    leaves the file unparsable, which hands the agent a broken build before it
    starts.
    """
    out: List[List[str]] = []
    buf: List[str] = []
    depth = 0
    quoted = False
    last_comment = False
    for line in lines:
        stripped = line.strip()
        if quoted:
            # Inside a multi-line quoted argument: text is opaque.
            buf.append(line)
            step, quoted = _cmake_depth(line, quoted)
            depth += step
            if depth <= 0:
                out.append(buf)
                buf = []
                depth = 0
            last_comment = False
            continue
        if buf:
            # Inside an open command; a comment line is part of it.
            buf.append(line)
            if stripped.startswith("#"):
                continue
        elif stripped.startswith("#"):
            if last_comment:
                out[-1].append(line)
            else:
                out.append([line])
            last_comment = True
            continue
        elif not stripped:
            out.append([line])
            last_comment = False
            continue
        else:
            buf.append(line)
        step, quoted = _cmake_depth(line, quoted)
        depth += step
        if depth <= 0:
            out.append(buf)
            buf = []
            depth = 0
        last_comment = False
    if buf:
        out.append(buf)
    return out


def _sanitize_kylin_cmake(text: str) -> str:
    """Drop test/benchmark targets and test source lists from CMake.

    Kylin repositories often keep their full test suite in the same CMake
    file as the library.  The agent view removes the test directories; this
    removes the corresponding build declarations so the file tree does not
    reveal test names or paths.  Statements are matched whole, so a
    multi-line option or command disappears entirely instead of leaving its
    opening line behind.
    """
    out: List[str] = []
    skip_depth = 0
    for statement in _cmake_statements(text.splitlines()):
        first = statement[0].strip()
        if skip_depth:
            for line in statement:
                stripped = line.strip()
                if re.match(r"^if\s*\(", stripped, re.I):
                    skip_depth += 1
                elif re.match(r"^endif\s*\(", stripped, re.I):
                    skip_depth -= 1
            continue
        if re.match(r"^if\s*\(", first, re.I) and re.search(
            r"(?i)(?:TEST|BENCH)", first
        ):
            skip_depth = 1
            continue
        if any(KYLIN_CMAKE_TEST_RE.search(line) for line in statement):
            continue
        out.extend(statement)
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
        # curl build-migration tasks (l3_curl_build, v2_curl_build) own their
        # build files; those files are part of the submitted change.
        return not str(task.get("task_id") or "").endswith("curl_build")
    return False


def task_scenario(task: Dict[str, Any]) -> str:
    return str(task.get("scenario") or "")


def removed_patterns(task: Dict[str, Any]) -> List[str]:
    """Return ``prepare.remove`` / ``prepare.remove_globs`` as normalized globs."""
    prepare = task.get("prepare") or {}
    out: List[str] = []
    for key in ("remove", "remove_globs"):
        value = prepare.get(key) or []
        if isinstance(value, str):
            value = [value]
        for item in value:
            rel = str(item).replace("\\", "/")
            while rel.startswith("./"):
                rel = rel[2:]
            rel = rel.lstrip("/")
            if rel:
                out.append(rel)
    return out


def is_removed_path(task: Dict[str, Any], rel: str) -> bool:
    """True when ``rel`` is an implementation the task author removed.

    These paths are the answer, not hidden test material: the agent may create
    them, so ``copy_overlay`` must keep accepting them.  They are filtered only
    when building the agent view and when the judge tree is prepared.
    """
    rel = rel.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    rel = rel.lstrip("/")
    for pattern in removed_patterns(task):
        if any(ch in pattern for ch in "*?["):
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, pattern.rstrip("/") + "/*"):
                return True
        elif rel == pattern or rel.startswith(pattern.rstrip("/") + "/"):
            return True
    return False


def strip_removed_paths(root: Path, task: Dict[str, Any]) -> List[str]:
    """Delete removed implementation paths from a tree in place.

    ``prepare.sh`` already removes them; this is the defence for a stale or
    hand-made ``work/`` that still contains the answer.
    """
    root = Path(root)
    deleted: List[str] = []
    for rel in _walk(root):
        if not is_removed_path(task, rel):
            continue
        path = root / rel
        if path.is_symlink() or path.is_file():
            path.unlink()
            deleted.append(rel)
    return deleted


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
        if len(parts) == 1 and parts[-1] == "README":
            # POCO's CPack include names the repository README as its package
            # description file; without it ``cmake`` cannot configure at all.
            return False
        if any(part in KYLIN_TEST_DIRS or "test" in part.lower() for part in parts[:-1]):
            return True
        if any(part in KYLIN_DOC_DIRS or part in KYLIN_METADATA_DIRS for part in parts[:-1]):
            return True
        if parts[-1] in KYLIN_DOC_FILES or parts[-1].upper().startswith("README"):
            return True
        if "test" in parts[-1].lower() or "benchmark" in parts[-1].lower():
            # ``cmake/`` holds build support (e.g. ``test_compiler.cpp`` used
            # by try_compile), never task test material.  Match the directory
            # case-insensitively: curl keeps it as ``CMake/`` and its
            # ``CurlTests.c`` is a try_compile probe the build needs.
            if parts[0].lower() != "cmake" and (
                KYLIN_TEST_NAME_RE.search(parts[-1])
                or "benchmark" in parts[-1].lower()
            ):
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


def walk_files(source: Path) -> List[str]:
    """Return every file (not directory) under ``source`` as a posix path."""
    return _walk(Path(source))


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
        if is_hidden_path(task, rel) or is_removed_path(task, rel):
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
