#!/usr/bin/env python3
"""Static preflight for migration task packages.

Catches the classes of defects that otherwise only surface after a 30-60
minute agent run:

* hidden/regression commands use a program that is missing from the target
  image (``cmp`` in the Kylin image, for example);
* a binary needs a shared library that is not on the loader path;
* fixed test ports collide between tasks that the batch may run at the same
  time;
* the gold answer itself trips the ``api_removal`` gate, which means the
  prompt and the gate describe different deliverables.

The checks are static and take seconds.  ``bench_batch.py`` runs this before
starting any job and skips tasks that fail.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.harness import api_removal, taskmodel  # noqa: E402

DEFAULT_IMAGE = "migration/kylin:sp3-p2"
# Programs whose absence is worth checking; extracted from commands and
# harness scripts.  Shell builtins are filtered out.
BUILTINS = {
    "cd", "test", "[", "[[", "if", "then", "else", "fi", "for", "while", "do",
    "done", "case", "esac", "export", "local", "readonly", "set", "unset",
    "return", "exit", "shift", "true", "false", "source", ".", "eval", "exec",
    "printf", "echo", "wait", "trap", "{", "}", "!", "not", "no", "posix",
}


def _segments(command: str) -> Iterable[str]:
    """Split a shell string on ``; && || |`` but never inside quotes.

    Naive splitting rips apart quoted regexes (``grep -E 'a|b'``) and makes
    the scanner report words from the pattern as missing programs.
    """
    segs: List[str] = []
    buf: List[str] = []
    quote: Optional[str] = None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch in ";|":
            segs.append("".join(buf))
            buf = []
            if i + 1 < len(command) and command[i + 1] in "&|":
                i += 2
            else:
                i += 1
            continue
        if ch == "&" and i + 1 < len(command) and command[i + 1] == "&":
            segs.append("".join(buf))
            buf = []
            i += 2
            continue
        buf.append(ch)
        i += 1
    segs.append("".join(buf))
    for seg in segs:
        seg = seg.strip()
        if seg:
            yield seg


def _first_word(seg: str) -> str:
    while True:
        m = re.match(r"^[A-Za-z_][A-Za-z0-9_]*=\S*\s+", seg)
        if not m:
            break
        seg = seg[m.end():]
    words = seg.split()
    return words[0] if words else ""


def _plausible_program(word: str) -> bool:
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9_.+-]*$", word))


def _command_programs(command: str) -> List[str]:
    progs = []
    for seg in _segments(command):
        word = _first_word(seg)
        if not word:
            continue
        word = word.strip("'\"")
        if word.startswith(".") or word.startswith("/") or "{" in word:
            continue
        if _plausible_program(word):
            progs.append(word)
    return progs


def _script_programs(path: Path) -> List[str]:
    """Approximate the programs a shell script invokes."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    defined = set(re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\(\)", text))
    progs = []
    heredoc: Optional[str] = None
    for line in text.splitlines():
        stripped = line.strip()
        if heredoc is not None:
            if stripped == heredoc:
                heredoc = None
            continue
        line = stripped
        if not line or line.startswith("#"):
            continue
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if m:
            heredoc = m.group(1)
        for seg in _segments(line):
            word = _first_word(seg)
            word = word.strip("'\"")
            if not word or word in BUILTINS:
                continue
            if word.startswith(("./", "/", "$", "-", "{")) or "=" in word:
                continue
            if "{" in word or "}" in word:
                continue
            if word in defined:
                continue
            if _plausible_program(word):
                progs.append(word)
    return progs


