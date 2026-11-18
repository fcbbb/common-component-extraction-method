#!/usr/bin/env python3
"""Generate migration task packages from a slate.

Scenarios include CUDA -> MUSA (MultiKernelBench) and the archived
CUDA -> Ascend recipes.  The package can be materialized immediately from a
local clone of the upstream benchmark (``--repo-root name=/path``); otherwise
it is written as a recipe whose ``prepare.sh`` clones the pinned commit.

Usage::

    python3 tools/extract_migrate_task.py \
        --slate cuda_to_musa/slate.yaml \
        --repo-root MultiKernelBench=/tmp/bench_src/MultiKernelBench \
        --all
"""
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

GROUPS = {
    "source_files": "source",
    "gold_files": "gold",
    "reference_files": "reference",
    "spec_files": "spec",
    "test_files": "tests",
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(x) for x in value]


def _copy_group(repo_root: Path, files: List[str], dest: Path) -> List[str]:
    copied: List[str] = []
    for rel in files:
        src = repo_root / rel
        if not src.exists():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
        copied.append(rel)
    return copied


def _prepare_script(task: Dict[str, Any]) -> str:
    source = task.get("source") or {}
    repo = str(source.get("repo", ""))
    commit = str(source.get("commit", ""))
    repo_name = str(source.get("repo_name") or repo.rstrip("/").split("/")[-1].replace(".git", ""))
    repo_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in repo_name)
    groups = {key: _as_list(source.get(key)) for key in GROUPS}
    remove = _as_list((task.get("prepare") or {}).get("remove"))
    remove_globs = _as_list((task.get("prepare") or {}).get("remove_globs"))

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'ROOT="$(cd "$(dirname "$0")" && pwd)"',
        'CACHE="${MIGRATION_BENCH_CACHE:-$HOME/.cache/migration-bench}"',
        f'REPO_DIR="$CACHE/repos/{repo_name}-{commit[:12]}"',
        f'REPO_URL={shlex.quote(repo)}',
        f'COMMIT={shlex.quote(commit)}',
        "",
        'mkdir -p "$CACHE/repos"',
        'if [ ! -d "$REPO_DIR/.git" ]; then',
        '  git clone --filter=blob:none --no-checkout "$REPO_URL" "$REPO_DIR"',
        "fi",
        'if ! git -C "$REPO_DIR" cat-file -e "$COMMIT^{commit}" 2>/dev/null; then',
        '  git -C "$REPO_DIR" fetch --depth 1 origin "$COMMIT" || true',
        "fi",
        'git -C "$REPO_DIR" checkout --detach "$COMMIT" >/dev/null 2>&1',
        'rm -rf "$ROOT/work"',
        'mkdir -p "$ROOT/work"',
        "",
    ]

    if str(task.get("layout") or "slice") == "repo":
        lines += [
            'git -C "$REPO_DIR" archive "$COMMIT" | tar -x -C "$ROOT/work"',
            "",
            "# Copy evaluator-only gold, then remove it from the agent-visible tree.",
            'rm -rf "$ROOT/gold"',
            'mkdir -p "$ROOT/gold"',
        ]
        for rel in groups["gold_files"]:
            q = shlex.quote(rel)
            lines += [
                f'if [ -e "$ROOT/work"/{q} ]; then',
                f'  mkdir -p "$ROOT/gold"/"$(dirname {q})"',
                f'  cp -a "$ROOT/work"/{q} "$ROOT/gold"/{q}',
                "fi",
            ]
        for rel in remove:
            lines.append(f'rm -rf "$ROOT/work"/{shlex.quote(rel)}')
        for pattern in remove_globs:
            # Unquoted glob on purpose: rm -f tolerates zero matches.
            lines.append(f'rm -f "$ROOT/work"/{pattern}')
        lines += [
            "",
            'if [ -f "$ROOT/README.md" ]; then cp "$ROOT/README.md" "$ROOT/work/TASK.md"; fi',
            'printf "%s\\n" "$COMMIT" > "$ROOT/work/.source_commit"',
            'echo "prepared $ROOT/work from $REPO_URL@$COMMIT"',
        ]
        return "\n".join(lines) + "\n"

    lines += [
        'copy_group() {',
        '  local group="$1"; shift',
        '  for rel in "$@"; do',
        '    if [ -e "$REPO_DIR/$rel" ]; then',
        '      mkdir -p "$ROOT/work/$group/$(dirname "$rel")"',
        '      cp -a "$REPO_DIR/$rel" "$ROOT/work/$group/$rel"',
        "    fi",
        "  done",
        "}",
        "",
    ]
    for key, group in GROUPS.items():
        if key == "gold_files":
            continue
        files = groups[key]
        if files:
            lines.append(f"copy_group {shlex.quote(group)} " + " ".join(shlex.quote(f) for f in files))
    lines += [
        "",
        "# Gold is evaluator-only; it is deliberately not copied into work/.",
        'rm -rf "$ROOT/gold"',
        'mkdir -p "$ROOT/gold"',
    ]
    for rel in groups["gold_files"]:
        q = shlex.quote(rel)
        lines += [
            f'if [ -e "$REPO_DIR"/{q} ]; then',
            f'  mkdir -p "$ROOT/gold"/"$(dirname {q})"',
            f'  cp -a "$REPO_DIR"/{q} "$ROOT/gold"/{q}',
            "fi",
        ]
    lines += [
        'if [ -f "$ROOT/README.md" ]; then cp "$ROOT/README.md" "$ROOT/work/TASK.md"; fi',
        'printf "%s\\n" "$COMMIT" > "$ROOT/work/.source_commit"',
        'echo "prepared $ROOT/work from $REPO_URL@$COMMIT"',
    ]
    return "\n".join(lines) + "\n"


