#!/usr/bin/env python3
"""Compare backend units and token streams with a frozen Git implementation."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import types

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from component_method.languages.contracts import stable_digest
from component_method.languages.python.backend import PythonBackend
from component_method.languages.python.compat import legacy_unit
from component_method.languages.python.units import source_unit_records

BASELINE_REVISION = "ee50cebca10f6a89fc211e690a797bc032b265e6"
NAMESPACE = "_component_method_reference"


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=REPOSITORY)


def load_reference(revision: str) -> dict[str, types.ModuleType]:
    package = types.ModuleType(NAMESPACE)
    package.__path__ = []
    sys.modules[NAMESPACE] = package
    modules = {}
    # Keep the historical parser, dataclasses, and relative imports isolated.
    for name, path in (
        ("units", "source_scan/units.py"),
        ("discovery", "source_scan/unit_extraction.py"),
        ("ngrams", "signal_analysis/ngrams.py"),
        ("clone", "signal_analysis/clone_signal.py"),
        ("skeleton", "signal_analysis/ast_signal.py"),
        ("scan", "signal_analysis/prepare_embeddings.py"),
    ):
        source = git("show", f"{revision}:src/component_method/{path}").decode("utf-8")
        source = source.replace("component_method.source_scan.units", f"{NAMESPACE}.units")
        module = types.ModuleType(f"{NAMESPACE}.{name}")
        module.__package__ = NAMESPACE
        module.__file__ = f"{revision}:{path}"
        sys.modules[module.__name__] = module
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        modules[name] = module
    return modules


def compare(revision: str) -> dict:
    revision = git("rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}").decode().strip()
    reference = load_reference(revision)
    backend = PythonBackend()
    report = {"schema": "python-backend-comparison-v1", "revision": revision,
              "files": 0, "units": 0, "clone_streams": 0, "skeleton_streams": 0}
    records = {key: [] for key in ("sources", "units", "source_records", "clone", "skeleton")}
    archive = git("archive", "--format=tar", revision, "src/component_method")
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        for member in sorted(tree.getmembers(), key=lambda item: item.name):
            path = Path(member.name)
            if (not member.isfile() or path.suffix != ".py"
                    or any(part in reference["scan"].EXCLUDED_DIRS for part in path.parts)
                    or path.name.startswith("test_") or path.name.endswith("_test.py")):
                continue
            source = tree.extractfile(member).read().decode("utf-8")
            file_id = path.as_posix()
            entries = [{"file_id": file_id, "source_code": source}]
            expected_units = reference["discovery"].extract_unit_sources(entries)
            actual_units = [legacy_unit(unit) for unit in backend.extract_units(file_id, source)]
            if actual_units != expected_units:
                raise RuntimeError(f"source units differ: {file_id}")
            expected_records = reference["units"].source_unit_records(source)
            if source_unit_records(source) != expected_records:
                raise RuntimeError(f"source records differ: {file_id}")
            report["files"] += 1
            report["units"] += len(expected_units)
            records["sources"].append([file_id, source])
            records["units"].extend(expected_units)
            records["source_records"].append([file_id, expected_records])
            for signal, function in (("clone", "_unit_streams"), ("skeleton", "_skeleton_streams")):
                expected, error = getattr(reference[signal], function)(file_id, source)
                actual, actual_error = backend.file_token_streams(file_id, source, signal)
                expected_rows = [[s.file_id, s.unit_id, s.tokens, s.rows] for s in expected]
                actual_rows = [[s.file_id, s.unit_id, list(s.tokens), list(s.rows)] for s in actual]
                if actual_rows != expected_rows or (signal == "skeleton" and error != actual_error):
                    raise RuntimeError(f"{signal} streams differ: {file_id}")
                records[signal].append([file_id, expected_rows])
                report[f"{signal}_streams"] += len(expected)
    report["sha256"] = {key: stable_digest(value) for key, value in records.items()}
    report["backend_identity"] = backend.identity().to_json()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=BASELINE_REVISION)
    args = parser.parse_args()
    print(json.dumps(compare(args.revision), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