def _image_programs(image: str) -> Optional[set]:
    """Programs present on PATH in the target image (None if docker fails)."""
    candidates = set()
    for root in (ROOT / "v3").rglob("task.yaml"):
        try:
            task = taskmodel.load_task(root.parent)
        except Exception:  # noqa: BLE001
            continue
        for key in ("hidden_tests", "regression_tests", "public_tests"):
            cmd = (task.get(key) or {}).get("command")
            if cmd:
                candidates.update(_command_programs(cmd))
        for script in (root.parent / "harness").glob("*.sh"):
            candidates.update(_script_programs(script))
    candidates = {c for c in candidates if c not in BUILTINS}
    if not candidates:
        return set()
    script = " ".join(sorted(shlex.quote(c) for c in candidates))
    try:
        proc = subprocess.run(
            ["docker", "run", "--rm", image, "sh", "-c",
             f"for t in {script}; do command -v \"$t\" >/dev/null 2>&1 && echo \"$t\"; done; exit 0"],
            capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def _ports(task: Dict, root: Path) -> List[int]:
    text = ""
    for key in ("hidden_tests", "regression_tests"):
        text += "\n" + str((task.get(key) or {}).get("command") or "")
    for script in (root / "harness").glob("*.sh"):
        text += "\n" + script.read_text(encoding="utf-8", errors="replace")
    ports = {int(m) for m in re.findall(r"--port\s+(\d+)", text)}
    ports |= {int(m) for m in re.findall(r"\bPORT=(\d+)", text)}
    return sorted(ports)


def _gold_hits(task: Dict, root: Path) -> List[str]:
    gate = ((task.get("gates") or {}).get("api_removal") or {})
    if not isinstance(gate, dict) or gate.get("expect_fail") or gate.get("positive"):
        return []
    regex = gate.get("source_regex")
    if not regex:
        return []
    gold = root / "gold"
    if not gold.is_dir():
        return []
    dirs = gate.get("source_dirs") or []
    hits: List[str] = []
    for raw in dirs:
        rel = str(raw)
        candidates = [p for p in gold.rglob(Path(rel).name) if p.is_file()]
        for cand in candidates:
            result = api_removal.scan(
                source_dirs=[str(cand)],
                source_regex=regex,
                exclude_globs=gate.get("exclude_globs") or [],
            )
            for hit in result.get("source_hits") or []:
                hits.append(f"{hit['file'].split('/gold/', 1)[-1]}:{hit['line']} {hit['match']}")
    return hits


def _loader_risk(task: Dict, root: Path) -> List[str]:
    """Binaries run from a directory other than the one holding TestLibrary.so."""
    text = "\n".join(
        str((task.get(k) or {}).get("command") or "")
        for k in ("hidden_tests", "regression_tests")
    )
    risks = []
    for seg in _segments(text):
        if "Foundation-testrunner" not in seg and "util_tests" not in seg:
            continue
        base = seg.split()[-1] if seg.split() else ""
        # Only POCO's TestLibrary/ClassLoader tests dlopen a test .so by bare name.
        cppignore = root / "work" / "cppignore.lnx"
        ignores_shared = False
        if cppignore.is_file():
            body = cppignore.read_text(encoding="utf-8", errors="replace")
            ignores_shared = "SharedLibraryTest" in body or "ClassLoaderTest" in body
        if ("SharedLibraryTest" in seg or "ClassLoaderTest" in seg) and not ignores_shared:
            if "LD_LIBRARY_PATH" not in seg:
                risks.append("SharedLibraryTest/ClassLoaderTest without LD_LIBRARY_PATH")
    return risks


def _gold_control(task_id: str, root: Path) -> Tuple[List[str], List[str]]:
    """Require a recorded passing gold run for any task that ships a gold answer.

    The api-gate scan above only asks whether gold would trip *that* gate.  It
    cannot see a hidden test that upstream gold does not satisfy -- yet such a
    task fails both arms for reasons that have nothing to do with the
    migration.  ``gold_sanity.py`` is the only check that runs the real gates
    against the gold answer, so its report is the control of record.

    ``gold_sanity.py`` runs the harness on the *host*.  That is not the judge
    environment (e.g. curl's build probes the host for OpenSSL), so a passing
    ``bench.py run --seed-gold --fake-model`` attempt -- the same in-image
    judge with a copied gold answer -- counts as a control too.
    """
    gold = root / "gold"
    if not gold.is_dir() or not any(p.is_file() for p in gold.rglob("*")):
        return [], []  # negative controls have no answer to restore
    controls: List[Tuple[float, str]] = []
    for path in sorted((ROOT / "reports" / "gold_sanity").glob("*.json")):
        if path.name == "summary.json":
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        runner = doc.get("runner") or {}
        where = Path(str(runner.get("root") or "")).name
        if not (where.startswith(task_id) or path.stem.startswith(task_id)):
            continue
        if str(doc.get("status") or "") == "pass":
            controls.append((path.stat().st_mtime, path.name))
    judge_root = ROOT / "reports" / "bench"
    if judge_root.is_dir():
        for path in sorted(judge_root.glob(f"gold*/{task_id}/run*/attempt.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(doc, dict):
                continue
            judge = doc.get("judge") or {}
            if not isinstance(judge, dict):
                continue
            if not doc.get("gold_seeded"):
                continue  # only a seeded gold answer is a control
            if str(doc.get("status")) == "pass" and int(judge.get("rc") or 0) == 0:
                label = path.parent.parent.parent.name
                controls.append((path.stat().st_mtime, f"bench/{label}"))
    if not controls:
        return (
            [f"no passing gold control for {task_id} "
             "(checked reports/gold_sanity and reports/bench/gold*/)"],
            [],
        )
    newest_gold = max((p.stat().st_mtime for p in gold.rglob("*") if p.is_file()), default=0.0)
    best = max(controls)
    if newest_gold > best[0]:
        return ([], [f"gold control {best[1]} is older than the current gold/ files"])
    return [], []


def check_task(root: Path, image_programs: Optional[set]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    try:
        task = taskmodel.load_task(root)
    except Exception as exc:  # noqa: BLE001
        return [f"cannot load task: {exc}"], []
    if image_programs is not None:
        missing = set()
        for key in ("hidden_tests", "regression_tests"):
            cmd = (task.get(key) or {}).get("command")
            if cmd:
                for prog in _command_programs(cmd):
                    if prog not in image_programs and prog not in BUILTINS:
                        missing.add(prog)
        for script in (root / "harness").glob("*.sh"):
            for prog in _script_programs(script):
                if prog not in image_programs:
                    missing.add(prog)
        if missing:
            errors.append("programs missing in image: " + ", ".join(sorted(missing)))
    for hit in _gold_hits(task, root):
        errors.append("gold trips api_removal gate: " + hit)
    for risk in _loader_risk(task, root):
        errors.append(risk)
    control_errors, control_warnings = _gold_control(str(task.get("task_id") or root.name), root)
    errors.extend(control_errors)
    warnings.extend(control_warnings)
    return errors, warnings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", action="append", default=[])
    ap.add_argument("--tasks-file", action="append", default=[])
    ap.add_argument("--image", default=DEFAULT_IMAGE)
    ap.add_argument("--ports", action="store_true", help="report fixed port usage")
    args = ap.parse_args(argv)

    names: List[str] = list(args.task)
    for tasks_file in args.tasks_file or []:
        for line in Path(tasks_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                names.append(line)
    roots = []
    for name in names:
        root = ROOT / "v3" / "windows_to_kylin" / "tasks" / name
        if not (root / "task.yaml").is_file():
            print(f"MISSING {name}")
            return 2
        roots.append(root)

    print(f"image {args.image}: checking programs ...", file=sys.stderr)
    programs = _image_programs(args.image)
    if programs is None:
        print("WARN could not inspect image; skipping program checks", file=sys.stderr)

    port_owner: Dict[int, List[str]] = {}
    failed = 0
    for root in roots:
        errors, warnings = check_task(root, programs)
        try:
            ports = _ports(taskmodel.load_task(root), root)
        except Exception:  # noqa: BLE001
            ports = []
        for port in ports:
            port_owner.setdefault(port, []).append(root.name)
        if errors:
            failed += 1
            print(f"FAIL {root.name}")
            for err in errors:
                print(f"     {err}")
        else:
            print(f"OK   {root.name}")
        for warn in warnings:
            print(f"WARN {root.name}: {warn}")
    if args.ports or not names:
        for port, owners in sorted(port_owner.items()):
            if len(owners) > 1:
                print(f"PORT {port} shared by {', '.join(owners)}")
    print(f"PREFLIGHT {'FAIL' if failed else 'PASS'} tasks={len(roots)} failed={failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())