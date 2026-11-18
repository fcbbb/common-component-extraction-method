#!/usr/bin/env python3
"""Bring the vendored IPP -> VSIPL tasks onto the shared task-package schema.

The 19 packages under ``ipp_vsipl_tasks/`` predate the unified schema: they
have no ``scenario``/``provenance.json``/``prepare.sh`` and their commands use
literal paths.  This tool rewrites them in place while preserving every
hand-written comment and note:

* add ``scenario: ipp_to_vsipl``, ``source_kind``, ``gold_kind``;
* add ``source.license`` and ``source.vendored``;
* point ``build``/``public_tests``/``hidden_tests``/API gate at the shared
  ``{root}/{work}/{build}/{golden}`` placeholders;
* write ``provenance.json`` and a vendored ``prepare.sh``;
* install the shared ``harness/run_hidden.py`` and the ``BUILD_HIDDEN_TESTS``
  CMake option used by the evaluator-only hidden test target.

The source snapshots are vendored, so ``prepare.sh`` never touches the network:
it copies the package's own ``src/``, ``include/``, ``test/`` and
``CMakeLists.txt`` into ``work/``.

Usage::

    python3 tools/unify_ipp_tasks.py [--root ipp_vsipl_tasks]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "ipp_vsipl_tasks"

# id -> (license, canonical upstream URL or None for synthetic snapshots)
META: Dict[str, Tuple[str, Optional[str]]] = {
    "l1_aubio_dct": ("GPL-3.0-or-later", "https://github.com/aubio/aubio.git"),
    "l1_conv_corr": ("synthetic", None),
    "l1_juce_fft": ("AGPL-3.0-only", "https://github.com/juce-framework/JUCE.git"),
    "l1_steamaudio_fft": (
        "Apache-2.0",
        "https://github.com/valveSoftware/steam-audio.git",
    ),
    "l1_vec_db_mag": ("synthetic", None),
    "l1_window_gen": ("synthetic", None),
    "l2_aubio_fft": ("GPL-3.0-or-later", "https://github.com/aubio/aubio.git"),
    "l2_cfar_detector": ("synthetic", None),
    "l2_cil_fbp": ("Apache-2.0", "https://github.com/TomographicImaging/CIL.git"),
    "l2_dot_norm_stats": ("synthetic", None),
    "l2_fdfir_overlap_save": ("synthetic", None),
    "l2_r8brain_fft": (
        "MIT",
        "https://github.com/avaneev/r8brain-free-src.git",
    ),
    "l2_rubberband_fft": (
        "GPL-2.0-or-later",
        "https://github.com/breakfastquay/rubberband.git",
    ),
    "l2_saf_stft": (
        "MIT",
        "https://github.com/leomccormack/Spatial_Audio_Framework.git",
    ),
    "l2_tdfir_bank": ("synthetic", None),
    "l3_audio_resampler": ("synthetic", None),
    "l3_comms_demod_frontend": ("synthetic", None),
    "l3_iir_eq_negative": ("synthetic", None),
    "l3_spectrum_sensing": ("synthetic", None),
}

TOP_KEY = re.compile(r"^([A-Za-z_][\w]*):")


def _section_of(lines: List[str]) -> List[str]:
    """Return the top-level section name for every line."""
    sections: List[str] = []
    current = ""
    for line in lines:
        match = TOP_KEY.match(line)
        if match:
            current = match.group(1)
        sections.append(current)
    return sections


def _replace_value(line: str, value: str) -> str:
    """Replace a ``key: value  # comment`` scalar, keeping the comment."""
    match = re.match(r"^(\s*[A-Za-z_][\w]*:\s*)(.*?)(\s+#.*)?$", line)
    if not match:
        raise ValueError(f"cannot parse scalar line: {line!r}")
    prefix, _old, comment = match.groups()
    return f"{prefix}{value}{comment or ''}"


def _insert_after(lines: List[str], index: int, new_lines: List[str]) -> List[str]:
    return lines[: index + 1] + new_lines + lines[index + 1 :]


