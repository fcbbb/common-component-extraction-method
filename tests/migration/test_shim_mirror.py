"""The ssh shim must carry artifacts across the split workspaces.

MUSA runs the agent's commands on a remote host while the method preparation
stages run here.  ``docker_api_shim.py --mirror-local`` pushes the local
workspace before every exec and pulls the remote one back afterwards; without
that, a component bundle produced by the stages never reaches the agent, and
the agent's edits never reach the local bundle check.

The transport is faked (``ssh`` runs the command locally, ``rsync`` copies
between the two directories), so this tests the mirror orchestration only.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "migration_scenario_validation" / "tools" / "docker_api_shim.py"

FAKE_SSH = """#!/bin/bash
while [ $# -gt 0 ]; do
  case "$1" in
    -o|-p|-l|-i) shift 2;;
    fakehost) shift; break;;
    *) break;;
  esac
done
exec bash -c "$*"
"""

FAKE_RSYNC = """#!/bin/bash
src=""; dst=""
while [ $# -gt 0 ]; do
  case "$1" in
    --delete) shift;;
    --exclude) shift 2;;
    --rsync-path=*) shift;;
    -e) shift 2;;
    -*) shift;;
    *) if [ -z "$src" ]; then src="$1"; else dst="$1"; fi; shift;;
  esac
done
if [ -n "$FAKE_RSYNC_FAIL_FILE" ] && [ -f "$FAKE_RSYNC_FAIL_FILE" ]; then
  echo "simulated failure" >&2; exit 23
fi
src="${src#fakehost:}"; dst="${dst#fakehost:}"
mkdir -p "$dst" || exit 1
cp -a "${src%/}/." "$dst/" || exit 1
exit 0
"""


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: Path) -> None:
        super().__init__("localhost")
        self._path = str(path)

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._path)


@pytest.fixture()
def mirror(tmp_path: Path) -> Iterator[tuple[Path, Path, Path]]:
    """Start the shim over a faked ssh transport; yield (socket, local, remote)."""
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for name, body in (("ssh", FAKE_SSH), ("rsync", FAKE_RSYNC)):
        path = fakebin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    remote.mkdir()
    (local / "seed.txt").write_text("from-local\n", encoding="utf-8")
    config = tmp_path / "remote.yaml"
    config.write_text(
        f"host: fakehost\nremote_root: {remote}\nssh_opts: []\n", encoding="utf-8"
    )
    sock = tmp_path / "shim.sock"
    env = dict(
        os.environ,
        PATH=f"{fakebin}:{os.environ.get('PATH', '')}",
        FAKE_RSYNC_FAIL_FILE=str(tmp_path / "fail-rsync"),
    )
    proc = subprocess.Popen(
        [
            sys.executable, str(SHIM),
            "--socket", str(sock),
            "--transport", "ssh",
            "--remote-config", str(config),
            "--remote-root", str(remote),
            "--mirror-local", str(local),
        ],
        env=env,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while not sock.exists():
            if proc.poll() is not None:
                raise AssertionError("shim exited before creating its socket")
            if time.monotonic() > deadline:
                raise AssertionError("shim did not create its socket")
            time.sleep(0.05)
        yield sock, local, remote
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _exec(sock: Path, command: str) -> tuple[int, str]:
    conn = _UnixConnection(sock)
    conn.request("POST", "/containers/x/exec", json.dumps({
        "Cmd": ["bash", "-lc", command], "WorkingDir": "/workspace",
    }))
    exec_id = json.loads(conn.getresponse().read())["Id"]
    conn = _UnixConnection(sock)
    conn.request("POST", f"/exec/{exec_id}/start")
    raw = conn.getresponse().read()[8:]
    conn = _UnixConnection(sock)
    conn.request("GET", f"/exec/{exec_id}/json")
    return json.loads(conn.getresponse().read())["ExitCode"], raw.decode()


def test_mirror_moves_artifacts_in_both_directions(mirror):
    sock, local, remote = mirror
    code, output = _exec(
        sock, "cat seed.txt && echo made-remotely > from_agent.txt && echo ok"
    )
    assert code == 0, output
    assert "from-local" in output
    assert (remote / "seed.txt").read_text() == "from-local\n"
    assert (local / "from_agent.txt").read_text() == "made-remotely\n"


def test_failed_push_refuses_to_run_on_a_stale_remote(mirror):
    sock, local, remote = mirror
    (local.parent / "fail-rsync").write_text("", encoding="utf-8")
    code, output = _exec(sock, "echo should-not-run > stale_marker.txt")
    assert code == 125
    assert "workspace push failed" in output
    assert not (remote / "stale_marker.txt").exists()


def test_pull_is_skipped_for_local_bundle_and_build_output(mirror):
    sock, local, remote = mirror
    (local / "component_bundle").mkdir()
    (local / "component_bundle" / "c.json").write_text("{}", encoding="utf-8")
    _exec(sock, "echo remote > build.log && echo ok")
    # component_bundle is local-owned: the remote copy must not overwrite it.
    assert (local / "component_bundle" / "c.json").read_text() == "{}"
    assert (remote / "component_bundle" / "c.json").read_text() == "{}"