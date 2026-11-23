#!/usr/bin/env python3
"""Run the V3 transformation extraction chain over the frozen history corpus.

Stages: ``scan -> extract -> curate -> review -> publish -> verify``.

Examples::

    # No model: corpus integrity only.
    python3 tools/extract_transformation.py --stage scan

    # Full chain (needs MODEL_NAME / OPENAI_API_BASE / OPENAI_API_KEY).
    python3 tools/extract_transformation.py --stage all --resume

    # Verify the published library against its corpus.
    python3 tools/extract_transformation.py --stage verify

``--spec`` points at the history spec; its directory is used as the corpus root.
The published library defaults to ``v3/windows_to_kylin/library_generated`` so
the hand-built ``v3/windows_to_kylin/library`` is never overwritten.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
if str(PROJECT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT / "src"))

from component_method.component_build.methodology.pipeline import main  # noqa: E402


def _expand_spec(argv: list[str]) -> list[str]:
    """Translate ``--spec <path>`` into ``--history <path.parent>``."""
    expanded: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--spec":
            if index + 1 >= len(argv):
                raise SystemExit("--spec needs a path")
            expanded.extend(["--history", str(Path(argv[index + 1]).expanduser().resolve().parent)])
            index += 2
            continue
        if value.startswith("--spec="):
            expanded.extend(
                ["--history", str(Path(value.split("=", 1)[1]).expanduser().resolve().parent)]
            )
            index += 1
            continue
        expanded.append(value)
        index += 1
    return expanded


if __name__ == "__main__":
    raise SystemExit(main(_expand_spec(sys.argv[1:])))