#!/usr/bin/env python3
"""Prepare a remote execution host to run the benchmark itself.

The rented MUSA box is a plain Ubuntu container: no Docker daemon, no Node,
no DSH.  It cannot host nested containers (no ``CAP_SYS_ADMIN``), so the
execution plane for ``cuda_to_musa`` is the remote host itself.  This script
makes that host a first-class execution environment:

1. install the pinned Node.js (24.9.0) under ``<remote_root>/toolchain``;
2. mirror this repository (sources + DSH workspace only) to
   ``<remote_root>/repo``;
3. install and build the DSH plugins there (``npm ci && npm run build``);
4. verify ``node``/``dsh``/``component_method`` all resolve.

Once ``bootstrap`` succeeds the attempt no longer needs a shim or a second
copy of the workspace: the agent, the method stages and the judge all run in
one filesystem, on the machine that has the target toolchain.

Usage::

    python3 tools/remote_setup.py check
    python3 tools/remote_setup.py bootstrap
    python3 tools/remote_setup.py bootstrap --skip-repo   # Node only
    python3 tools/remote_setup.py sync                    # repo + plugin rebuild
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a project dependency
    yaml = None  # type: ignore[assignment]

# The remote execution plane needs the whole repository (DSH plugins, the
# component-method package, and the benchmark itself), not just this directory.
ROOT = Path(__file__).resolve().parents[2]
BENCH_ROOT = Path(__file__).resolve().parents[1]
PINNED_NODE = "24.9.0"
DEFAULT_REMOTE_CONFIG = BENCH_ROOT / "env" / "remote.yaml"

# Everything the remote execution plane needs.  Work products, credentials and
# the other scenarios stay local.
REPO_EXCLUDES = [
    "**/node_modules",
    "**/.venv",
    ".git",
    "**/__pycache__",
    "*.pyc",
    "**/reports",
    "**/archive",
    "**/windows_to_kylin",
    "**/ipp_vsipl_tasks",
    "**/work",
    "**/gold",
    "**/gold_authored",
    "**/upstream_nonconforming",
    # V3 history corpora contain `after` target implementations, and the
    # published library contains retrieval targets.  Neither belongs in the
    # remote repository an agent can inspect; the method arm stages the
    # selected bundle explicitly.
    "**/history",
    "**/library",
    "**/library_generated",
    "**/runs",
    "**/bench.env",
    "**/remote.yaml",
    "**/.env",
    "*.pem",
    "*.key",
]


def _load_config(path: Path) -> Dict:
    if yaml is None:
        raise SystemExit("PyYAML is required to read env/remote.yaml")
    if not path.is_file():
        raise SystemExit(f"remote config is missing: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not data.get("host"):
        raise SystemExit(f"remote config has no host: {path}")
    return data


def _ssh_env(cfg: Dict) -> Dict[str, str]:
    env = dict(os.environ)
    askpass = str(cfg.get("askpass") or "")
    if askpass:
        env["SSH_ASKPASS"] = askpass
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env.setdefault("DISPLAY", ":0")
    return env


def _ssh_base(cfg: Dict) -> List[str]:
    cmd = ["ssh", "-o", "BatchMode=no"]
    cmd += [str(x) for x in (cfg.get("ssh_opts") or [])]
    if cfg.get("port"):
        cmd += ["-p", str(cfg["port"])]
    target = f"{cfg.get('user')}@{cfg['host']}" if cfg.get("user") else str(cfg["host"])
    cmd.append(target)
    return cmd


def _run(cmd: List[str], *, timeout: int, env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired as exc:
        return 124, f"timeout after {timeout}s: {exc}"
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


_TRANSIENT = (
    "Connection closed by",
    "Connection reset by",
    "Connection timed out",
    "kex_exchange_identification",
    "ssh_exchange_identification",
    "Broken pipe",
)


def _retry(cmd: List[str], cfg: Dict, *, timeout: int) -> Tuple[int, str]:
    last = (255, "")
    for attempt in range(5):
        rc, out = _run(cmd, timeout=timeout, env=_ssh_env(cfg))
        if rc == 0 or not any(marker in out for marker in _TRANSIENT):
            return rc, out
        last = (rc, out)
        time.sleep(min(30, 3 * 2**attempt))
    return last


def _ssh(cfg: Dict, command: str, *, timeout: int = 3600, stream: bool = False) -> Tuple[int, str]:
    if stream:
        return _retry(_ssh_base(cfg) + [command], cfg, timeout=timeout)
    # Non-interactive: keep stdout/stderr separate from ssh's own diagnostics.
    return _retry(
        _ssh_base(cfg) + [f"bash -lc {shlex.quote(command)}"], cfg, timeout=timeout
    )


def _rsync(cfg: Dict, source: Path, remote_dir: str, *, timeout: int = 3600) -> Tuple[int, str]:
    target = f"{cfg.get('user')}@{cfg['host']}" if cfg.get("user") else str(cfg["host"])
    ssh_parts = ["ssh"]
    ssh_parts += [str(x) for x in (cfg.get("ssh_opts") or [])]
    if cfg.get("port"):
        ssh_parts += ["-p", str(cfg["port"])]
    cmd = ["rsync", "-a", "--delete"]
    for pattern in REPO_EXCLUDES:
        cmd += ["--exclude", pattern]
    cmd += ["-e", " ".join(ssh_parts), f"{source}/", f"{target}:{remote_dir}/"]
    return _retry(cmd, cfg, timeout=timeout)


def _rsync_put(
    cfg: Dict, source: Path, remote_dir: str, *, timeout: int = 600
) -> Tuple[int, str]:
    """Copy a single file (or directory) to the remote host, no excludes."""
    target = f"{cfg.get('user')}@{cfg['host']}" if cfg.get("user") else str(cfg["host"])
    ssh_parts = ["ssh"]
    ssh_parts += [str(x) for x in (cfg.get("ssh_opts") or [])]
    if cfg.get("port"):
        ssh_parts += ["-p", str(cfg["port"])]
    cmd = ["rsync", "-a", "-e", " ".join(ssh_parts), str(source), f"{target}:{remote_dir}/"]
    return _retry(cmd, cfg, timeout=timeout)


def sync_repo(cfg: Dict, *, build: bool = True, timeout: int = 3600) -> Tuple[int, str]:
    """Mirror the repository to the remote host and rebuild the DSH plugins.

    ``npm ci`` runs only when the remote has no installed tree; ``npm run
    build`` always runs, because the plugins' ``dist/`` is what DSH loads and
    the sources were just overwritten.

    The component-method stages resolve their release root as
    ``<release>/repository`` plus ``<release>/offline_artifacts``.  The mirror
    lives at ``<remote_root>/repo``, so a ``repository`` symlink keeps that
    layout without a second copy of the tree.
    """
    root = str(cfg.get("remote_root") or "/root/migration-bench")
    repo_dir = f"{root}/repo"
    rc, out = _ssh(cfg, f"mkdir -p {shlex.quote(repo_dir)}", timeout=300)
    if rc != 0:
        return rc, out
    layout = (
        f"mkdir -p {shlex.quote(root + '/offline_artifacts')} && "
        f"if [ ! -e {shlex.quote(root + '/repository')} ]; then "
        f"ln -s repo {shlex.quote(root + '/repository')}; fi"
    )
    rc, out = _ssh(cfg, layout, timeout=300)
    if rc != 0:
        return rc, out
    rc, out = _rsync(cfg, ROOT, repo_dir, timeout=timeout)
    if rc != 0 or not build:
        return rc, out
    path = f"{root}/toolchain/node/bin:/usr/local/bin:/usr/bin:/bin"
    command = (
        f"export PATH={path}; cd {shlex.quote(repo_dir + '/dsh')} && "
        f"if [ ! -x node_modules/.bin/dsh ]; then npm ci --no-audit --no-fund; fi && "
        f"npm run build"
    )
    return _ssh(cfg, command, timeout=timeout)


def bootstrap(args: argparse.Namespace) -> int:
    cfg = _load_config(Path(args.remote_config))
    root = str(cfg.get("remote_root") or "/root/migration-bench")
    node_dir = f"{root}/toolchain/node-v{PINNED_NODE}-linux-x64"
    repo_dir = f"{root}/repo"

    rc, out = _ssh(cfg, f"mkdir -p {shlex.quote(root + '/toolchain')} {shlex.quote(repo_dir)}")
    if rc != 0:
        print(f"ERROR cannot create remote directories: {out[-800:]}", file=sys.stderr)
        return 2

    if not args.skip_node:
        rc, out = _ssh(cfg, f"{shlex.quote(node_dir + '/bin/node')} --version")
        current = out.strip().splitlines()[-1] if rc == 0 else ""
        if current == f"v{PINNED_NODE}":
            print(f"node     {current} (already installed)")
        else:
            print(f"node     installing v{PINNED_NODE} -> {node_dir}")
            script = f"""set -euo pipefail
