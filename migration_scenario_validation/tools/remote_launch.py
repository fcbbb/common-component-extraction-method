#!/usr/bin/env python3
"""Exec a program with an environment read from a JSON document.

Used on the remote execution host: the controller cannot pass a long,
multi-line environment (the system prompt) through an ``ssh`` command line
without fragile quoting, so it ships a JSON file next to the attempt and this
launcher turns it into the child's environment before ``exec``.

Usage::

    python3 remote_launch.py <env.json> <program> [args...]
"""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: remote_launch.py <env.json> <program> [args...]", file=sys.stderr)
        return 2
    payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
    if not isinstance(payload, dict):
        print("env document must be a JSON object", file=sys.stderr)
        return 2
    environment = {str(k): str(v) for k, v in payload.items()}
    os.environ.clear()
    os.environ.update(environment)
    cwd = environment.get("COMPONENT_DSH_REMOTE_CWD") or ""
    if cwd:
        os.chdir(cwd)
    try:
        os.execv(sys.argv[2], sys.argv[2:])
    except OSError as exc:
        print(f"cannot exec {sys.argv[2]}: {exc}", file=sys.stderr)
        return 127
    return 127


if __name__ == "__main__":
    raise SystemExit(main())