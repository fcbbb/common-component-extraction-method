#!/usr/bin/env python3
"""Sync a task workspace to a remote accelerator host and run a command.

Used by the CUDA -> MUSA scenario because the MTT S4000 is not on the
development machine.  The script deliberately shells out to ``ssh``/``rsync``
(or ``tar`` when rsync is unavailable); it does not require Paramiko.

Config (``env/remote.yaml``)::

    host: 10.0.0.20
    user: ubuntu
    port: 22
    remote_root: /data/migration-bench
    ssh_opts: ["-o", "StrictHostKeyChecking=accept-new"]
    rsync: true

Usage::

    python3 shared/harness/run_remote.py --config env/remote.yaml \
        --local-dir tasks/b1_mkb_add/work \
        --remote-dir b1_mkb_add/work \
        --command "python3 harness/run_task.py --device musa"
"""
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def _load_config(path: str | Path) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("remote config must be a mapping")
    for key in ("host", "remote_root"):
        if not data.get(key):
            raise ValueError(f"remote config missing {key}")
    return data


def _ssh_base(cfg: Dict[str, Any]) -> List[str]:
    cmd = ["ssh"]
    cmd += [str(x) for x in (cfg.get("ssh_opts") or [])]
    if cfg.get("port"):
        cmd += ["-p", str(cfg["port"])]
    target = f"{cfg.get('user')}@{cfg['host']}" if cfg.get("user") else str(cfg["host"])
    cmd.append(target)
    return cmd


def _sync(local: Path, remote: str, cfg: Dict[str, Any], dry_run: bool) -> str:
    target = f"{cfg.get('user')}@{cfg['host']}" if cfg.get("user") else str(cfg["host"])
    remote_path = f"{remote.rstrip('/')}/{local.name}"
    if cfg.get("rsync", True) and shutil.which("rsync"):
        cmd = ["rsync", "-az", "--delete"]
        if cfg.get("port"):
            cmd += ["-e", f"ssh -p {cfg['port']}"]
        cmd += [str(local) + "/", f"{target}:{remote_path}/"]
    else:
        # tar over ssh fallback
        ssh = _ssh_base(cfg)
        cmd = (
            f"tar -C {shlex.quote(str(local))} -czf - . | "
            + " ".join(shlex.quote(x) for x in ssh)
            + f" 'mkdir -p {shlex.quote(remote_path)} && tar -xzf - -C {shlex.quote(remote_path)}'"
        )
    if dry_run:
        return "DRY-RUN " + (cmd if isinstance(cmd, str) else " ".join(cmd))
    proc = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout or "") + (proc.stderr or ""))
    return (proc.stdout or "") + (proc.stderr or "")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--local-dir", required=True)
    ap.add_argument("--remote-dir", required=True)
    ap.add_argument("--command", required=True)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    try:
        cfg = _load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        return 2

    local = Path(args.local_dir).resolve()
    remote_root = str(cfg["remote_root"])
    remote_task_dir = f"{remote_root.rstrip('/')}/{args.remote_dir.strip('/')}"

    result: Dict[str, Any] = {
        "status": "error",
        "host": cfg["host"],
        "local": str(local),
        "remote": remote_task_dir,
        "command": args.command,
        "sync": "",
        "log": "",
    }

    try:
        result["sync"] = _sync(local, f"{remote_root}/{args.remote_dir.strip('/')}", cfg, args.dry_run)
        if args.dry_run:
            result["status"] = "dry-run"
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        ssh_cmd = _ssh_base(cfg) + [f"cd {shlex.quote(remote_task_dir)} && {args.command}"]
        proc = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=args.timeout)
        result["log"] = (proc.stdout or "") + (proc.stderr or "")
        result["status"] = "pass" if proc.returncode == 0 else "fail"
        result["returncode"] = proc.returncode
    except subprocess.TimeoutExpired:
        result["status"] = "fail"
        result["error"] = f"remote timeout after {args.timeout}s"
    except Exception as exc:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = str(exc)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] in {"pass", "dry-run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())