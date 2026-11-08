"""Inspect configured source backends and their isolated runtime toolchains."""

from collections import Counter
import json
from pathlib import Path
import secrets
import tempfile

from component_method.component_build.contracts import RepositoryContext
from component_method.component_build.validation.execution import execute_invocation
from component_method.source_scan.scanning import source_files, task_backends
from .runtime import write_driver


def inspect_configuration(config):
    root = Path(config["repository_root"]).expanduser().resolve()
    selection = task_backends(config)
    counts = Counter(backend.language_id for _, backend in source_files(root, config.get("source_subdir", "."), selection))
    commands = [(backend.language_id, argv) for backend, _ in selection.entries
                for argv in backend.toolchain_probes()]
    with tempfile.TemporaryDirectory(prefix="component-preflight-") as directory:
        workspace = Path(directory)
        for name in ("artifact", "smoke", "driver", "build"):
            (workspace / name).mkdir()
        metadata = {"nonce": secrets.token_hex(24), "entrypoints": []}
        body = "\n".join(f"command({list(argv)!r}, {language + '-' + str(index)!r})"
                         for index, (language, argv) in enumerate(commands))
        invocation = write_driver(workspace, metadata, body, evidence_level="toolchain_probe")
        result, isolation = execute_invocation(invocation, workspace, RepositoryContext(root, runtime_image=config["runtime_image"]))
        if result.returncode or result.timed_out:
            raise RuntimeError("isolated toolchain preflight failed: " + result.stdout + result.stderr)
        marker = "COMPONENT_RESULT_" + metadata["nonce"] + ":"
        reports = [json.loads(line[len(marker):]) for line in result.stdout.splitlines() if line.startswith(marker)]
        if len(reports) != 1 or reports[0].get("error"):
            raise RuntimeError("missing or failed toolchain preflight report")
    return {"schema": "language-preflight-v2", "language_backends": selection.manifest(),
            "source_files": dict(counts), "isolation": isolation, "toolchains": reports[0]}
