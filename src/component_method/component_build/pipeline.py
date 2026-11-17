"""Shared extraction, review, repair, and publication for artifact components."""

import json

from component_method.component_build.extraction.service import extract_components
from component_method.component_build.repair.artifacts import repair_artifact_with_agent
from component_method.component_build.validation.artifact_service import validate_artifact_component
from component_method.library_publish.artifacts import publish_artifact_library
from component_method.protocol_candidates.extraction import protocol_packet_extraction_request
from component_method.languages.cache import CachingSourceBackend
from component_method.languages.contracts import contained_path


def build_artifact_library(*, packets, repository, agent_runner, output_dir, review_runner=None,
                           max_repairs=0, executor=None, repository_id="", source_commit=""):
    """Run every language through the same source-grounded, task-blind gates."""
    output_dir.mkdir(parents=True, exist_ok=True)
    review_runner = review_runner or agent_runner
    accepted, results = [], []
    source_backends: dict[str, CachingSourceBackend] = {}
    for packet in packets:
        language = packet.get("language")
        packet_backend = None
        if isinstance(language, str):
            if language not in source_backends:
                from component_method.languages.registry import default_registry

                source_backends[language] = CachingSourceBackend(
                    default_registry().resolve({"language": language}).single()
                )
            packet_backend = source_backends[language]
        request = protocol_packet_extraction_request(repository_root=repository.resolved_root(),
                                                     output_root=output_dir / "extraction", packet=packet,
                                                     backend=packet_backend)
        drafts = extract_components(request, agent_runner=agent_runner, system_prompt="")
        for draft in drafts:
            component = draft.to_json()
            if draft.status != "draft_ready":
                continue
            if draft.artifact is None:
                raise ValueError("artifact pipeline requires component-draft-v2")
            folder = contained_path(contained_path(output_dir / "components", packet["packet_id"]), draft.component_id)
            kwargs = {"executor": executor} if executor is not None else {}
            validation = validate_artifact_component(
                component_id=draft.component_id, component=component, candidate_payload={"candidate": component},
                repository=repository, agent_runner=review_runner, output_dir=folder / "initial", **kwargs,
            )
            for attempt in range(max_repairs):
                if validation["status"] == "validated":
                    break
                review = validation.get("commonality_review", {})
                if review.get("status") != "confirmed":
                    break
                repair = repair_artifact_with_agent(
                    agent_runner, repository.resolved_root(), component,
                    {"repair_target": "artifact", "reason": validation.get("reason", "smoke validation failed"),
                     "previous_review": review, "max_changed_lines": 20}, folder / f"repair-{attempt + 1}",
                )
                if repair.get("status") != "repaired":
                    break
                component = {**component, "artifact": repair["artifact"]}
                validation = validate_artifact_component(
                    component_id=draft.component_id, component=component, candidate_payload={"candidate": component},
                    repository=repository, agent_runner=review_runner, output_dir=folder / f"revalidation-{attempt + 1}", **kwargs,
                )
            results.append({"component_id": draft.component_id, "language": draft.artifact.language,
                            "status": validation["status"]})
            if validation["status"] == "validated":
                accepted.append({"component": component, "validation": validation})
    library = publish_artifact_library(accepted, output_dir / "library", repository=repository_id,
                                       source_commit=source_commit)
    summary = {"schema": "artifact-pipeline-result-v2", "task_blind": True,
               "results": results, "published_count": len(accepted), "library": str(library)}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary
