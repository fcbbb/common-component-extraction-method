from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from component_method.component_build.methodology.contracts import (
    normalize_response,
    normalize_transformation,
    render_readme,
    validate_transformation,
)
from component_method.component_build.methodology.corpus import CorpusError, load_corpus
from component_method.component_build.methodology.curate import curate
from component_method.component_build.methodology.finalize import finalize_entries
from component_method.component_build.methodology import pipeline as pipeline_module
from component_method.component_build.methodology.pipeline import extract, main
from component_method.component_build.methodology.publish import publish, verify_library
from component_method.component_build.methodology.review import (
    review_entries,
    validate_review,
)
from component_method.component_build.methodology.revise import revise_entries
from component_method.component_build.methodology.service import (
    build_extraction_task,
    build_review_task,
    build_revision_task,
    load_prompt,
)
from component_method.component_build.submission import (
    load_submission,
    validate_methodology_extraction,
    validate_methodology_review,
)
from component_method.library_publish.agent_bundle import agent_bundle_prompt


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or f"/* {path.name} */\n", encoding="utf-8")


def _transformation(**overrides):
    value = {
        "status": "draft_ready",
        "title": "File lifecycle port",
        "capability": "file-system/io",
        "when_to_use": "A task must rebuild open/close semantics behind an existing handle abstraction.",
        "mapping_rules": [
            "open handle -> open descriptor with close-on-exec and the same access mode",
            "close handle -> close descriptor, preserving the first error",
        ],
        "semantic_deltas": [
            "errors surface through errno instead of a Win32 error code",
        ],
        "pitfalls": [
            "a short read is normal and must not be treated as end of file",
        ],
        "procedure": [
            "inventory the shared contract and every caller expectation",
            "map each name to the target primitive and emulate only the deltas",
        ],
        "verification": [
            "open, read, write and close probe including an error path",
        ],
        "boundary": "Local filesystems only; async I/O and change notification are outside.",
        "applicability": {
            "os": ["linux"],
            "constraints": [],
        },
        "evidence": [
            {
                "project": "libuv",
                "commit": "abc123",
                "task_id": "ex1",
                "role": "source-migration",
            }
        ],
    }
    value.update(overrides)
    return value


def _example(
    root: Path,
    *,
    task_id: str = "ex1",
    capability: str = "file-system/io",
    repo: str = "https://example.com/libuv.git",
    scenario: str | None = None,
    policy: dict | None = None,
) -> Path:
    example = root / "examples" / task_id
    _write(example / "repo" / "src" / "win" / "impl.c")
    _write(example / "repo" / "src" / "unix" / "impl.c")
    _write(example / "repo" / "include" / "api.h")
    _write(example / "repo" / "test" / "test_impl.c")
    metadata = {
        "schema": "migration-history-example-v1",
        "generated_by": "tools/build_history_corpus.py",
        "task_id": task_id,
        "capability": capability,
        "source": {
            "repo": repo,
            "commit": "abc123",
            "license": "MIT",
        },
        "target": {"os": "kylin-v10-sp3", "arch": "x86_64"},
        "spec": "Port the file layer.",
        "workspace": "repo",
        "files": {
            "before": ["src/win/impl.c"],
            "after": ["src/unix/impl.c"],
            "context": ["include/api.h"],
            "tests": ["test/test_impl.c"],
        },
        "packet": {"path": "inputs/focus_context_packets.json", "sha256": ""},
    }
    packet = {
        "schema": "migration-focus-context-packets-v1",
        "packets": [
            {
                "packet_id": f"history_{task_id}",
                "focus_files": ["src/unix/impl.c"],
                "context_files": ["src/win/impl.c", "include/api.h", "test/test_impl.c"],
                "focus_unit_count": 1,
                "context_unit_count": 3,
            }
        ],
    }
    packet_path = example / "inputs" / "focus_context_packets.json"
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    metadata["packet"]["sha256"] = hashlib.sha256(packet_path.read_bytes()).hexdigest()
    (example / "example.json").write_text(json.dumps(metadata), encoding="utf-8")
    index_path = root / "index.json"
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {
            "schema": "migration-history-corpus-v1",
            "library_id": "windows-to-posix-transformations",
            "examples": [],
        }
    if scenario:
        index["scenario"] = scenario
    if policy:
        index["policy"] = policy
    if not any(item.get("task_id") == task_id for item in index["examples"]):
        index["examples"].append({"task_id": task_id})
    index_path.write_text(json.dumps(index), encoding="utf-8")
    return example


class _ExtractRunner:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def run_workspace_agent(self, **kwargs):
        self.calls.append(kwargs["task_label"])
        return self.response


class _PayloadReviewRunner:
    """Return a full review payload keyed by the proposed transformation id."""

    def __init__(self, factory):
        self.factory = factory
        self.calls = []

    def run_workspace_agent(self, **kwargs):
        transformation_id = kwargs["task_label"].split(":", 1)[1]
        self.calls.append(transformation_id)
        return self.factory(transformation_id)


class _ReviewRunner:
    def __init__(self, verdict="publish"):
        self.verdict = verdict
        self.calls = []

    def run_workspace_agent(self, **kwargs):
        transformation_id = kwargs["task_label"].split(":", 1)[1]
        self.calls.append(transformation_id)
        return {
            "transformation_id": transformation_id,
            "verdict": self.verdict,
            "summary": "The mapping is grounded and the boundary is explicit.",
            "must_change": (
                [_rework_review(transformation_id)["must_change"][0]]
                if self.verdict == "rework"
                else []
            ),
        }


