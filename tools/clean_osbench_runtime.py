#!/usr/bin/env python3
"""Remove root-owned test directories baked into prepared OS-Bench images.

OS-Bench images may contain test databases under /tmp that were created by the
image build as root.  The prepared images run as 10001:10001 for isolation, so
those stale directories cause permission failures.  This maintenance tool adds
a cleanup layer while preserving the image's non-root runtime user.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

TOOLS = Path(__file__).resolve().parent
REPOSITORY = TOOLS.parent
DEFAULT_WORKSPACE = REPOSITORY / "work" / "osbench"
CLEANUP_PATHS = (
    "/tmp/table_testdb",
    "/tmp/db_options_test",
    "/tmp/leveldbtest-*",
    "/tmp/pytest-of-root",
)


def image_user(image: str) -> str:
    value = subprocess.check_output(
        ["docker", "image", "inspect", image, "--format", "{{.Config.User}}"],
        text=True,
    ).strip()
    return value or "10001:10001"


def clean_image(image: str) -> None:
    user = image_user(image)
    with tempfile.TemporaryDirectory(prefix="osbench-image-clean-") as directory:
        dockerfile = Path(directory) / "Dockerfile"
        dockerfile.write_text(
            "\n".join(
                [
                    f"FROM {image}",
                    "USER 0",
                    "RUN rm -rf " + " ".join(CLEANUP_PATHS),
                    f"USER {user}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        subprocess.run(
            ["docker", "build", "-t", image, "-f", str(dockerfile), directory],
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--task", action="append", help="OS-Bench task ID; repeatable.")
    parser.add_argument("--image-prefix", default="component-method/osbench-cpp")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    rows = json.loads((workspace / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    by_id = {row["instance_id"]: row for row in rows}
    selected = args.task or list(by_id)
    missing = sorted(set(selected) - set(by_id))
    if missing:
        raise RuntimeError(f"unknown OS-Bench task IDs: {missing}")
    for instance_id in selected:
        row = by_id[instance_id]
        image = f"{args.image_prefix}:{instance_id}"
        if row.get("runtime_image") != image:
            continue
        print(f"[clean] {image}", flush=True)
        clean_image(image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())