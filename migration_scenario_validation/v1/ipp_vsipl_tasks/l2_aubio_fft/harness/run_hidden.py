#!/usr/bin/env python3
"""Evaluator entry point for a task package.

Steps
  1. configure + build the candidate source in a scratch build dir
  2. run harness/hidden_test against the stored golden cases
Prints one JSON object and exits non-zero if any step fails.

Usage:
  python3 harness/run_hidden.py --task-root . --golden <dir> \
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
    m = re.search(r"SUMMARY cases=(\d+) failures=(\d+)", out)
    if m:
        result["cases"] = int(m.group(1))
        result["failures"] = int(m.group(2))
    m = re.search(r"SUMMARY[^\n]*worst_rel=([0-9.eE+-]+)", out) or re.search(
        r"worst_rel=([0-9.eE+-]+)", out
    )
    if m:
        result["worst_rel"] = float(m.group(1))
    result["log"] = out[-4000:]
    print(json.dumps(result, indent=2))
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
