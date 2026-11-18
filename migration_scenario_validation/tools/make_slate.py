#!/usr/bin/env python3
"""Render a slate YAML into Markdown/CSV for review and provenance.

Usage::

    python3 tools/make_slate.py \
        --slate windows_to_kylin/slate.yaml --out-md windows_to_kylin/task_slate.md \
        --out-csv provenance.csv
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(x) for x in value]


def _flush_md(handle, title: str, rows: List[Dict[str, Any]]) -> None:
    handle.write(f"# {title}\n\n")
    handle.write("| # | Task ID | Level | Fit | Counted | Source kind | Task | Upstream |\n")
    handle.write("|---:|---|---|---|---|---|---|---|\n")
    for index, row in enumerate(rows, 1):
        source = row.get("source") or {}
        handle.write(
            f"| {index} | `{row['task_id']}` | {row.get('level', '')} | "
            f"{row.get('fit', '')} | {'yes' if row.get('counted', True) else 'no'} | "
            f"{row.get('source_kind', '')} | {row.get('title', '')} | "
            f"{source.get('repo', '')} @ `{str(source.get('commit', ''))[:12]}` |\n"
        )
    core = sum(1 for row in rows if row.get("counted", True))
    handle.write(f"\nCore tasks: **{core}**; total packages: **{len(rows)}**.\n\n")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slate", action="append", required=True)
    ap.add_argument("--out-md", action="append", default=[])
    ap.add_argument("--out-csv", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    all_rows: List[Dict[str, Any]] = []
    for slate_index, slate_path in enumerate(args.slate):
        path = Path(slate_path).resolve()
        with path.open("r", encoding="utf-8") as fh:
            slate = yaml.safe_load(fh) or {}
        defaults = slate.get("defaults") or {}
        scenario = slate.get("scenario")
        rows: List[Dict[str, Any]] = []
        for raw in slate.get("tasks") or []:
            row = dict(defaults)
            row.update(raw)
            row.setdefault("scenario", scenario)
            row["task_id"] = str(row.get("id") or row.get("task_id"))
            row.setdefault("counted", True)
            rows.append(row)
        all_rows.extend(rows)
        if args.out_md:
            out = Path(args.out_md[slate_index] if slate_index < len(args.out_md) else args.out_md[0])
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8") as fh:
                _flush_md(fh, f"Task slate: {scenario}", rows)

    if args.out_csv:
        path = Path(args.out_csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            fields = [
                "scenario",
                "task_id",
                "level",
                "fit",
                "counted",
                "source_kind",
                "title",
                "repo",
                "commit",
                "license",
            ]
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in all_rows:
                source = row.get("source") or {}
                writer.writerow(
                    {
                        "scenario": row.get("scenario"),
                        "task_id": row["task_id"],
                        "level": row.get("level"),
                        "fit": row.get("fit"),
                        "counted": row.get("counted", True),
                        "source_kind": row.get("source_kind"),
                        "title": row.get("title"),
                        "repo": source.get("repo"),
                        "commit": source.get("commit"),
                        "license": source.get("license"),
                    }
                )

    if args.json:
        print(json.dumps(all_rows, indent=2, ensure_ascii=False))
    else:
        core = sum(1 for row in all_rows if row.get("counted", True))
        print(f"tasks={len(all_rows)} core={core}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())