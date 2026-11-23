"""End-to-end CLI for the transformation (methodology) pipeline.

Stages mirror the V3 design::

    scan -> extract -> curate -> review -> revise -> finalize -> publish -> verify

``review`` gives each component exactly one verdict: ``publish``, ``discard``
or ``rework``.  A ``rework`` verdict carries a concrete must-change list and
enters one repair round under ``runs/rework/r1/``.  ``finalize`` then resolves
anything still open in that round and returns the last version.  There is no
second review and no second repair round; ``publish`` accepts only an explicit
``publish`` verdict.  A discarded component is never published.

``scan`` and ``verify`` need no model.  ``extract``, ``review`` and ``revise``
call the same
repository-capable agent runtime used by the component pipeline; credentials
come from ``--model/--api-base/--api-key`` or ``MODEL_NAME/OPENAI_API_BASE/
OPENAI_API_KEY``.  ``--fixture-root`` replaces the agent with recorded JSON
responses, which is how the plumbing is tested without a model.

Nothing below the corpus format is scenario-specific: point ``--history`` at
another scenario's corpus (built by the same corpus tool from its own spec) and
the same stages apply.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .contracts import digest
from .corpus import corpus_digest, load_corpus, verify_corpus
from .curate import curate
from .finalize import finalize_entries
from .publish import publish, verify_library
from .review import review_entries
from .revise import revise_entries
from .service import extraction_input_digest, load_prompt, run_extraction

RUN_SCHEMA = "methodology-extraction-run-v1"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class FixtureRunner:
    """Replay recorded agent responses; used by tests and `--fixture-root`."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.fixture = True

    def run_workspace_agent(
        self,
        *,
        workspace_root: Path,
        task: str,
        output_dir: Path,
        task_label: str,
        agent_role: str = "extraction",
        component_workspace: Path | None = None,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "fixture_task.txt").write_text(task, encoding="utf-8")
        key = task_label.split(":", 1)[-1]
        for candidate in (
            self.root / agent_role / f"{key}.json",
            self.root / f"{key}.json",
        ):
            if candidate.is_file():
                return _read_json(candidate)
        raise FileNotFoundError(
            f"fixture response is missing for {agent_role}:{key} under {self.root}"
        )