def _readme(task: Dict[str, Any], provenance: Dict[str, Any]) -> str:
    source = task.get("source") or {}
    layout = str(task.get("layout") or "slice")
    if layout == "repo":
        workspace = [
            "```bash",
            "bash prepare.sh",
            "cd work",
            "```",
            "",
            "`work/` is the pinned upstream snapshot, minus the evaluator-only gold",
            "files listed in `provenance.json` and the upstream MUSA samples matched",
            "by `prepare.remove_globs` (all `prompts/musa_new_model_*.py`).  The",
            "upstream test harness is available inside the snapshot.",
        ]
    else:
        workspace = [
            "```bash",
            "bash prepare.sh",
            "cd work",
            "```",
            "",
            f"Visible: `source/`, `reference/`, `spec/`, `tests/`. "
            f"Gold kind: `{provenance.get('gold_kind', 'implementation')}`; "
            "the gold files are listed in `provenance.json` and are not copied to `work/`.",
        ]
    return "\n".join(
        [
            f"# {task.get('task_id')} — {task.get('title', '')}",
            "",
            f"- **Scenario**: `{task.get('scenario')}`",
            f"- **Level**: `{task.get('level')}`  **Fit**: `{task.get('fit', '')}`",
            f"- **Source kind**: `{task.get('source_kind')}`",
            f"- **Source**: {source.get('repo')} @ `{source.get('commit')}`",
            f"- **License**: {source.get('license')}",
            "",
            "## Task",
            "",
            str(task.get("spec", "")).strip(),
            "",
            "## Workspace",
            "",
            *workspace,
            "",
            "## Hidden tests",
            "",
            "```bash",
            str((task.get("hidden_tests") or {}).get("command", "")),
            "```",
            "",
        ]
    )