def test_normalize_and_render(tmp_path: Path):
    example_meta = json.loads((_example(tmp_path) / "example.json").read_text())
    normalized = normalize_transformation(_transformation(), example=example_meta)
    assert normalized["transformation_id"] == "file-lifecycle-port"
    assert normalized["evidence"][0]["task_id"] == "ex1"
    assert validate_transformation(normalized, example=example_meta) == []
    readme = render_readme(
        {
            **normalized,
            "bundle_id": normalized["transformation_id"],
            "provenance": {"task_ids": ["ex1"]},
        }
    )
    assert "## Mapping rules" in readme
    assert "## When to use" in readme


@pytest.mark.parametrize(
    "field, value",
    [
        ("mapping_rules", "see src/unix/impl.c for the pattern"),
        ("procedure", "```c\nopen(path);\n```"),
        ("notes", '#include "api.h"'),
        ("verification", "open /home/user/project/file.c"),
    ],
)
def test_leakage_rejected(tmp_path: Path, field: str, value):
    example_meta = json.loads((_example(tmp_path) / "example.json").read_text())
    payload = _transformation()
    if field in {"mapping_rules", "procedure", "verification"}:
        payload[field] = [*payload[field], value]
    else:
        payload[field] = value
    normalized = normalize_transformation(payload, example=example_meta)
    errors = validate_transformation(normalized, example=example_meta)
    assert any("path" in error or "code" in error or "include" in error for error in errors), errors


def test_standard_system_headers_are_not_leakage(tmp_path: Path):
    example_meta = json.loads((_example(tmp_path) / "example.json").read_text())
    normalized = normalize_transformation(
        _transformation(
            applicability={
                "os": ["ignored"],
                "constraints": ["uses sys/statfs.h and linux/magic.h"],
            }
        ),
        example=example_meta,
    )
    assert validate_transformation(normalized, example=example_meta) == []


def test_list_items_drop_their_own_bullet(tmp_path: Path):
    example_meta = json.loads((_example(tmp_path) / "example.json").read_text())
    normalized = normalize_transformation(
        _transformation(
            mapping_rules=[
                "- open handle -> open descriptor",
                "- close handle -> close descriptor",
            ]
        ),
        example=example_meta,
    )
    assert normalized["mapping_rules"] == [
        "open handle -> open descriptor",
        "close handle -> close descriptor",
    ]


def test_minimal_agent_card_is_complete_at_normalization(tmp_path: Path):
    example_meta = json.loads((_example(tmp_path) / "example.json").read_text())
    card = {
        "title": "File lifecycle port",
        "when_to_use": "A task must rebuild open/close semantics behind an existing handle abstraction.",
        "mapping_rules": [
            "open handle -> open descriptor with close-on-exec and the same access mode",
            "close handle -> close descriptor, preserving the first error",
        ],
        "procedure": [
            "inventory the callers",
            "map each operation to the target primitive",
        ],
        "semantic_deltas": [
            "errors surface through errno instead of a Win32 error code",
        ],
        "pitfalls": [
            "a short read is normal and must not be treated as end of file",
        ],
        "verification": [
            "open, read, write and close probe including an error path",
        ],
        "boundary": "Local filesystems only; async I/O and change notification are outside.",
        "applicability": {"os": ["ignored"], "constraints": ["glibc >= 2.17"]},
    }
    status, accepted, audit, rejected = normalize_response(
        {"transformations": [card]}, example=example_meta
    )
    assert status == "ready"
    assert audit == {}
    assert rejected == []
    component = accepted[0]
    # Identity, capability and the target environment are pipeline-owned.
    assert component["transformation_id"] == "file-lifecycle-port"
    assert component["capability"] == "file-system/io"
    assert component["applicability"] == {
        "os": ["kylin-v10-sp3", "x86_64"],
        "constraints": ["glibc >= 2.17"],
    }
    assert component["evidence"][0]["task_id"] == "ex1"
    # Derived fields that only repeated the title or were always constant are gone.
    for absent in (
        "covers",
        "keywords",
        "source_pattern",
        "target_pattern",
        "confidence",
        "leakage_class",
        "source_migrations",
    ):
        assert absent not in component
    assert validate_transformation(component, example=example_meta) == []
    readme = render_readme({**component, "bundle_id": component["transformation_id"]})
    assert "Source (" not in readme
    assert "## Mapping rules" in readme


def test_prose_card_needs_no_itemization(tmp_path: Path):
    history = tmp_path / "history"
    _example(history)
    example = load_corpus(history).examples[0]
    card = {
        "title": "Descriptor lifecycle",
        "when_to_use": (
            "Use this when a migrated layer must replace a platform handle "
            "lifecycle with descriptors and preserve the ownership contract."
        ),
        "mapping_rules": (
            "Map each source handle to a descriptor and keep ownership with the "
            "opener; close it on every exit path."
        ),
        "procedure": "Open the resource, use it, then close it on every path.",
        "semantic_deltas": (
            "Errors arrive through errno instead of a platform error code."
        ),
        "pitfalls": (
            "A short read is normal and must not be treated as end of file."
        ),
        "verification": (
            "Open, read and close a file and check that the error path still "
            "releases the descriptor."
        ),
        "boundary": "Local filesystems only; async I/O is outside this component.",
        "applicability": {"os": ["linux"], "constraints": []},
    }

    _, accepted, _, rejected = normalize_response(
        {"transformations": [card]}, example=example.metadata
    )

    assert rejected == []
    transformation = accepted[0]
    assert transformation["mapping_rules"] == [card["mapping_rules"]]
    assert transformation["procedure"] == [card["procedure"]]

    readme = render_readme(transformation)
    # One paragraph is rendered as a paragraph, not as a one-item list.
    assert f"- {card['mapping_rules']}" not in readme
    assert card["mapping_rules"] in readme
    assert f"1. {card['procedure']}" not in readme
    assert card["procedure"] in readme