cd /tmp
version={PINNED_NODE}
tarball=node-v${{version}}-linux-x64.tar.gz
base=https://nodejs.org/dist/v${{version}}
curl -fsSLO "$base/$tarball"
curl -fsSLO "$base/SHASUMS256.txt"
expected=$(awk -v f="$tarball" '$2==f {{print $1}}' SHASUMS256.txt)
test -n "$expected"
echo "$expected  $tarball" | sha256sum -c -
rm -rf {shlex.quote(node_dir)}
mkdir -p {shlex.quote(root + '/toolchain')}
tar -xzf "$tarball" -C {shlex.quote(root + '/toolchain')}
ln -sfn {shlex.quote(node_dir)} {shlex.quote(root + '/toolchain/node')}
{shlex.quote(node_dir + '/bin/node')} --version
"""
            rc, out = _ssh(cfg, script, timeout=1800)
            if rc != 0:
                print(f"ERROR node install failed: {out[-1500:]}", file=sys.stderr)
                return 2
            print(f"node     {out.strip().splitlines()[-1]}")

    if args.skip_repo:
        return 0

    print(f"repo     syncing {ROOT} -> {repo_dir}")
    started = time.time()
    rc, out = sync_repo(cfg, build=True)
    if rc != 0:
        print(f"ERROR repo sync failed: {out[-1500:]}", file=sys.stderr)
        return 2
    print(f"repo     synced in {time.time() - started:.1f}s")

    return check(args, quiet=True)


def check(args: argparse.Namespace, *, quiet: bool = False) -> int:
    cfg = _load_config(Path(args.remote_config))
    root = str(cfg.get("remote_root") or "/root/migration-bench")
    path = f"{root}/toolchain/node/bin:/usr/local/bin:/usr/bin:/bin"
    probes = {
        "node": f"{root}/toolchain/node/bin/node --version",
        "npm": f"export PATH={path}; npm --version",
        "dsh": f"export PATH={path}; {root}/repo/dsh/node_modules/.bin/dsh --version",
        "python": "python3 --version",
        "component_method": (
            f"cd {root}/repo && PYTHONPATH={root}/repo/src "
            f"python3 -c 'import component_method, sys; print(component_method.__file__)'"
        ),
        "docker": "command -v docker || true",
    }
    failures = 0
    report: Dict[str, str] = {}
    for name, command in probes.items():
        rc, out = _ssh(cfg, command, timeout=300)
        value = out.strip().splitlines()[-1] if out.strip() else ""
        if name == "docker":
            report[name] = value or "absent (expected)"
            continue
        report[name] = value if rc == 0 else f"FAIL rc={rc}: {value[:200]}"
        if rc != 0:
            failures += 1
    if not quiet:
        for name, value in report.items():
            print(f"{name:<18} {value}")
    print(json.dumps({"ok": failures == 0, "remote": report}, ensure_ascii=False))
    return 0 if failures == 0 else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("check", "bootstrap", "sync"))
    ap.add_argument("--remote-config", default=str(DEFAULT_REMOTE_CONFIG))
    ap.add_argument("--skip-node", action="store_true")
    ap.add_argument("--skip-repo", action="store_true")
    args = ap.parse_args(argv)
    if args.command == "sync":
        cfg = _load_config(Path(args.remote_config))
        rc, out = sync_repo(cfg)
        if rc != 0:
            print(f"ERROR sync failed: {out[-2000:]}", file=sys.stderr)
            return 2
        print("repo     synced and built")
        return 0
    return bootstrap(args) if args.command == "bootstrap" else check(args)


if __name__ == "__main__":
    raise SystemExit(main())