def rewrite_task_yaml(path: Path, task_id: str) -> None:
    license_name, repo_url = META[task_id]
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    if "scenario:" not in raw:
        for idx, line in enumerate(lines):
            if line.startswith("task_id:"):
                lines = _insert_after(
                    lines,
                    idx,
                    [
                        "scenario: ipp_to_vsipl",
                        "source_kind: vendored-ipp-snapshot",
                        "gold_kind: implementation",
                    ],
                )
                break

    # source: canonical URL (when real), license, vendored flag.
    sections = _section_of(lines)
    src_idx = None
    for idx, line in enumerate(lines):
        if sections[idx] == "source" and line.startswith("  repo:"):
            if repo_url:
                lines[idx] = _replace_value(line, repo_url)
        elif sections[idx] == "source" and line.startswith("  commit:"):
            src_idx = idx
    if src_idx is not None and "  license:" not in raw:
        lines = _insert_after(
            lines, src_idx, [f"  license: {license_name}", "  vendored: true"]
        )

    # prepare: vendored snapshots need no deletion from work/.
    if "prepare:" not in raw:
        for idx, line in enumerate(lines):
            if line.startswith("build:"):
                lines = _insert_after(lines, idx - 1, ["prepare:", "  mode: vendored"])
                break

    # Commands: swap literal paths for the shared placeholders.
    sections = _section_of(lines)
    artifact_name = ""
    for idx, line in enumerate(lines):
        if sections[idx] == "build" and line.startswith("  artifact:"):
            old = re.match(r"^\s*artifact:\s*[\"']?(.*?)[\"']?\s*$", line)
            if old:
                artifact_name = Path(old.group(1)).name
    if not artifact_name:
        raise ValueError(f"{task_id}: build.artifact not found")

    out: List[str] = []
    sections = _section_of(lines)
    for idx, line in enumerate(lines):
        section = sections[idx]
        if section == "build" and line.startswith("  command:"):
            out.append(
                "  command: 'cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release "
                '-DVSIPL_ROOT="${VSIPL_ROOT:-}" && cmake --build {build} -j\''
            )
        elif section == "build" and line.startswith("  artifact:"):
            out.append(f"  artifact: '{{build}}/{artifact_name}'")
        elif section == "public_tests" and line.startswith("  command:"):
            out.append("  command: 'ctest --test-dir {build} --output-on-failure'")
        elif section == "hidden_tests" and line.startswith("  command:"):
            out.append(
                "  command: 'python3 {root}/harness/run_hidden.py --task-root . "
                f"--task-id {task_id} --harness-dir {{root}}/harness "
                "--golden {golden} --build-dir {build}/hidden'"
            )
        elif section == "gates" and line.startswith("  api_removal:"):
            out.append(
                "  api_removal: 'bash {root}/harness/check_api_removal.sh "
                f"{{build}}/{artifact_name}'"
            )
            out.append(
                "  behavior: 'hidden_test exits 0 on every golden case; "
                "no IPP symbol remains in the built artifact'"
            )
        else:
            out.append(line)

    path.write_text("\n".join(out) + "\n", encoding="utf-8")


