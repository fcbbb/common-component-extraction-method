#!/usr/bin/env python3
"""Docker-API shim for the pinned controlled-bash plugin.

The plugin talks to ``COMPONENT_DSH_DOCKER_SOCKET`` and uses exactly four
Docker Engine endpoints:

* ``GET  /containers/<name>/json``
* ``POST /containers/<name>/exec``
* ``POST /exec/<id>/start``
* ``GET  /exec/<id>/json``

This server implements that subset over a unix socket and translates every
exec into a shell script run in one of two places:

* ``--transport local``: on this host, with a local workspace root.  Used to
  exercise the exact same plugin path without a remote machine.
* ``--transport ssh``: on a remote host over SSH, with a remote workspace
  root.  This is how the MUSA tasks run on the rented MTT S4000, which has no
  Docker daemon and no DSH installation.

Only the workspace path is mapped; the plugin's ``/workspace`` cwd becomes the
configured root.  Output is framed like Docker's multiplexed stream, because
the plugin decodes that framing.

``--mirror-local`` makes the split filesystem coherent.  The host-side method
stages (source scan, extraction, curation, retrieval) write into the local
workspace, while the agent's commands write into the remote copy.  With the
mirror enabled every exec is bracketed by:

* a push of the local workspace to the remote root (local method artifacts
  become visible to the agent), and
* a pull of the remote workspace back (agent edits become visible to the local
  stages, the bundle check and the workspace diff).

Without it, component artifacts produced on either side never reach the other.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from socketserver import ThreadingUnixStreamServer
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a project dependency
    yaml = None  # type: ignore[assignment]


MAX_OUTPUT = 1_000_000


class _State:
    def __init__(self) -> None:
        self.execs: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()


STATE = _State()


def _load_remote_config(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise SystemExit("PyYAML is required for --transport ssh")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: remote config must be a mapping")
    for key in ("host", "remote_root"):
        if not data.get(key):
            raise SystemExit(f"{path}: remote config is missing {key!r}")
    return data


def _ssh_base(cfg: Dict[str, Any]) -> List[str]:
    cmd = ["ssh"]
    cmd += [str(x) for x in (cfg.get("ssh_opts") or [])]
    if cfg.get("port"):
        cmd += ["-p", str(cfg["port"])]
    target = f"{cfg.get('user')}@{cfg['host']}" if cfg.get("user") else str(cfg["host"])
    cmd.append(target)
    return cmd


def _ssh_env(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Environment for the ssh transport.

    With ``askpass: <script>`` in the remote config, ssh reads the password
    from that helper instead of a tty.  The script itself reads a 0600 file;
    the password is never stored in this repository or in a command line.
    """
    env = dict(os.environ)
    askpass = str(cfg.get("askpass") or "")
    if askpass:
        env["SSH_ASKPASS"] = askpass
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env.setdefault("DISPLAY", ":0")
    return env


