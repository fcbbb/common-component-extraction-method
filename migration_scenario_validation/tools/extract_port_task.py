#!/usr/bin/env python3
"""Generate Windows -> Kylin task packages from a slate.

The package is a *recipe*: ``prepare.sh`` clones the pinned upstream commit,
copies it to ``work/`` and removes the target-platform files.  The upstream
Windows implementation, headers and tests stay visible; the POSIX gold stays in
the upstream commit (evaluator-only) and is listed in ``provenance.json``.

Usage::

    python3 tools/extract_port_task.py --slate windows_to_kylin/slate.yaml --all
    python3 tools/extract_port_task.py --slate ... --task l1_poco_thread --materialize
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _repo_name(url: str) -> str:
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _prepare_script(task: Dict[str, Any], provenance: Dict[str, Any]) -> str:
    source = task.get("source") or {}
    repo = str(source.get("repo", ""))
    commit = str(source.get("commit", ""))
    tag = str(source.get("tag") or "")
    subdir = str(source.get("subdir") or "").strip("/")
    repo_name = _repo_name(repo)
    remove = _as_list((task.get("prepare") or {}).get("remove")) or _as_list(
        provenance.get("gold_files")
    )
    patch = (task.get("prepare") or {}).get("patch")

    extra_repos = list(source.get("extra_repos") or [])
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'ROOT="$(cd "$(dirname "$0")" && pwd)"',
        'CACHE="${MIGRATION_BENCH_CACHE:-$HOME/.cache/migration-bench}"',
        f'REPO_DIR="$CACHE/repos/{repo_name}-{commit[:12]}"',
        f'REPO_URL={shlex.quote(repo)}',
        f'COMMIT={shlex.quote(commit)}',
        f'TAG={shlex.quote(tag)}',
        f'SUBDIR={shlex.quote(subdir)}',
        "",
        'mkdir -p "$CACHE/repos"',
        'if [ ! -d "$REPO_DIR/.git" ]; then',
        '  echo "== cloning $REPO_URL =="',
        '  git clone --filter=blob:none --no-checkout "$REPO_URL" "$REPO_DIR"',
        "fi",
        'if ! git -C "$REPO_DIR" cat-file -e "$COMMIT^{commit}" 2>/dev/null; then',
        '  echo "== fetching $COMMIT =="',
        '  if ! git -C "$REPO_DIR" fetch --depth 1 origin "$COMMIT"; then',
        '    if [ -n "$TAG" ]; then git -C "$REPO_DIR" fetch --depth 1 origin "refs/tags/$TAG"; fi',
        "  fi",
        "fi",
        'git -C "$REPO_DIR" checkout --detach "$COMMIT" >/dev/null 2>&1',
        "",
        'rm -rf "$ROOT/work"',
        'mkdir -p "$ROOT/work"',
        'if [ -n "$SUBDIR" ]; then',
        '  TMP="$(mktemp -d)"',
        '  trap \'rm -rf "$TMP"\' EXIT',
        '  git -C "$REPO_DIR" archive "$COMMIT" "$SUBDIR" | tar -x -C "$TMP"',
        '  cp -a "$TMP/$SUBDIR/." "$ROOT/work/"',
        "else",
        '  git -C "$REPO_DIR" archive "$COMMIT" | tar -x -C "$ROOT/work"',
        "fi",
        "",
    ]
    for extra in extra_repos:
        name = str(extra.get("name") or "extra")
        url = str(extra.get("repo") or "")
        sha = str(extra.get("commit") or "")
        dest = str(extra.get("dest") or name)
        extra_dir = f"$CACHE/repos/{name}-{sha[:12]}" if sha else f"$CACHE/repos/{name}"
        lines += [
            f'# extra test repo: {name}',
            f'EXTRA_DIR="{extra_dir}"',
            'if [ ! -d "$EXTRA_DIR/.git" ]; then',
            f'  git clone {shlex.quote(url)} "$EXTRA_DIR"',
            "fi",
        ]
        if sha:
            lines += [
                f'if ! git -C "$EXTRA_DIR" cat-file -e {shlex.quote(sha)}^{{commit}} 2>/dev/null; then',
                f'  git -C "$EXTRA_DIR" fetch --depth 1 origin {shlex.quote(sha)} || true',
                "fi",
                f'git -C "$EXTRA_DIR" checkout --detach {shlex.quote(sha)} >/dev/null 2>&1',
            ]
        lines += [
            f'mkdir -p "$ROOT/work/{dest}"',
            f'cp -a "$EXTRA_DIR/." "$ROOT/work/{dest}/"',
            f'rm -rf "$ROOT/work/{dest}/.git"',
            "",
        ]
    lines += [
        "# Copy the target-platform implementation to the evaluator-only gold tree.",
        'rm -rf "$ROOT/gold"',
        'mkdir -p "$ROOT/gold"',
        "copy_gold() {",
        '  rel="$1"',
        '  case "$rel" in',
        "    *[*?[]*)",
        '      mkdir -p "$ROOT/gold/$(dirname "$rel")"',
        '      cp -a $ROOT/work/$rel "$ROOT/gold/$(dirname "$rel")/" 2>/dev/null || true',
        "      ;;",
        "    *)",
        '      if [ -e "$ROOT/work/$rel" ]; then',
        '        mkdir -p "$ROOT/gold/$(dirname "$rel")"',
        '        cp -a "$ROOT/work/$rel" "$ROOT/gold/$rel"',
        "      fi",
        "      ;;",
        "  esac",
        "}",
    ]
    for item in remove:
        lines.append(f"copy_gold {shlex.quote(item)}")
    lines += [
        "",
        "# Remove the target-platform implementation from the agent-visible tree.",
    ]
    for item in remove:
        lines.append(f'rm -rf "$ROOT/work"/{shlex.quote(item)}')
    if patch:
        lines += [
            "",
            "# Optional business-embedded strip patch (removes #else POSIX branches).",
            f'if [ -f "$ROOT/harness/{patch}" ]; then',
            f'  git -C "$ROOT/work" apply "$ROOT/harness/{patch}"',
            "fi",
        ]
    lines += [
        "",
        'if [ -f "$ROOT/README.md" ]; then cp "$ROOT/README.md" "$ROOT/work/TASK.md"; fi',
        'printf "%s\\n" "$COMMIT" > "$ROOT/work/.source_commit"',
        'echo "prepared $ROOT/work from $REPO_URL@$COMMIT"',
    ]
    return "\n".join(lines) + "\n"


def _readme(task: Dict[str, Any], provenance: Dict[str, Any]) -> str:
    source = task.get("source") or {}
    target = task.get("target") or {}
    lines = [
        f"# {task.get('task_id')} — {task.get('title', '')}",
        "",
        f"- **Scenario**: `{task.get('scenario')}`",
        f"- **Level**: `{task.get('level')}`  **Fit**: `{task.get('fit', '')}`",
        f"- **Source**: {source.get('repo')} @ `{source.get('commit')}`",
        f"- **License**: {source.get('license')}",
        f"- **Target**: {target.get('os', target.get('backend', ''))} / "
        f"{target.get('toolchain', target.get('soc', ''))}",
        "",
        "## Task",
        "",
        str(task.get("spec", "")).strip(),
        "",
        "## Workspace",
        "",
        "```bash",
        "bash prepare.sh       # materialize work/ (network + git)",
        "cd work",
        "```",
        "",
        "The target-platform implementation has been removed.  Keep the public",
        "headers and the Windows source as reference; implement the missing",
        "platform layer and make the hidden tests pass.",
        "",
        "## Build",
        "",
        "```bash",
        str((task.get("build") or {}).get("command", "")),
        "```",
        "",
        "## Hidden tests",
        "",
        "```bash",
        str((task.get("hidden_tests") or {}).get("command", "")),
        "```",
        "",
        "## Gold",
        "",
        f"Gold kind: `{provenance.get('gold_kind', 'implementation')}`.  "
        "The reference files are listed in `provenance.json` and are **not** "
        "part of the agent-visible `work/` tree.",
        "",
    ]
    return "\n".join(lines)


def _write_package(task: Dict[str, Any], out_root: Path, *, force: bool) -> Path:
    tid = str(task["task_id"])
    root = out_root / tid
    if root.exists() and not force:
        raise FileExistsError(f"{root} exists; use --force to overwrite")
    root.mkdir(parents=True, exist_ok=True)
    (root / "harness").mkdir(exist_ok=True)

    source = task.get("source") or {}
    gold_files = _as_list(source.get("gold_files"))
    remove = _as_list((task.get("prepare") or {}).get("remove")) or gold_files
    provenance = {
        "task_id": tid,
        "scenario": task.get("scenario"),
        "repo": source.get("repo"),
        "commit": source.get("commit"),
        "tag": source.get("tag"),
        "subdir": source.get("subdir"),
        "license": source.get("license"),
        "source_files": _as_list(source.get("windows_files")),
        "gold_files": gold_files,
        "test_files": _as_list(source.get("test_files")),
        "remove": remove,
        "gold_kind": task.get("gold_kind", "implementation"),
        "materialized": False,
        "generated_by": "tools/extract_port_task.py",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # task.yaml is the canonical package description.
    canonical = {k: v for k, v in task.items() if not k.startswith("_")}
    canonical["prepare"] = dict(task.get("prepare") or {})
    canonical["prepare"]["remove"] = remove
    with (root / "task.yaml").open("w", encoding="utf-8") as fh:
        yaml.safe_dump(canonical, fh, sort_keys=False, allow_unicode=True, width=100)

    with (root / "provenance.json").open("w", encoding="utf-8") as fh:
        json.dump(provenance, fh, indent=2, ensure_ascii=False)

    prepare = root / "prepare.sh"
    prepare.write_text(_prepare_script(task, provenance), encoding="utf-8")
    prepare.chmod(0o755)

    (root / "README.md").write_text(_readme(task, provenance), encoding="utf-8")

    config = {
        "task_id": tid,
        "scenario": task.get("scenario"),
        "level": task.get("level"),
        "build": task.get("build"),
        "public_tests": task.get("public_tests"),
        "hidden_tests": task.get("hidden_tests"),
        "gates": task.get("gates"),
        "target": task.get("target"),
        "placeholders": ["{root}", "{work}", "{build}", "{golden}"],
    }
    with (root / "harness" / "config.json").open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)

    # Thin API gate wrapper: one implementation for all scenarios.
    api = (task.get("gates") or {}).get("api_removal") or {}
    if isinstance(api, dict):
        symbol = api.get("symbol_regex") or ""
        source_re = api.get("source_regex") or ""
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
        wrapper = f"""#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SHARED=""