def test_workspace_audit_must_cover_before_and_after(tmp_path: Path):
    example_meta = json.loads((_example(tmp_path) / "example.json").read_text())
    response = {
        "status": "ready",
        "workspace_audit": {"checked_files": ["src/unix/impl.c"], "gaps": []},
        "transformations": [_transformation()],
    }
    with pytest.raises(ValueError, match="did not inspect"):
        normalize_response(response, example=example_meta)


def test_full_chain_with_fake_agents(tmp_path: Path):
    history = tmp_path / "history"
    _example(history)
    run_root = tmp_path / "runs"
    response = {
        "status": "ready",
        "workspace_audit": {
            "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
            "gaps": [],
        },
        "transformations": [_transformation()],
    }
    extract_runner = _ExtractRunner(response)
    summary = extract(
        history,
        run_root,
        runner=extract_runner,
        model="fixture",
        workers=1,
        resume=False,
    )
    assert summary["failed"] == 0
    assert len(extract_runner.calls) == 1

    curated = curate(history, run_root / "extract", run_root / "curated")
    assert curated["accepted_count"] == 1

    review_runner = _ReviewRunner()
    reviews = review_entries(
        history,
        run_root / "curated",
        run_root / "reviews",
        runner=review_runner,
        model="fixture",
        workers=1,
    )
    assert reviews["verdict_counts"] == {"publish": 1}

    library = tmp_path / "library"
    publication = publish(
        history,
        run_root / "curated",
        run_root / "reviews",
        library,
    )
    assert publication["component_count"] == 1
    assert publication["components"][0]["bundle_id"] == "file-lifecycle-port"
    verified = verify_library(library, history_root=history)
    assert verified["status"] == "ok"
    manifest = json.loads((library / "manifest.json").read_text())
    assert manifest["kind"] == "methodology"
    assert manifest["schema_version"] == "methodology-1"
    component = json.loads(
        (library / "components" / "file-lifecycle-port" / "component.json").read_text()
    )
    assert component["review"]["verdict"] == "publish"
    assert "src/unix/impl.c" not in json.dumps(component)


def test_discarded_component_is_never_published(tmp_path: Path):
    history = tmp_path / "history"
    _example(history)
    run_root = tmp_path / "runs"
    response = {
        "status": "ready",
        "workspace_audit": {
            "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
            "gaps": [],
        },
        "transformations": [_transformation()],
    }
    extract(history, run_root, runner=_ExtractRunner(response), model="fixture", workers=1, resume=False)
    curate(history, run_root / "extract", run_root / "curated")
    review_entries(
        history,
        run_root / "curated",
        run_root / "reviews",
        runner=_ReviewRunner(verdict="discard"),
        model="fixture",
        workers=1,
    )
    library = tmp_path / "library"
    publication = publish(history, run_root / "curated", run_root / "reviews", library)
    assert publication["component_count"] == 0
    assert publication["skipped"][0]["reason"].startswith("discarded by review")
    assert not (library / "components" / "file-lifecycle-port").exists()


def test_pipeline_cli_with_fixtures(tmp_path: Path, capsys):
    history = tmp_path / "history"
    _example(history)
    fixture_root = tmp_path / "fixtures"
    (fixture_root / "methodology").mkdir(parents=True)
    (fixture_root / "methodology" / "ex1.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "workspace_audit": {
                    "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
                    "gaps": [],
                },
                "transformations": [_transformation()],
            }
        ),
        encoding="utf-8",
    )
    review_runner = _ReviewRunner()
    (fixture_root / "methodology_review").mkdir(parents=True)
    (fixture_root / "methodology_review" / "file-lifecycle-port.json").write_text(
        json.dumps(review_runner.run_workspace_agent(task_label="review:file-lifecycle-port")),
        encoding="utf-8",
    )
    library = tmp_path / "library"
    code = main(
        [
            "--history",
            str(history),
            "--library",
            str(library),
            "--fixture-root",
            str(fixture_root),
            "--stage",
            "all",
            "--workers",
            "1",
        ]
    )
    assert code == 0, capsys.readouterr().out
    assert json.loads((library / "manifest.json").read_text())["component_count"] == 1


def test_corpus_policy_is_declared_per_scenario(tmp_path: Path):
    history = tmp_path / "history"
    _example(
        history,
        repo="https://example.com/MultiKernelBench.git",
        scenario="cuda_to_musa",
        policy={
            "library_source_repos": ["MultiKernelBench"],
            "held_out_repos": ["poco"],
        },
    )
    corpus = load_corpus(history)
    assert corpus.examples[0].scenario == "cuda_to_musa"

    held_out = tmp_path / "held_out"
    _example(
        held_out,
        repo="https://example.com/poco.git",
        scenario="windows_to_kylin",
        policy={
            "library_source_repos": ["libuv"],
            "held_out_repos": ["poco"],
        },
    )
    with pytest.raises(CorpusError, match="held-out"):
        load_corpus(held_out)


