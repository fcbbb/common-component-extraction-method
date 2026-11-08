"""Build artifact libraries from frozen language-partitioned candidates."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from component_method.component_build.contracts import RepositoryContext
from component_method.component_build.extraction.runner import OfficialImageExtractionRunner
from component_method.component_build.pipeline import build_artifact_library
from component_method.languages.contracts import stable_digest
from component_method.protocol_candidates.extraction import pack_protocol_candidates
from component_method.source_scan.scanning import source_files, task_backends


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    root = Path(config["repository_root"]).expanduser().resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"preserving existing pipeline output: {output}")
    selection = task_backends(config)
    sources = list(source_files(root, config.get("source_subdir", "."), selection))
    candidates = json.loads(args.candidates.read_text())["candidates"]
    enabled = {(backend.language_id, backend.backend_id) for backend, _ in selection.entries}
    if any((c.get("language"), c.get("backend_id")) not in enabled for c in candidates):
        raise ValueError("candidate language/backend is not configured")
    units = {(unit.file_id, unit.unit_key, unit.language, unit.backend_id)
             for source, backend in sources
             for unit in backend.extract_units(source["file_id"], source["source_code"])}
    for candidate in candidates:
        for unit in candidate.get("units", []):
            reference = (unit["file_id"], unit.get("unit_key", unit.get("unit_id")),
                         candidate["language"], candidate["backend_id"])
            if reference not in units:
                raise ValueError(f"candidate unit is absent from the current source snapshot: {reference}")
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is required for extraction and independent review")
    import docker

    client = docker.from_env()
    try:
        runtime_image = client.images.get(config["runtime_image"]).id
    finally:
        client.close()
    packets = pack_protocol_candidates(candidates)
    output.mkdir(parents=True)
    frozen = {"schema": "artifact-pipeline-input-v2", "language_backends": selection.manifest(),
              "candidates_sha256": hashlib.sha256(args.candidates.read_bytes()).hexdigest(),
              "sources": {entry["file_id"]: stable_digest(entry["source_code"]) for entry, _ in sources},
              "model": config["model"], "runtime_image": runtime_image, "task_blind": True}
    (output / "input_manifest.json").write_text(json.dumps(frozen, indent=2) + "\n")
    runner = OfficialImageExtractionRunner(model=config["model"], api_key=os.environ["OPENAI_API_KEY"],
                                          base_url=config.get("api_base", os.environ.get("OPENAI_API_BASE")),
                                          runtime_image=runtime_image, repository_root=root,
                                          timeout_seconds=config.get("agent_timeout_seconds", 1080))
    repository = RepositoryContext(root, runtime_image=runtime_image, metadata={"languages": config.get("languages", [])})
    result = build_artifact_library(packets=packets, repository=repository, agent_runner=runner,
                                    output_dir=output / "build", max_repairs=config.get("max_repairs", 0),
                                    repository_id=config.get("repository", ""), source_commit=config.get("source_commit", ""))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if any(item["status"] == "failed" for item in result["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