PREPARE = """#!/usr/bin/env bash
# Vendored snapshot: no network access is required or performed.
# The IPP source state is already in this package under src/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="$ROOT/work"
REPO={repo}
COMMIT={commit}

rm -rf "$WORK"
mkdir -p "$WORK"
for entry in src include test CMakeLists.txt support; do
  if [ -e "$ROOT/$entry" ]; then
    cp -a "$ROOT/$entry" "$WORK/"
  fi
done
if [ -f "$ROOT/README.md" ]; then cp "$ROOT/README.md" "$WORK/TASK.md"; fi

printf '%s\\n' "$COMMIT" > "$WORK/.source_commit"
printf 'vendored: %s @ %s\\n' "$REPO" "$COMMIT" > "$WORK/.source_origin"
echo "prepared $WORK (vendored $REPO@$COMMIT)"
"""


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def write_prepare(root: Path, task_id: str) -> None:
    task = yaml.safe_load((root / "task.yaml").read_text(encoding="utf-8"))
    src = task.get("source") or {}
    body = PREPARE.format(
        repo=shell_quote(str(src.get("repo", ""))),
        commit=shell_quote(str(src.get("commit", ""))),
    )
    path = root / "prepare.sh"
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_provenance(root: Path, task_id: str) -> None:
    task = yaml.safe_load((root / "task.yaml").read_text(encoding="utf-8"))
    src = task.get("source") or {}
    files = [str(item) for item in (src.get("files") or [])]
    gold_rel = str(task.get("gold_patch") or "")
    gold_name = Path(gold_rel).name

    harness = root / "harness"
    test_files = sorted(
        str(p.relative_to(root))
        for p in harness.rglob("*")
        if p.is_file()
        and p.suffix in {".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".sh"}
        and "golden" not in p.parts
    )
    golden = harness / "golden"
    golden_count = sum(1 for p in golden.rglob("*") if p.is_file()) if golden.is_dir() else 0

    data: Dict[str, Any] = {
        "task_id": task_id,
        "scenario": "ipp_to_vsipl",
        "repo": str(src.get("repo", "")),
        "commit": str(src.get("commit", "")),
        "license": str(src.get("license", "")),
        "vendored": True,
        "snapshot": f"ipp_vsipl_tasks/{task_id}",
        "source_files": files,
        "gold_files": [gold_rel] if gold_rel else [],
        "test_files": test_files,
        "golden_cases": golden_count,
        "remove": [],
        "gold_kind": "implementation",
        "materialized": True,
        "generated_by": "tools/unify_ipp_tasks.py",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (root / "provenance.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def patch_cmake(root: Path) -> None:
    path = root / "CMakeLists.txt"
    text = path.read_text(encoding="utf-8")
    if "BUILD_HIDDEN_TESTS" not in text:
        text = text.replace(
            'option(USE_GOLD "Build the reference VSIPL migration (evaluator only)" OFF)',
            'option(USE_GOLD "Build the reference VSIPL migration (evaluator only)" OFF)\n'
            'option(BUILD_HIDDEN_TESTS "Build the evaluator-only hidden test" OFF)',
        )
    # Wrap the hidden test target.
    text = re.sub(
        r"add_executable\(hidden_test harness/hidden_test\.(c|cpp)\)\n"
        r"target_link_libraries\(hidden_test ([^\n]+)\)\n",
        lambda m: (
            "if(BUILD_HIDDEN_TESTS)\n"
            f"    add_executable(hidden_test ${{HARNESS_DIR}}/hidden_test.{m.group(1)})\n"
            f"    target_link_libraries(hidden_test {m.group(2)})\n"
            "endif()\n"
        ),
        text,
    )
    # golden_gen is evaluator-only too; keep its USE_IPP/USE_GOLD guard.
    text = text.replace(
        "add_executable(golden_gen harness/golden_gen.",
        "add_executable(golden_gen ${HARNESS_DIR}/golden_gen.",
    )
    path.write_text(text, encoding="utf-8")


RUN_HIDDEN = '''#!/usr/bin/env python3
"""Evaluator entry point for a task package.

Steps
  1. configure + build the candidate source in a scratch build dir
  2. run harness/hidden_test against the stored golden cases
Prints one JSON object and exits non-zero if any step fails.

Usage:
  python3 harness/run_hidden.py --task-root . --golden <dir> \\
      [--harness-dir <dir>] [--build-dir <dir>]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys


def run(cmd, cwd=None, env=None):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-root", default=".")
    ap.add_argument("--task-id", default=None)
    ap.add_argument("--harness-dir", default=None)
    ap.add_argument("--golden", required=True, help="dir with case_*.bin")
    ap.add_argument("--build-dir", default=None)
    ap.add_argument("--cmake", default=os.environ.get("CMAKE", "cmake"))
    ap.add_argument("--vsip-root", default=os.environ.get("VSIPL_ROOT"))
    args = ap.parse_args()

    root = os.path.abspath(args.task_root)
    harness = os.path.abspath(args.harness_dir or os.path.join(root, "harness"))
    build = os.path.abspath(args.build_dir or os.path.join(root, "build_hidden"))
    result = {
        "task": args.task_id or os.path.basename(root.rstrip(os.sep)),
        "build": None,
        "tests": None,
    }

    if os.path.isdir(build):
        shutil.rmtree(build)
    cmd = [
        args.cmake,
        "-S",
        root,
        "-B",
        build,
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_HIDDEN_TESTS=ON",
        "-DHARNESS_DIR=" + harness,
    ]
    if args.vsip_root:
        cmd += ["-DVSIPL_ROOT=" + os.path.abspath(args.vsip_root)]
    rc, out = run(cmd)
    if rc == 0:
        rc, out = run([args.cmake, "--build", build, "--target", "hidden_test", "-j"])
    if rc != 0:
        result["build"] = "fail"
        result["log"] = out[-4000:]
        print(json.dumps(result, indent=2))
        return 1
    result["build"] = "ok"

    exe = os.path.join(build, "hidden_test")
    rc, out = run([exe, os.path.abspath(args.golden)])
    result["tests"] = "pass" if rc == 0 else "fail"
    m = re.search(r"SUMMARY cases=(\\d+) failures=(\\d+)", out)
    if m:
        result["cases"] = int(m.group(1))
        result["failures"] = int(m.group(2))
    m = re.search(r"SUMMARY[^\\n]*worst_rel=([0-9.eE+-]+)", out) or re.search(
        r"worst_rel=([0-9.eE+-]+)", out
    )
    if m:
        result["worst_rel"] = float(m.group(1))
    result["log"] = out[-4000:]
    print(json.dumps(result, indent=2))
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
'''


def install_runner(root: Path) -> None:
    path = root / "harness" / "run_hidden.py"
    path.write_text(RUN_HIDDEN, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(TASKS))
    args = ap.parse_args(argv)
    tasks_root = Path(args.root).resolve()
    if not tasks_root.is_dir():
        ap.error(f"not a directory: {tasks_root}")

    count = 0
    for root in sorted(tasks_root.iterdir()):
        if not (root / "task.yaml").is_file():
            continue
        task_id = root.name
        if task_id not in META:
            print(f"skip {task_id}: no license/repo metadata", file=sys.stderr)
            continue
        rewrite_task_yaml(root / "task.yaml", task_id)
        install_runner(root)
        patch_cmake(root)
        write_prepare(root, task_id)
        write_provenance(root, task_id)
        count += 1
        print(f"unified {task_id}")
    print(f"done: {count} task(s) under {tasks_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())