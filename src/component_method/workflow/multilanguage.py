"""Build artifact libraries from frozen language-partitioned candidates."""

import argparse
import gzip
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




def _load_cached_units(path: Path, sources: list[dict[str, str]],
                       enabled: set[tuple[str, str]]) -> set[tuple[str, str, str, str]]:
    """Load candidate-stage units without re-running the language parser.

    The cache is accepted only when every recorded source hash matches the
    current snapshot.  A missing or stale cache falls back to normal parsing.
    """
    path = path.expanduser().resolve()
    actual_sources = {
        entry["file_id"]: hashlib.sha256(entry["source_code"].encode("utf-8")).hexdigest()
        for entry in sources
    }
    units: set[tuple[str, str, str, str]] = set()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("schema") != "source-unit-v2":
                raise ValueError(f"unsupported unit cache schema at line {line_number}")
            file_id = row.get("file_id")
            unit_key = row.get("unit_key")
            language = row.get("language")
            backend_id = row.get("backend_id")
            if not all(isinstance(value, str) and value for value in (file_id, unit_key, language, backend_id)):
                raise ValueError(f"invalid unit cache row at line {line_number}")
            if (language, backend_id) not in enabled:
                raise ValueError(f"unit cache backend is not configured: {language} {backend_id}")
            recorded_source_hash = row.get("source_sha256")
            if recorded_source_hash and actual_sources.get(file_id) != recorded_source_hash:
                raise ValueError(f"unit cache source changed: {file_id}")
            units.add((file_id, unit_key, language, backend_id))
    if not units:
        raise ValueError("unit cache is empty")
    return units


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
    cache_path = config.get("unit_cache")
    units = None
    if cache_path:
        cache_path = Path(cache_path).expanduser()
        if not cache_path.is_absolute():
            cache_path = args.config.resolve().parent / cache_path
        try:
            units = _load_cached_units(
                cache_path, [entry for entry, _ in sources], enabled
            )
            print(f"[multilanguage] reuse unit cache: {cache_path}", flush=True)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[multilanguage] unit cache unavailable, reparsing: {exc}", flush=True)
    if units is None:
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
                                          base_url=config.get("api_base") or os.environ.get("OPENAI_API_BASE"),
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
