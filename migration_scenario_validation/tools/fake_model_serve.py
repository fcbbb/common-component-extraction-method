#!/usr/bin/env python3
"""Serve the plumbing self-test model on a fixed address.

``baseline_trial --fake-model`` starts this server inside the controller
process, which only works when DSH runs on the same host.  On a remote
execution plane the harness has to reach the fixture itself, so this script
runs the same handler on the execution host:

    python3 tools/fake_model_serve.py --port 18811 --tool bash

It prints the OpenAI-compatible base URL on stdout once it is listening.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_trial as at  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18811)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--tool",
        default="bash",
        choices=("bash", "controlled_bash"),
        help="shell tool name the fixture should call",
    )
    args = parser.parse_args(argv)

    at._FAKE_STATE["n"] = 0
    at._FAKE_STATE["tool"] = args.tool
    server = ThreadingHTTPServer((args.host, args.port), at._FakeModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"http://{args.host}:{server.server_port}/v1", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())