d="$ROOT"
while [ "$d" != "/" ]; do
  if [ -f "$d/shared/harness/api_removal.py" ]; then
    SHARED="$d/shared/harness/api_removal.py"
    break
  fi
  d="$(dirname "$d")"
done
if [ -z "$SHARED" ]; then
  echo "shared/harness/api_removal.py not found above $ROOT" >&2
  exit 2
fi
exec python3 "$SHARED" \\
  {dir_args} \\
  {expect_arg}{glob_args}--symbol-regex {shlex.quote(symbol)} \\
  --source-regex {shlex.quote(source_re)} \\
  "$@"
"""
        gate = root / "harness" / "check_api_removal.sh"
        gate.write_text(wrapper, encoding="utf-8")
        gate.chmod(0o755)

    for name in _as_list((task.get("harness") or {}).get("scripts")):
        shim = root / "harness" / Path(str(name)).name
        shim.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'ROOT="$(cd "$(dirname "$0")/.." && pwd)"\n'
            'SHARED=""\n'
            'd="$ROOT"\n'
            'while [ "$d" != "/" ]; do\n'
            f'  if [ -f "$d/shared/harness/{Path(str(name)).name}" ]; then\n'
            f'    SHARED="$d/shared/harness/{Path(str(name)).name}"\n'
            "    break\n"
            "  fi\n"
            '  d="$(dirname "$d")"\n'
            "done\n"
            'if [ -z "$SHARED" ]; then\n'
            f'  echo "shared/harness/{Path(str(name)).name} not found above $ROOT" >&2\n'
            "  exit 2\n"
            "fi\n"
            'exec bash "$SHARED" "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)

    (root / ".gitignore").write_text("work/\nbuild/\nbuild_hidden/\n*.log\n", encoding="utf-8")
    return root


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slate", required=True)
    ap.add_argument("--out", default=None, help="output tasks/ directory")
    ap.add_argument("--task", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--materialize", action="store_true", help="run prepare.sh after writing")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    slate_path = Path(args.slate).resolve()
    with slate_path.open("r", encoding="utf-8") as fh:
        slate = yaml.safe_load(fh) or {}
    scenario = slate.get("scenario")
    defaults = slate.get("defaults") or {}
    raw_tasks = slate.get("tasks") or []
    if not raw_tasks:
        print(f"{slate_path}: no tasks", file=sys.stderr)
        return 2

    out_root = Path(args.out).resolve() if args.out else slate_path.parent / "tasks"
    out_root.mkdir(parents=True, exist_ok=True)

    selected = []
    for raw in raw_tasks:
        merged = _deep_merge(defaults, raw)
        merged.setdefault("scenario", scenario)
        merged["task_id"] = str(merged.get("id") or merged.get("task_id"))
        if not merged["task_id"]:
            raise ValueError(f"task without id in {slate_path}")
        selected.append(merged)

    if args.task:
        wanted = set(args.task)
        selected = [t for t in selected if t["task_id"] in wanted]
        missing = wanted - {t["task_id"] for t in selected}
        if missing:
            print(f"unknown task(s): {sorted(missing)}", file=sys.stderr)
            return 2
    elif not args.all:
        print("refusing to generate everything without --all (or use --task)", file=sys.stderr)
        return 2

    results = []
    for task in selected:
        try:
            root = _write_package(task, out_root, force=args.force)
            materialized = False
            if args.materialize:
                proc = subprocess.run(
                    ["bash", str(root / "prepare.sh")],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                )
                materialized = proc.returncode == 0
                if materialized:
                    prov_path = root / "provenance.json"
                    prov = json.loads(prov_path.read_text(encoding="utf-8"))
                    prov["materialized"] = True
                    prov_path.write_text(json.dumps(prov, indent=2, ensure_ascii=False), encoding="utf-8")
                else:
                    results.append(
                        {
                            "task": task["task_id"],
                            "status": "materialize-fail",
                            "log": (proc.stdout or "") + (proc.stderr or ""),
                        }
                    )
                    continue
            results.append({"task": task["task_id"], "status": "ok", "root": str(root), "materialized": materialized})
        except Exception as exc:  # noqa: BLE001
            results.append({"task": task.get("task_id"), "status": "error", "error": str(exc)})

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for item in results:
            print(f"{item['status']:<16} {item['task']}")
            if item.get("error"):
                print(f"  {item['error']}")
            if item.get("log"):
                print(item["log"][-2000:])
    return 0 if all(item["status"] == "ok" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())