def _remote_login_path(cfg: Dict[str, Any]) -> str:
    """Return the remote login-shell PATH.

    ``_script`` passes a fixed PATH (``/usr/local/bin:/usr/bin:/bin``) because
    Docker exec does too.  On the MUSA box the SDK (``mcc``) is only on the
    login PATH, so prepend that; do not copy other variables, which may hold
    credentials the agent must not see.
    """
    proc = None
    for attempt in range(3):
        try:
            proc = subprocess.run(
                _ssh_base(cfg) + ['bash -lc \'printf %s "$PATH"\''],
                capture_output=True, text=True, timeout=60, env=_ssh_env(cfg),
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0:
            break
        time.sleep(3 * (attempt + 1))
    if proc is None or proc.returncode != 0:
        print("[shim] could not read remote login PATH; using base PATH", file=sys.stderr)
        return ""
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _remote_rsync_command(cfg: Dict[str, Any], agent_user: str) -> str:
    """Remote ``--rsync-path`` so mirroring writes as the agent's user.

    The workspace is chowned to ``agent_user``, so a plain rsync running as the
    ssh user cannot write into it.  Resolve the absolute rsync path as well:
    sudo's secure_path often does not include the directory rsync lives in.
    """
    if not agent_user:
        return ""
    proc = None
    for attempt in range(3):
        try:
            proc = subprocess.run(
                _ssh_base(cfg) + ["bash -lc 'command -v rsync'"],
                capture_output=True, text=True, timeout=60, env=_ssh_env(cfg),
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0:
            break
        time.sleep(3 * (attempt + 1))
    binary = "rsync"
    if proc is not None and proc.returncode == 0:
        lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
        if lines:
            binary = lines[-1]
    return f"sudo -n -u {shlex.quote(agent_user)} {shlex.quote(binary)}"


def _map_path(value: str, mapping: List[Tuple[str, str]]) -> str:
    for container_path, host_path in sorted(mapping, key=lambda item: -len(item[0])):
        if value == container_path:
            return host_path
        if value.startswith(container_path + "/"):
            return host_path + value[len(container_path) :]
    return value


MIRROR_PUSH_EXCLUDES = ("__pycache__/", "*.pyc")
# The local side owns ``component_bundle`` (the method tool materializes it);
# build output and VCS metadata are irrelevant to the local stages, so pulling
# them back on every exec only costs time.
MIRROR_PULL_EXCLUDES = (
    "__pycache__/",
    "*.pyc",
    ".git/",
    "build/",
    "build-*/",
    "cmake-build-*/",
    "component_bundle/",
)


class _Mirror:
    """Keep a local directory and a remote directory in sync around each exec.

    The benchmark host runs the method stages; the remote host runs the agent's
    commands.  Both write to "the workspace", so the two copies have to be
    reconciled around every exec.  Push first (local method artifacts become
    visible to the agent), then pull (agent edits become visible to the local
    stages, bundle check and workspace diff).
    """

    def __init__(
        self,
        local: Path,
        remote: str,
        cfg: Dict[str, Any],
        remote_rsync: str = "",
    ) -> None:
        self.local = Path(local).expanduser().resolve()
        self.remote = remote.rstrip("/")
        self.target = (
            f"{cfg.get('user')}@{cfg['host']}" if cfg.get("user") else str(cfg["host"])
        )
        ssh_parts = ["ssh"]
        ssh_parts += [str(x) for x in (cfg.get("ssh_opts") or [])]
        if cfg.get("port"):
            ssh_parts += ["-p", str(cfg["port"])]
        self.ssh_command = " ".join(shlex.quote(x) for x in ssh_parts)
        self.remote_rsync = remote_rsync
        self.lock = threading.Lock()

    def _rsync(
        self,
        source: str,
        destination: str,
        *,
        excludes: Tuple[str, ...],
        delete: bool,
        label: str,
    ) -> Tuple[int, str]:
        cmd = ["rsync", "-a", "-s"]
        if delete:
            cmd.append("--delete")
        for pattern in excludes:
            cmd += ["--exclude", pattern]
        if self.remote_rsync:
            cmd.append("--rsync-path=" + self.remote_rsync)
        cmd += ["-e", self.ssh_command, source, destination]
        last: Tuple[int, str] = (255, "not attempted")
        for attempt in range(1, 4):
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=1800
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                last = (255, f"{label}: {exc}")
            else:
                output = ((proc.stdout or "") + (proc.stderr or "")).strip()
                if proc.returncode == 0:
                    return 0, output
                last = (proc.returncode, output)
                # rsync 255 is a transport error; retry.  Anything else is a
                # deterministic filesystem problem and will not go away.
                if proc.returncode != 255:
                    return last
            time.sleep(2 * attempt)
        return last

    def push(self) -> Tuple[int, str]:
        return self._rsync(
            f"{self.local}/",
            f"{self.target}:{self.remote}/",
            excludes=MIRROR_PUSH_EXCLUDES,
            delete=False,
            label="push",
        )

    def pull(self) -> Tuple[int, str]:
        return self._rsync(
            f"{self.target}:{self.remote}/",
            f"{self.local}/",
            excludes=MIRROR_PULL_EXCLUDES,
            delete=True,
            label="pull",
        )


MIRROR: Optional[_Mirror] = None


def _script(
    cwd: str,
    env: List[str],
    cmd: List[str],
    *,
    agent_user: str,
    extra_path: str = "",
    block_network_env: bool = False,
) -> str:
    if block_network_env:
        # The rented MUSA container does not allow ``unshare -n``.  Point the
        # common HTTP clients at a dead local proxy so the agent cannot fetch
        # upstream MUSA samples; this is a soft gate, not a kernel firewall.
        env = list(env) + [
            "HTTP_PROXY=http://127.0.0.1:9",
            "HTTPS_PROXY=http://127.0.0.1:9",
            "http_proxy=http://127.0.0.1:9",
            "https_proxy=http://127.0.0.1:9",
            "NO_PROXY=localhost,127.0.0.1",
            "no_proxy=localhost,127.0.0.1",
        ]
    if extra_path:
        merged = []
        found = False
        for item in env:
            if item.startswith("PATH="):
                found = True
                current = item[len("PATH=") :]
                parts = [extra_path] + [p for p in current.split(":") if p]
                merged.append("PATH=" + ":".join(dict.fromkeys(parts)))
            else:
                merged.append(item)
        if not found:
            merged.append("PATH=" + extra_path)
        env = merged
    lines = [f"cd {shlex.quote(cwd)} || exit 125"]
    prefix = ""
    if agent_user:
        prefix = "sudo -n -u " + shlex.quote(agent_user) + " -- "
    lines.append("exec " + prefix + "env " + " ".join(shlex.quote(x) for x in env)
                 + " " + shlex.join(cmd) + " 2>&1")
    return "\n".join(lines) + "\n"


def _run_exec(
    *,
    transport: str,
    ssh_cfg: Optional[Dict[str, Any]],
    mapping: List[Tuple[str, str]],
    agent_user: str,
    isolate_network: bool,
    working_dir: str,
    env: List[str],
    cmd: List[str],
    login_path: str = "",
    block_network_env: bool = False,
) -> Tuple[int, bytes]:
    mapped_cwd = _map_path(working_dir or "/workspace", mapping)
    mapped_cmd = [_map_path(arg, mapping) for arg in cmd]
    script = _script(
        mapped_cwd,
        env,
        mapped_cmd,
        agent_user=agent_user,
        extra_path=login_path,
        block_network_env=block_network_env,
    )
    if transport == "local":
        proc = subprocess.run(
            ["bash", "-s"], input=script, text=True, capture_output=True, timeout=7200
        )
    else:
        assert ssh_cfg is not None
        remote = ["bash", "-s"] if not isolate_network else ["unshare", "-n", "--", "bash", "-s"]
        proc = subprocess.run(
            _ssh_base(ssh_cfg) + remote,
            input=script,
            text=True,
            capture_output=True,
            timeout=7200,
            env=_ssh_env(ssh_cfg),
        )
    output = (proc.stdout or "") + (proc.stderr or "")
    if len(output) > MAX_OUTPUT:
        output = output[-MAX_OUTPUT:]
    return proc.returncode, output.encode("utf-8", "replace")


def _frame(payload: bytes) -> bytes:
    """Docker multiplexed stream frame: type byte, 3 pad bytes, u32 size."""
    return struct.pack(">B3xI", 1, len(payload)) + payload


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    # Injected by make_server
    transport = "local"
    ssh_cfg: Optional[Dict[str, Any]] = None
    mapping: List[Tuple[str, str]] = []
    agent_user = ""
    isolate_network = False
    container_name = "remote"
    login_path = ""
    block_network_env = False

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        print(f"[shim] {fmt % args}", file=sys.stderr, flush=True)

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            value = {}
        return value if isinstance(value, dict) else {}

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/_ping":
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"OK")
            return
        if path.startswith("/containers/") and path.endswith("/json"):
            self._json(200, {"Name": self.container_name, "State": {"Running": True}})
            return
        if path.startswith("/exec/") and path.endswith("/json"):
            exec_id = unquote(path[len("/exec/") : -len("/json")])
            with STATE.lock:
                record = STATE.execs.get(exec_id)
            if record is None:
                self._json(404, {"message": f"no such exec: {exec_id}"})
                return
            self._json(200, {"ExitCode": record["exit_code"], "Running": False})
            return
        self._json(404, {"message": f"unsupported GET {path}"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/containers/") and path.endswith("/exec"):
            body = self._body()
            exec_id = uuid.uuid4().hex
            with STATE.lock:
                STATE.execs[exec_id] = {
                    "WorkingDir": body.get("WorkingDir") or "/workspace",
                    "Env": [str(x) for x in (body.get("Env") or [])],
                    "Cmd": [str(x) for x in (body.get("Cmd") or [])],
                    "exit_code": 125,
                }
            self._json(201, {"Id": exec_id})
            return
        if path.startswith("/exec/") and path.endswith("/start"):
            exec_id = unquote(path[len("/exec/") : -len("/start")])
            with STATE.lock:
                record = STATE.execs.get(exec_id)
            if record is None:
                self._json(404, {"message": f"no such exec: {exec_id}"})
                return
            # One exec at a time: the mirror makes the two workspaces a single
            # resource, so concurrent commands must not interleave push/pull.
            if MIRROR is not None:
                MIRROR.lock.acquire()
            try:
                code, output = self._exec_with_mirror(record)
            finally:
                if MIRROR is not None:
                    MIRROR.lock.release()
            with STATE.lock:
                record["exit_code"] = code
            payload = _frame(output)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.docker.raw-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self._json(404, {"message": f"unsupported POST {path}"})

    def _exec_with_mirror(self, record: Dict[str, Any]) -> Tuple[int, bytes]:
        if MIRROR is not None:
            rc, out = MIRROR.push()
            if rc != 0:
                # Running on a stale remote workspace would silently drop the
                # component artifacts the method stages just produced.
                return 125, (
                    "[shim] workspace push failed; refusing to run on a stale "
                    f"remote workspace (rsync={rc})\n{out[-2000:]}\n"
                ).encode("utf-8", "replace")
        try:
            code, output = _run_exec(
                transport=self.transport,
                ssh_cfg=self.ssh_cfg,
                mapping=self.mapping,
                agent_user=self.agent_user,
                isolate_network=self.isolate_network,
                working_dir=record["WorkingDir"],
                env=record["Env"],
                cmd=record["Cmd"],
                login_path=self.login_path,
                block_network_env=self.block_network_env,
            )
        except subprocess.TimeoutExpired:
            code, output = 124, b"[shim] exec timed out after 7200s\n"
        except OSError as exc:
            code, output = 127, f"[shim] cannot start exec: {exc}\n".encode()
        if MIRROR is not None:
            rc, out = MIRROR.pull()
            if rc != 0:
                # The verdict comes from the remote judge; a failed pull only
                # costs local evidence.  Say so instead of failing the command.
                print(
                    f"[shim] workspace pull failed (rsync={rc}): {out[-500:]}",
                    file=sys.stderr,
                    flush=True,
                )
        return code, output


def make_server(socket_path: Path, **options: Any) -> ThreadingUnixStreamServer:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    class Server(ThreadingUnixStreamServer):
        daemon_threads = True
        allow_reuse_address = True

    class BoundHandler(Handler):
        pass

    for key, value in options.items():
        setattr(BoundHandler, key, value)
    server = Server(str(socket_path), BoundHandler)
    return server


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--socket", required=True)
    ap.add_argument("--transport", choices=["local", "ssh"], default="local")
    ap.add_argument("--root", default="", help="workspace root for --transport local")
    ap.add_argument("--remote-config", default="")
    ap.add_argument("--remote-root", default="", help="workspace root on the remote host")
    ap.add_argument("--container-name", default="remote")
    ap.add_argument("--agent-user", default="")
    ap.add_argument("--isolate-network", action="store_true")
    ap.add_argument("--mirror-local", default="",
                    help="local workspace to push/pull around every ssh exec")
    ap.add_argument("--ready-file", default="")
    args = ap.parse_args(argv)

    global MIRROR
    login_path = ""
    block_network_env = False
    if args.transport == "local":
        if args.mirror_local:
            ap.error("--mirror-local is only meaningful with --transport ssh")
        root = args.root or os.getcwd()
        mapping = [("/workspace", str(Path(root).resolve()))]
    else:
        if not args.remote_config or not args.remote_root:
            ap.error("--transport ssh needs --remote-config and --remote-root")
        mapping = [("/workspace", args.remote_root)]
        ssh_cfg = _load_remote_config(Path(args.remote_config))
        login_path = _remote_login_path(ssh_cfg)
        block_network_env = bool(ssh_cfg.get("block_network_env"))
        if args.mirror_local:
            local = Path(args.mirror_local).expanduser()
            if not local.is_dir():
                ap.error(f"--mirror-local is not a directory: {local}")
            MIRROR = _Mirror(
                local,
                args.remote_root,
                ssh_cfg,
                _remote_rsync_command(ssh_cfg, args.agent_user),
            )
    socket_path = Path(args.socket)
    server = make_server(
        socket_path,
        transport=args.transport,
        ssh_cfg=None if args.transport == "local" else ssh_cfg,
        mapping=mapping,
        agent_user=args.agent_user,
        isolate_network=args.isolate_network,
        container_name=args.container_name,
        login_path=login_path,
        block_network_env=block_network_env,
    )

    if args.ready_file:
        Path(args.ready_file).write_text(str(socket_path), encoding="utf-8")
    print(f"[shim] transport={args.transport} socket={socket_path} "
          f"map={mapping}", file=sys.stderr, flush=True)
    if MIRROR is not None:
        print(f"[shim] mirror {MIRROR.local} <-> {MIRROR.target}:{MIRROR.remote}",
              file=sys.stderr, flush=True)

    def stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        try:
            socket_path.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())