def make_runner(args: argparse.Namespace) -> Any:
    if args.fixture_root:
        return FixtureRunner(Path(args.fixture_root))
    model = args.model or os.environ.get("MODEL_NAME")
    api_base = args.api_base or os.environ.get("OPENAI_API_BASE")
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    missing = [
        name
        for name, value in (
            ("model", model),
            ("api-base", api_base),
            ("api-key", api_key),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "extract and review need model credentials; missing: "
            + ", ".join(missing)
        )
    from ..extraction.runner import ComponentAgentRunner

    return ComponentAgentRunner(
        model=str(model),
        api_key=str(api_key),
        base_url=str(api_base),
        timeout_seconds=args.timeout,
        runtime_image=args.runtime_image,
    )


def scan(history_root: Path, run_root: Path) -> dict[str, Any]:
    report = verify_corpus(history_root)
    _write_json(run_root / "scan.json", report)
    return report


def extract(
    history_root: Path,
    run_root: Path,
    *,
    runner: Any,
    model: str,
    workers: int,
    resume: bool,
) -> dict[str, Any]:
    corpus = load_corpus(history_root)
    system_prompt = load_prompt("extract_transformation_system.txt")
    extract_root = run_root / "extract"
    manifest_path = run_root / "run_manifest.json"
    manifest = {
        "schema": RUN_SCHEMA,
        "history_root": str(corpus.root),
        "history_digest": corpus_digest(corpus.root),
        "model": model,
        "prompt_sha256": digest(system_prompt),
        "task_ids": [example.task_id for example in corpus.examples],
    }
    if manifest_path.is_file():
        existing = _read_json(manifest_path)
        for key in ("history_digest", "model", "prompt_sha256", "task_ids"):
            if existing.get(key) != manifest[key]:
                raise RuntimeError(
                    f"existing extraction run changed at {key}; use a new --runs dir"
                )
    else:
        _write_json(manifest_path, {**manifest, "status": "running"})

    def process(example: Any) -> dict[str, Any]:
        output_dir = extract_root / example.task_id
        response_path = output_dir / "extraction_response.json"
        input_digest = extraction_input_digest(example, system_prompt)
        if resume and response_path.is_file():
            recorded = (
                (output_dir / "input_digest.txt").read_text(encoding="utf-8").strip()
                if (output_dir / "input_digest.txt").is_file()
                else None
            )
            if recorded == input_digest:
                return {
                    "task_id": example.task_id,
                    "status": "reused",
                    "response": str(response_path),
                }
        response = run_extraction(
            example,
            runner=runner,
            output_dir=output_dir,
            system_prompt=system_prompt,
        )
        return {
            "task_id": example.task_id,
            "status": "ok",
            "response": str(response_path),
            "transformations": len(response.get("transformations") or []),
        }

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(process, example): example for example in corpus.examples}
        for future in as_completed(futures):
            example = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - report every example failure
                failures.append(
                    {
                        "task_id": example.task_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    results.sort(key=lambda item: item["task_id"])
    summary = {
        "schema": "methodology-extraction-summary-v1",
        "history_digest": manifest["history_digest"],
        "model": model,
        "example_count": len(corpus.examples),
        "succeeded": sum(1 for item in results if item["status"] in {"ok", "reused"}),
        "failed": len(failures),
        "results": results,
        "failures": failures,
    }
    _write_json(run_root / "extract" / "summary.json", summary)
    _write_json(
        manifest_path,
        {**manifest, "status": "completed" if not failures else "incomplete"},
    )
    return summary


def _rework_ids(review_root: Path) -> set[str]:
    """Components the first review sent to the single rework round."""
    ids: set[str] = set()
    for path in sorted(review_root.glob("*/review.json")):
        value = _read_json(path)
        if value.get("verdict") == "rework":
            ids.add(str(value.get("transformation_id") or path.parent.name))
    return ids


def _final_roots(run_root: Path) -> tuple[Path, Path]:
    """Finalized set when a rework round ran, else the first-pass set."""
    final = run_root / "final"
    if (final / "transformations.json").is_file():
        return final, final / "reviews"
    return run_root / "curated", run_root / "reviews"


def _note_review_failures(
    output: dict[str, Any], summary: dict[str, Any], label: str
) -> None:
    """A review that never finished leaves its component without a verdict.

    Publication accepts only an explicit ``publish`` verdict, so an
    infrastructure failure costs that one component, not the run.
    """
    failed = summary.get("failure_count") or 0
    if not failed:
        return
    output.setdefault("warnings", []).append(
        f"{label}: {failed} component(s) could not be reviewed "
        f"({summary.get('failures')}); they have no verdict and are not published"
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    history_root = Path(args.history).expanduser().resolve()
    run_root = Path(args.runs).expanduser().resolve()
    library = Path(args.library).expanduser().resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    stage = args.stage
    model = args.model or os.environ.get("MODEL_NAME") or "fixture"
    output: dict[str, Any] = {"stage": stage}

    if stage in {"scan", "all"}:
        output["scan"] = scan(history_root, run_root)
    if stage in {"extract", "all"}:
        runner = make_runner(args)
        output["extract"] = extract(
            history_root,
            run_root,
            runner=runner,
            model=model,
            workers=args.workers,
            resume=args.resume,
        )
        if output["extract"]["failed"]:
            # Do not curate a partial extraction wave: a failed example would
            # silently shrink the library.
            output["status"] = "incomplete"
            return output
    if stage in {"curate", "all"}:
        output["curate"] = curate(
            history_root,
            run_root / "extract",
            run_root / "curated",
        )
    if stage in {"review", "all"}:
        runner = make_runner(args)
        output["review"] = review_entries(
            history_root,
            run_root / "curated",
            run_root / "reviews",
            runner=runner,
            model=model,
            workers=args.workers,
            resume=args.resume,
        )
        _note_review_failures(output, output["review"], "review")
    if stage in {"revise", "all"}:
        curated_root, review_root = run_root / "curated", run_root / "reviews"
        if stage == "revise":
            if not (curated_root / "transformations.json").is_file():
                raise RuntimeError(
                    "revise needs a curated set; run --stage curate first "
                    f"(missing {curated_root / 'transformations.json'})"
                )
            if not review_root.is_dir():
                raise RuntimeError(
                    "revise needs review results; run --stage review first "
                    f"(missing {review_root})"
                )
        rework_ids = _rework_ids(review_root)
        if rework_ids:
            runner = make_runner(args)
            rework_root = run_root / "rework" / "r1"
            output["rework"] = revise_entries(
                history_root,
                curated_root,
                review_root,
                rework_root,
                runner=runner,
                model=model,
                workers=args.workers,
                resume=args.resume,
            )
            output["finalize"] = finalize_entries(
                history_root,
                rework_root,
                review_root,
                run_root / "final",
                runner=runner,
                model=model,
                workers=args.workers,
            )
            if output["finalize"]["invalid_count"] or output["finalize"]["failure_count"]:
                output.setdefault("warnings", []).append(
                    "finalize: "
                    f"{output['finalize']['invalid_count']} invalid and "
                    f"{output['finalize']['failure_count']} failed; "
                    "those components keep the rework verdict and are not published"
                )
    if stage in {"publish", "all"}:
        curated_root, review_root = _final_roots(run_root)
        output["publish"] = publish(
            history_root,
            curated_root,
            review_root,
            library,
            force=args.force,
        )
    if stage in {"verify", "all"}:
        output["verify"] = verify_library(library, history_root=history_root)
    output.setdefault("status", "ok")
    return output


def build_parser() -> argparse.ArgumentParser:
    project = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(
        description=(
            "Extract, curate, review and publish transformation components from "
            "the frozen migration history corpus."
        )
    )
    parser.add_argument(
        "--history",
        default=os.environ.get(
            "METHODOLOGY_HISTORY_ROOT",
            str(project / "migration_scenario_validation/v3/windows_to_kylin/history"),
        ),
        help="history corpus root (contains index.json and examples/)",
    )
    parser.add_argument(
        "--runs",
        default=None,
        help="run directory (default: <history>/runs)",
    )
    parser.add_argument(
        "--library",
        default=None,
        help="published library destination (default: <history>/../library_generated)",
    )
    parser.add_argument(
        "--stage",
        choices=(
            "scan",
            "extract",
            "curate",
            "review",
            "revise",
            "publish",
            "verify",
            "all",
        ),
        default="all",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--runtime-image", default=None)
    parser.add_argument("--timeout", type=int, default=1080)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--fixture-root",
        default=None,
        help="replay recorded agent responses instead of calling a model",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    history = Path(args.history).expanduser().resolve()
    if args.runs is None:
        args.runs = str(history / "runs")
    if args.library is None:
        args.library = str(history.parent / "library_generated")
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())