def test_history_spec_normalizes_scenario_policy(tmp_path: Path):
    from migration_scenario_validation.tools import build_history_corpus as builder

    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        "\n".join(
            [
                "schema: migration-history-spec-v1",
                "scenario: cuda_to_musa",
                "library_source_repos: [MultiKernelBench]",
                "held_out_repos: [triton]",
                "examples:",
                "  - task_id: e1",
                "    capability: gpu-compute",
                "",
            ]
        ),
        encoding="utf-8",
    )
    spec = builder._load_spec(spec_path)
    assert spec["scenario"] == "cuda_to_musa"
    assert spec["library_id"] == "cuda-to-musa-transformations"
    assert spec["language"] == "python"
    assert spec["backend_id"] == "python@1"
    assert spec["library_source_repos"] == ["MultiKernelBench"]
    assert spec["held_out_repos"] == ["triton"]

    conflicting = tmp_path / "conflicting.yaml"
    conflicting.write_text(
        "\n".join(
            [
                "schema: migration-history-spec-v1",
                "scenario: ipp_to_vsipl",
                "library_source_repos: [ipp]",
                "held_out_repos: [ipp]",
                "examples:",
                "  - task_id: e1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="both source and held out"):
        builder._load_spec(conflicting)


def test_other_scenario_shares_full_chain(tmp_path: Path):
    history = tmp_path / "history"
    _example(
        history,
        repo="https://example.com/MultiKernelBench.git",
        scenario="cuda_to_musa",
        policy={
            "library_source_repos": ["MultiKernelBench"],
            "held_out_repos": ["triton"],
        },
    )
    transformation = _transformation(
        capability="gpu-compute",
        evidence=[
            {
                "project": "multikernelbench",
                "commit": "abc123",
                "task_id": "ex1",
                "role": "source-migration",
            }
        ],
    )
    response = {
        "status": "ready",
        "workspace_audit": {
            "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
            "gaps": [],
        },
        "transformations": [transformation],
    }
    run_root = tmp_path / "runs"
    extract(history, run_root, runner=_ExtractRunner(response), model="fixture", workers=1, resume=False)
    curate(history, run_root / "extract", run_root / "curated")
    review_entries(
        history,
        run_root / "curated",
        run_root / "reviews",
        runner=_ReviewRunner(),
        model="fixture",
        workers=1,
    )
    library = tmp_path / "library"
    publication = publish(history, run_root / "curated", run_root / "reviews", library)
    assert publication["components"][0]["bundle_id"] == "file-lifecycle-port"
    assert verify_library(library, history_root=history)["status"] == "ok"


def test_stage_prompts_expose_only_their_own_context(tmp_path: Path):
    history = tmp_path / "history"
    _example(history)
    example = load_corpus(history).examples[0]

    extraction = build_extraction_task(
        example, load_prompt("extract_transformation_system.txt")
    )
    assert "## Review criteria" not in extraction
    assert "required_changes" not in extraction
    assert "License:" not in extraction
    assert "Migration scenario" not in extraction
    assert "workspace_audit" not in extraction
    assert '"transformations"' in extraction

    entry = {
        "transformation": {
            **_transformation(),
            "transformation_id": "file-lifecycle-port",
        }
    }
    review = build_review_task(
        entry, example, load_prompt("review_transformation_system.txt")
    )
    assert "## Proposal under review" in review
    assert "workspace_audit" not in review
    assert "extraction_response" not in review
    assert "## Verdict" in review
    assert "## Must change" in review
    for forbidden in ("hidden_tests", "task.yaml", "gold_files", "held_out"):
        assert forbidden not in extraction
        assert forbidden not in review


def test_extraction_prompt_stays_scenario_neutral():
    prompt = " ".join(load_prompt("extract_transformation_system.txt").split())
    for token in (
        "Win32",
        "POSIX",
        "CUDA",
        "MUSA",
        "Kylin",
        "libuv",
        "libarchive",
        "POCO",
        "nginx",
    ):
        assert token not in prompt
    # The agent writes only the experience card; the pipeline owns the rest.
    for field in (
        '"title"',
        '"when_to_use"',
        '"mapping_rules"',
        '"procedure"',
        '"semantic_deltas"',
        '"pitfalls"',
        '"verification"',
        '"boundary"',
        '"applicability"',
    ):
        assert field in prompt
    assert "exactly one component" in prompt
    # Source-side claims and ownership are the two recurring review failures.
    assert "who allocates it" in prompt
    # The card may be prose; no item counts or length caps are imposed.
    assert "one paragraph or a short list" in prompt
    # Checks must be reachable by an ordinary unprivileged process, not that
    # every check is an executable test.
    assert "ordinary unprivileged process" in prompt


def test_revision_prompt_replaces_the_quoted_statements():
    prompt = " ".join(
        load_prompt("revise_transformation_component.txt").split()
    )
    assert "Replace each quoted statement" in prompt
    # A repair keeps the rest of the card intact.
    assert "Keep every other field" in prompt
    assert "may stay a paragraph" in prompt


def test_review_prompt_outputs_a_verdict_and_change_objects():
    prompt = " ".join(load_prompt("review_transformation_system.txt").split())
    assert '"verdict"' in prompt
    assert '"must_change"' in prompt
    for verdict in ('`publish`', '`discard`', '`rework`'):
        assert verdict in prompt
    # A change names its field, quotes the defect and states the replacement.
    assert '"field"' in prompt
    assert '"quote"' in prompt
    assert '"instruction"' in prompt
    assert "copied from the field" in prompt
    for removed in ("major", "minor", '"checks"', '"confidence"', '"issues"'):
        assert removed not in prompt


def test_publish_verdict_carries_no_must_change():
    review = _publish_review("file-lifecycle-port")
    assert validate_review(review, transformation_id="file-lifecycle-port") == []


def test_discard_verdict_carries_no_must_change():
    review = _discard_review("file-lifecycle-port")
    assert validate_review(review, transformation_id="file-lifecycle-port") == []


def test_rework_verdict_needs_a_concrete_change():
    review = _rework_review("file-lifecycle-port")
    assert validate_review(review, transformation_id="file-lifecycle-port") == []
    review["must_change"] = []
    errors = validate_review(review, transformation_id="file-lifecycle-port")
    assert any("rework needs" in error for error in errors)


def test_publish_verdict_cannot_carry_a_must_change_list():
    review = _publish_review("file-lifecycle-port")
    review["must_change"] = [_rework_review("x")["must_change"][0]]
    errors = validate_review(review, transformation_id="file-lifecycle-port")
    assert any("cannot carry" in error for error in errors)


def test_a_must_change_item_must_be_a_change_object():
    review = _rework_review("file-lifecycle-port")
    review["must_change"] = ["fix it"]
    errors = validate_review(review, transformation_id="file-lifecycle-port")
    assert any("object with field" in error for error in errors)


def test_a_must_change_quote_must_appear_in_its_field(tmp_path: Path):
    example_meta = json.loads((_example(tmp_path) / "example.json").read_text())
    component = normalize_transformation(_transformation(), example=example_meta)
    review = _rework_review("file-lifecycle-port")
    assert validate_review(
        review,
        transformation_id="file-lifecycle-port",
        transformation=component,
    ) == []

    review["must_change"][0]["quote"] = "a statement that is not in the component"
    errors = validate_review(
        review,
        transformation_id="file-lifecycle-port",
        transformation=component,
    )
    assert any("does not appear" in error for error in errors)


def test_one_example_yields_one_component(tmp_path: Path):
    example_meta = json.loads((_example(tmp_path) / "example.json").read_text())
    with pytest.raises(ValueError, match="exactly one component"):
        normalize_response(
            {
                "transformations": [
                    _transformation(),
                    _transformation(title="Second family port"),
                ]
            },
            example=example_meta,
        )
    with pytest.raises(ValueError, match="exactly one component"):
        normalize_response({"transformations": []}, example=example_meta)


def _rework_review(transformation_id: str) -> dict:
    return {
        "transformation_id": transformation_id,
        "verdict": "rework",
        "summary": "The semantic delta describes an error model the target does not use.",
        "must_change": [
            {
                "field": "semantic_deltas",
                "quote": "errors surface through errno instead of a Win32 error code",
                "instruction": (
                    "State the target error behavior without the source "
                    "platform's error model."
                ),
            }
        ],
    }


def _publish_review(transformation_id: str) -> dict:
    return {
        "transformation_id": transformation_id,
        "verdict": "publish",
        "summary": "Every rule is grounded in the before/after pair.",
        "must_change": [],
    }


def _discard_review(transformation_id: str) -> dict:
    return {
        "transformation_id": transformation_id,
        "verdict": "discard",
        "summary": "The component restates the task and adds no reusable decision.",
        "must_change": [],
    }


def test_rework_and_finalize_publish_a_repaired_component(tmp_path: Path):
    history = tmp_path / "history"
    _example(history)
    run_root = tmp_path / "runs"
    run_root.mkdir()
    response = {
        "status": "ready",
        "workspace_audit": {
            "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
            "gaps": [],
        },
        "transformations": [_transformation()],
    }
    extract(
        history,
        run_root,
        runner=_ExtractRunner(response),
        model="fixture",
        workers=1,
        resume=False,
    )
    curate(history, run_root / "extract", run_root / "curated")
    review_entries(
        history,
        run_root / "curated",
        run_root / "reviews",
        runner=_PayloadReviewRunner(_rework_review),
        model="fixture",
        workers=1,
    )

    revised_payload = _transformation(
        title="File lifecycle port, grounded",
        mapping_rules=[
            "open handle -> open descriptor with close-on-exec and the same access mode",
            "close handle -> close descriptor, preserving the first error",
            "short read -> return the short count; never treat it as an error or end of file",
        ],
        semantic_deltas=[
            "errors arrive through errno using the target's own error numbers",
        ],
    )

    class _RevisionRunner:
        def run_workspace_agent(self, **kwargs):
            assert kwargs["task_label"] == "methodology-revise:file-lifecycle-port"
            assert (
                "errors surface through errno instead of a Win32 error code"
                in kwargs["task"]
            )
            return {
                "status": "ready",
                "workspace_audit": {
                    "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
                    "gaps": [],
                },
                "transformations": [revised_payload],
            }

    summary = revise_entries(
        history,
        run_root / "curated",
        run_root / "reviews",
        run_root / "rework" / "r1",
        runner=_RevisionRunner(),
        model="fixture",
        workers=1,
    )
    assert summary["revised_count"] == 1
    assert summary["status_counts"] == {"revised": 1}
    entries = json.loads(
        (run_root / "rework" / "r1" / "transformations.json").read_text()
    )
    assert entries[0]["transformation"]["title"] == "File lifecycle port, grounded"
    assert entries[0]["revision"]["review_verdict"] == "rework"
    assert entries[0]["revision"]["must_change"]
    assert entries[0]["entry_digest"] != json.loads(
        (run_root / "curated" / "transformations.json").read_text()
    )[0]["entry_digest"]

    class _FinalizeRunner:
        def run_workspace_agent(self, **kwargs):
            assert kwargs["task_label"] == "methodology-finalize:file-lifecycle-port"
            assert (
                "errors surface through errno instead of a Win32 error code"
                in kwargs["task"]
            )
            return {
                "status": "ready",
                "workspace_audit": {
                    "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
                    "gaps": [],
                },
                "transformations": [
                    _transformation(
                        title="File lifecycle port, grounded",
                        mapping_rules=[
                            "open handle -> open descriptor with close-on-exec and the same access mode",
                            "short read -> return the short count, never an error",
                        ],
                        semantic_deltas=[
                            "errors arrive through errno using the target's own error numbers",
                        ],
                    )
                ],
            }

    final = finalize_entries(
        history,
        run_root / "rework" / "r1",
        run_root / "reviews",
        run_root / "final",
        runner=_FinalizeRunner(),
        model="fixture",
        workers=1,
    )
    assert final["finalized_count"] == 1
    final_review = json.loads(
        (run_root / "final" / "reviews" / "file-lifecycle-port" / "review.json").read_text()
    )
    assert final_review["verdict"] == "publish"
    assert final_review["finalized"] is True
    assert final_review["must_change"] == _rework_review("x")["must_change"]

    library = tmp_path / "library"
    publish(
        history,
        run_root / "final",
        run_root / "final" / "reviews",
        library,
    )
    component = json.loads(
        (library / "components" / "file-lifecycle-port" / "component.json").read_text()
    )
    assert component["title"] == "File lifecycle port, grounded"
    assert component["review"]["verdict"] == "publish"
    assert component["review"]["finalized"] is True


def test_revision_id_is_owned_by_the_pipeline(tmp_path: Path):
    history = tmp_path / "history"
    _example(history)
    run_root = tmp_path / "runs"
    response = {
        "status": "ready",
        "workspace_audit": {
            "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
            "gaps": [],
        },
        "transformations": [_transformation()],
    }
    extract(history, run_root, runner=_ExtractRunner(response), model="fixture", workers=1, resume=False)
    curate(history, run_root / "extract", run_root / "curated")
    review_entries(
        history,
        run_root / "curated",
        run_root / "reviews",
        runner=_PayloadReviewRunner(_rework_review),
        model="fixture",
        workers=1,
    )

    class _RenamingRunner:
        def run_workspace_agent(self, **kwargs):
            return {
                "status": "ready",
                "workspace_audit": {
                    "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
                    "gaps": [],
                },
                "transformations": [
                    _transformation(title="Another family port")
                ],
            }

    summary = revise_entries(
        history,
        run_root / "curated",
        run_root / "reviews",
        run_root / "rework" / "r1",
        runner=_RenamingRunner(),
        model="fixture",
        workers=1,
    )
    assert summary["revised_count"] == 1
    assert summary["kept_original_count"] == 0
    entries = json.loads(
        (run_root / "rework" / "r1" / "transformations.json").read_text()
    )
    assert entries[0]["transformation_id"] == "file-lifecycle-port"
    result = json.loads(
        (run_root / "rework" / "r1" / "file-lifecycle-port" / "revision.json").read_text()
    )
    assert result["status"] == "revised"
    assert result["transformation"]["transformation_id"] == "file-lifecycle-port"
    assert result["transformation"]["capability"] == "file-system/io"


def test_finalize_passes_through_components_it_did_not_rework(tmp_path: Path):
    history = tmp_path / "history"
    _example(history)
    run_root = tmp_path / "runs"
    response = {
        "status": "ready",
        "workspace_audit": {
            "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
            "gaps": [],
        },
        "transformations": [_transformation()],
    }
    extract(history, run_root, runner=_ExtractRunner(response), model="fixture", workers=1, resume=False)
    curate(history, run_root / "extract", run_root / "curated")
    review_entries(
        history,
        run_root / "curated",
        run_root / "reviews",
        runner=_ReviewRunner(verdict="publish"),
        model="fixture",
        workers=1,
    )

    class _NoCallRunner:
        def run_workspace_agent(self, **kwargs):
            raise AssertionError("a publish verdict must not enter the finalize round")

    summary = finalize_entries(
        history,
        run_root / "curated",
        run_root / "reviews",
        run_root / "final",
        runner=_NoCallRunner(),
        model="fixture",
        workers=1,
    )
    assert summary["unchanged_count"] == 1
    assert summary["finalized_count"] == 0
    reused = json.loads(
        (run_root / "final" / "reviews" / "file-lifecycle-port" / "review.json").read_text()
    )
    original = json.loads(
        (run_root / "reviews" / "file-lifecycle-port" / "review.json").read_text()
    )
    assert reused["review_sha256"] == original["review_sha256"]
    assert reused["verdict"] == "publish"


def test_finalize_rejects_a_component_that_keeps_the_quoted_statement(tmp_path: Path):
    history = tmp_path / "history"
    _example(history)
    run_root = tmp_path / "runs"
    response = {
        "status": "ready",
        "workspace_audit": {
            "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
            "gaps": [],
        },
        "transformations": [_transformation()],
    }
    extract(
        history,
        run_root,
        runner=_ExtractRunner(response),
        model="fixture",
        workers=1,
        resume=False,
    )
    curate(history, run_root / "extract", run_root / "curated")
    review_entries(
        history,
        run_root / "curated",
        run_root / "reviews",
        runner=_PayloadReviewRunner(_rework_review),
        model="fixture",
        workers=1,
    )

    class _KeepsTheQuote:
        def run_workspace_agent(self, **kwargs):
            return {"transformations": [_transformation()]}

    summary = finalize_entries(
        history,
        run_root / "curated",
        run_root / "reviews",
        run_root / "final",
        runner=_KeepsTheQuote(),
        model="fixture",
        workers=1,
    )
    assert summary["invalid_count"] == 1
    assert summary["finalized_count"] == 0
    review = json.loads(
        (run_root / "final" / "reviews" / "file-lifecycle-port" / "review.json").read_text()
    )
    assert review["verdict"] == "invalid"
    assert any(
        "quoted statement still present" in error
        for error in review["validation_errors"]
    )


def test_pipeline_does_one_rework_round_and_finalizes_without_re_review(
    tmp_path: Path, monkeypatch
):
    history = tmp_path / "history"
    _example(history)
    library = tmp_path / "library"
    seen: list[str] = []
    revised_title = "File lifecycle port, grounded"

    class _Runner:
        def run_workspace_agent(self, **kwargs):
            label = kwargs["task_label"]
            seen.append(label)
            transformation_id = label.split(":", 1)[1]
            if label.startswith("methodology-extract:"):
                return {
                    "status": "ready",
                    "workspace_audit": {
                        "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
                        "gaps": [],
                    },
                    "transformations": [_transformation()],
                }
            if label.startswith("methodology-review:"):
                return _rework_review(transformation_id)
            if label.startswith(("methodology-revise:", "methodology-finalize:")):
                return {
                    "status": "ready",
                    "workspace_audit": {
                        "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
                        "gaps": [],
                    },
                    "transformations": [
                        _transformation(
                            title=revised_title,
                            mapping_rules=[
                                "open handle -> open descriptor with close-on-exec and the same access mode",
                                "short read -> return the short count instead of an error",
                            ],
                            semantic_deltas=[
                                "errors arrive through errno using the target's own error numbers",
                            ],
                        )
                    ],
                }
            raise AssertionError(f"unexpected task label: {label}")

    monkeypatch.setattr(pipeline_module, "make_runner", lambda args: _Runner())
    code = main(
        [
            "--history",
            str(history),
            "--runs",
            str(tmp_path / "runs"),
            "--library",
            str(library),
            "--stage",
            "all",
            "--workers",
            "1",
        ]
    )
    assert code == 0
    assert seen == [
        "methodology-extract:ex1",
        "methodology-review:file-lifecycle-port",
        "methodology-revise:file-lifecycle-port",
        "methodology-finalize:file-lifecycle-port",
    ]
    assert sum(label.startswith("methodology-review:") for label in seen) == 1
    manifest = json.loads((library / "manifest.json").read_text())
    assert manifest["component_count"] == 1
    component = json.loads(
        (library / "components" / "file-lifecycle-port" / "component.json").read_text()
    )
    assert component["title"] == revised_title
    assert component["review"]["finalized"] is True


def test_component_without_a_finalize_verdict_is_skipped_not_blocking(
    tmp_path: Path, monkeypatch
):
    history = tmp_path / "history"
    _example(history)
    _example(history, task_id="ex2", capability="process")
    library = tmp_path / "library"

    class _Runner:
        def run_workspace_agent(self, **kwargs):
            label = kwargs["task_label"]
            kind, key = label.split(":", 1)
            if kind == "methodology-extract":
                title = "File lifecycle port" if key == "ex1" else "Process spawn port"
                return {
                    "status": "ready",
                    "workspace_audit": {
                        "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
                        "gaps": [],
                    },
                    "transformations": [_transformation(title=title)],
                }
            if kind == "methodology-review":
                if key == "process-spawn-port":
                    return _publish_review(key)
                return _rework_review(key)
            if kind == "methodology-revise":
                return {
                    "status": "ready",
                    "workspace_audit": {
                        "checked_files": ["src/win/impl.c", "src/unix/impl.c"],
                        "gaps": [],
                    },
                    "transformations": [
                        _transformation(title="File lifecycle port, grounded")
                    ],
                }
            if kind == "methodology-finalize":
                # An empty envelope is invalid: the rework verdict stands.
                return {"transformations": []}
            raise AssertionError(f"unexpected task label: {label}")

    monkeypatch.setattr(pipeline_module, "make_runner", lambda args: _Runner())
    code = main(
        [
            "--history",
            str(history),
            "--runs",
            str(tmp_path / "runs"),
            "--library",
            str(library),
            "--stage",
            "all",
            "--workers",
            "1",
        ]
    )
    assert code == 0
    manifest = json.loads((library / "manifest.json").read_text())
    assert manifest["component_count"] == 1
    assert manifest["components"][0]["bundle_id"] == "process-spawn-port"
    assert not (library / "components" / "file-lifecycle-port").exists()


def test_review_infrastructure_failure_skips_one_component_only(
    tmp_path: Path, monkeypatch, capsys
):
    history = tmp_path / "history"
    _example(history)
    _example(history, task_id="ex2", capability="process")
    library = tmp_path / "library"

    class _Runner:
        def run_workspace_agent(self, **kwargs):
            label = kwargs["task_label"]
            kind, key = label.split(":", 1)
            if kind == "methodology-extract":
                title = "File lifecycle port" if key == "ex1" else "Process spawn port"
                return {"transformations": [_transformation(title=title)]}
            if key == "file-lifecycle-port":
                raise RuntimeError("agent backend did not finish on the host plane")
            return _publish_review(key)

    monkeypatch.setattr(pipeline_module, "make_runner", lambda args: _Runner())
    code = main(
        [
            "--history",
            str(history),
            "--runs",
            str(tmp_path / "runs"),
            "--library",
            str(library),
            "--stage",
            "all",
            "--workers",
            "1",
        ]
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert report["review"]["failure_count"] == 1
    assert "file-lifecycle-port" in report["warnings"][0]
    manifest = json.loads((library / "manifest.json").read_text())
    assert manifest["component_count"] == 1
    assert manifest["components"][0]["bundle_id"] == "process-spawn-port"
    assert not (library / "components" / "file-lifecycle-port").exists()


def test_revision_task_carries_the_review_requirements(tmp_path: Path):
    history = tmp_path / "history"
    _example(history)
    example = load_corpus(history).examples[0]
    entry = {"transformation": normalize_transformation(_transformation(), example=example.metadata)}
    task = build_revision_task(
        entry,
        _rework_review("file-lifecycle-port"),
        example,
        load_prompt("revise_transformation_component.txt"),
    )
    assert "errors surface through errno instead of a Win32 error code" in task
    assert "## Component under revision" in task
    assert "## Must change" in task
    assert "The pipeline keeps the component id" in task


def test_methodology_bundle_use_prompt_points_at_paths_and_reads_on_demand(tmp_path: Path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"kind": "methodology", "components": []}), encoding="utf-8"
    )

    prompt = agent_bundle_prompt(bundle=bundle)

    assert "INDEX.md" in prompt
    assert "SELECTION.md" not in prompt
    assert "selected component paths" in prompt
    assert "open each referenced README" in prompt
    assert "component.py" not in prompt
    assert "map its rules" in prompt
    assert "/tmp/component_usage.json" in prompt


def test_submission_transport(tmp_path: Path):
    manifest = {
        "status": "ready",
        "workspace_audit": {"checked_files": ["a.c"], "gaps": []},
        "transformations": [_transformation()],
    }
    validate_methodology_extraction(manifest)
    with pytest.raises(ValueError, match="exactly one component"):
        validate_methodology_extraction(
            {
                "transformations": [
                    _transformation(),
                    _transformation(title="Second family port"),
                ]
            }
        )
    with pytest.raises(ValueError, match="exactly one component"):
        validate_methodology_extraction({"transformations": []})
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert load_submission(tmp_path, "methodology")["status"] == "ready"

    review = {
        "transformation_id": "file-lifecycle-port",
        "verdict": "publish",
        "summary": "grounded",
        "must_change": [],
    }
    validate_methodology_review(review)
    (tmp_path / "manifest.json").write_text(json.dumps(review), encoding="utf-8")
    assert load_submission(tmp_path, "methodology_review")["verdict"] == "publish"

    validate_methodology_review(_rework_review("file-lifecycle-port"))
    with pytest.raises(ValueError, match="object with"):
        validate_methodology_review(
            {**_rework_review("file-lifecycle-port"), "must_change": ["fix it"]}
        )

def test_capability_and_target_environment_are_program_owned(tmp_path: Path):
    example_meta = json.loads((_example(tmp_path) / "example.json").read_text())
    example_meta["capability"] = "threading"
    example_meta["target"] = {"os": "kylin-v10-sp3", "arch": "aarch64"}

    normalized = normalize_transformation(
        _transformation(capability="file-system/io"), example=example_meta
    )

    # A model-supplied label cannot override the migration's declared layer.
    assert normalized["capability"] == "threading"
    assert normalized["applicability"]["os"] == ["kylin-v10-sp3", "aarch64"]


def test_over_long_title_is_cut_at_a_word_boundary(tmp_path: Path):
    import re

    example_meta = json.loads((_example(tmp_path) / "example.json").read_text())
    title = " ".join(["directory traversal"] * 8)

    first = normalize_transformation(_transformation(title=title), example=example_meta)
    second = normalize_transformation(_transformation(title=title), example=example_meta)
    identifier = first["transformation_id"]

    assert identifier == second["transformation_id"]
    assert len(identifier) <= 64
    assert re.match(r"^[a-z0-9][a-z0-9._-]*$", identifier)
    # The digest suffix replaces a mid-word cut; every retained token is whole.
    stem, _, suffix = identifier.rpartition("-")
    assert re.fullmatch(r"[0-9a-f]{8}", suffix)
    assert set(stem.split("-")) == {"directory", "traversal"}