def _write_package(
    task: Dict[str, Any],
    out_root: Path,
    repo_roots: Dict[str, Path],
    *,
    force: bool,
) -> Path:
    tid = str(task["task_id"])
    root = out_root / tid
    if root.exists() and not force:
        raise FileExistsError(f"{root} exists; use --force")
    root.mkdir(parents=True, exist_ok=True)
    (root / "harness").mkdir(exist_ok=True)

    source = task.get("source") or {}
    repo_name = str(source.get("repo_name") or "")
    if not repo_name:
        repo_name = str(source.get("repo") or "").rstrip("/").split("/")[-1].removesuffix(".git")
    repo_root = repo_roots.get(repo_name)
    layout = str(task.get("layout") or "slice")
    copied: Dict[str, List[str]] = {key: [] for key in GROUPS}
    if repo_root and repo_root.is_dir():
        for key, group in GROUPS.items():
            files = _as_list(source.get(key))
            if files and key != "gold_files" and layout != "repo":
                copied[key] = _copy_group(repo_root, files, root / group)
        gold_files = _as_list(source.get("gold_files"))
        if gold_files:
            copied["gold_files"] = _copy_group(repo_root, gold_files, root / "gold")

    provenance = {
        "task_id": tid,
        "scenario": task.get("scenario"),
        "repo": source.get("repo"),
        "commit": source.get("commit"),
        "tag": source.get("tag"),
        "license": source.get("license"),
        "source_kind": task.get("source_kind"),
        "source_files": _as_list(source.get("source_files")),
        "gold_files": _as_list(source.get("gold_files")),
        "reference_files": _as_list(source.get("reference_files")),
        "spec_files": _as_list(source.get("spec_files")),
        "test_files": _as_list(source.get("test_files")),
        "copied": copied,
        "gold_kind": task.get("gold_kind", "implementation"),
        "materialized": bool(repo_root and repo_root.is_dir()),
        "generated_by": "tools/extract_migrate_task.py",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    canonical = {k: v for k, v in task.items() if not k.startswith("_")}
    with (root / "task.yaml").open("w", encoding="utf-8") as fh:
        yaml.safe_dump(canonical, fh, sort_keys=False, allow_unicode=True, width=100)
    with (root / "provenance.json").open("w", encoding="utf-8") as fh:
        json.dump(provenance, fh, indent=2, ensure_ascii=False)

    prepare = root / "prepare.sh"
    prepare.write_text(_prepare_script(task), encoding="utf-8")
    prepare.chmod(0o755)
    (root / "README.md").write_text(_readme(task, provenance), encoding="utf-8")
    (root / ".gitignore").write_text("work/\nbuild/\n*.log\n", encoding="utf-8")

    wrapper = """#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
d = ROOT
while d != d.parent:
    if (d / "shared" / "harness" / "run_task.py").is_file():
        sys.path.insert(0, str(d))
        break
    d = d.parent
from shared.harness.run_task import main
raise SystemExit(main())
"""
    run_task = root / "harness" / "run_task.py"
    run_task.write_text(wrapper, encoding="utf-8")
    run_task.chmod(0o755)

    checker = root / "harness" / "check_result.py"
    checker.write_text(
        """#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
d = ROOT
while d != d.parent:
    if (d / "shared" / "harness" / "check_result.py").is_file():
        sys.path.insert(0, str(d))
        break
    d = d.parent
from shared.harness.check_result import main
raise SystemExit(main())
""",
        encoding="utf-8",
    )
    checker.chmod(0o755)

    if task.get("scenario") == "cuda_to_musa":
        musa_gate = root / "harness" / "check_musa_submission.py"
        musa_gate.write_text(
            """#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
d = ROOT
while d != d.parent:
    if (d / "shared" / "harness" / "check_musa_submission.py").is_file():
        sys.path.insert(0, str(d))
        break
    d = d.parent
from shared.harness.check_musa_submission import main
raise SystemExit(main())
""",
            encoding="utf-8",
        )
        musa_gate.chmod(0o755)

    api = (task.get("gates") or {}).get("api_removal") or {}
    if isinstance(api, dict):
        gate = root / "harness" / "check_api_removal.sh"
        globs = " ".join(
            f"--exclude-glob {shlex.quote(str(g))}" for g in (api.get("exclude_globs") or [])
        )
        glob_args = f"{globs} " if globs else ""
        expect_arg = "--expect-fail " if api.get("expect_fail") else ""
        source_dirs = _as_list(api.get("source_dirs")) or ["."]
        dir_args = " ".join(
            '--source-dir "$ROOT/work"'
            if d in (".", "")
            else f'--source-dir "$ROOT/work/{d}"'
            for d in source_dirs
        )
        gate.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'ROOT="$(cd "$(dirname "$0")/.." && pwd)"\n'
            'SHARED=""\n'
            'd="$ROOT"\n'
            'while [ "$d" != "/" ]; do\n'
            '  if [ -f "$d/shared/harness/api_removal.py" ]; then\n'
            '    SHARED="$d/shared/harness/api_removal.py"\n'
            "    break\n"
            "  fi\n"
            '  d="$(dirname "$d")"\n'
            "done\n"
            'if [ -z "$SHARED" ]; then\n'
            '  echo "shared/harness/api_removal.py not found above $ROOT" >&2\n'
            "  exit 2\n"
            "fi\n"
            'exec python3 "$SHARED" '
            f"{dir_args} "
            f"{expect_arg}{glob_args}--symbol-regex {shlex.quote(api.get('symbol_regex') or '')} "
            f"--source-regex {shlex.quote(api.get('source_regex') or '')} \"$@\"\n",
            encoding="utf-8",
        )
        gate.chmod(0o755)

    return root


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slate", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--repo-root", action="append", default=[], help="name=/path to local clone")
    ap.add_argument("--task", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    repo_roots: Dict[str, Path] = {}
    for item in args.repo_root:
        if "=" not in item:
            raise SystemExit(f"--repo-root must be name=path, got {item!r}")
        name, path = item.split("=", 1)
        repo_roots[name] = Path(path).resolve()

    slate_path = Path(args.slate).resolve()
    with slate_path.open("r", encoding="utf-8") as fh:
        slate = yaml.safe_load(fh) or {}
    scenario = slate.get("scenario")
    defaults = slate.get("defaults") or {}
    raw_tasks = slate.get("tasks") or []
    out_root = Path(args.out).resolve() if args.out else slate_path.parent / "tasks"
    out_root.mkdir(parents=True, exist_ok=True)

    selected = []
    for raw in raw_tasks:
        merged = _deep_merge(defaults, raw)
        merged.setdefault("scenario", scenario)
        merged["task_id"] = str(merged.get("id") or merged.get("task_id"))
        selected.append(merged)
    if args.task:
        wanted = set(args.task)
        selected = [t for t in selected if t["task_id"] in wanted]
        if wanted - {t["task_id"] for t in selected}:
            print(f"unknown task(s): {sorted(wanted - {t['task_id'] for t in selected})}", file=sys.stderr)
            return 2
    elif not args.all:
        print("refusing to generate everything without --all (or use --task)", file=sys.stderr)
        return 2

    results = []
    for task in selected:
        try:
            root = _write_package(task, out_root, repo_roots, force=args.force)
            results.append({"task": task["task_id"], "status": "ok", "root": str(root)})
        except Exception as exc:  # noqa: BLE001
            results.append({"task": task.get("task_id"), "status": "error", "error": str(exc)})

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for item in results:
            print(f"{item['status']:<8} {item['task']}")
            if item.get("error"):
                print(f"  {item['error']}")
    return 0 if all(item["status"] == "ok" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())