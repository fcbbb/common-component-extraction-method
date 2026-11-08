"""Shared artifact integrity, source grounding, and file materialization."""

from pathlib import Path

from .contracts import Diagnostic, PublishedComponent, TaskEnvironmentSpec, contained_path


class ArtifactSupport:
    def parse_observations(self, invocation, result):
        from .runtime import parse_observations

        return parse_observations(invocation, result)

    def artifact_units(self, artifact):
        return [unit for item in artifact.files if item.role in {"source", "header"}
                for unit in self.extract_units(item.path, item.content)]

    def resolve_entrypoints(self, artifact):
        units = self.artifact_units(artifact)
        resolved = {}
        for entry in artifact.entrypoints:
            matches = [u for u in units if u.qualified_name == entry.qualified_name
                       and u.kind == entry.kind and (not entry.signature or u.signature == entry.signature)]
            definitions = [u for u in matches if u.metadata.get("is_definition", True)]
            matches = definitions or matches
            if len(matches) != 1:
                raise ValueError(f"entrypoint must identify one definition: {entry.qualified_name} ({len(matches)} matches)")
            if entry.entrypoint_id in resolved:
                raise ValueError("duplicate entrypoint; overloaded entrypoints require distinct identifiers")
            resolved[entry.entrypoint_id] = matches[0]
        return resolved

    def validate_entrypoints(self, artifact):
        try:
            if not artifact.entrypoints:
                raise ValueError("artifact has no declared entrypoints")
            self.resolve_entrypoints(artifact)
        except (ValueError, RuntimeError) as exc:
            return [Diagnostic("artifact.entrypoints", str(exc))]
        return []

    def validate_artifact(self, artifact):
        if artifact.language != self.language_id or artifact.backend_id != self.backend_id:
            return [Diagnostic("artifact.backend", "artifact belongs to another backend")]
        if not any(item.content.strip() for item in artifact.files):
            return [Diagnostic("artifact.empty", "artifact contains no source")]
        return self.artifact_diagnostics(artifact) + self.validate_entrypoints(artifact)

    def artifact_diagnostics(self, artifact):
        return [error for item in artifact.files if item.role in {"source", "header"}
                for error in self.validate_source(item.path, item.content)]

    def validate_grounding(self, artifact, repository, members):
        errors = []
        if not members:
            return [Diagnostic("grounding.members", "artifact needs source members")]
        for member in members:
            if member.language != artifact.language or member.backend_id != artifact.backend_id:
                errors.append(Diagnostic("grounding.backend", "cross-language source member"))
                continue
            path = contained_path(repository, member.file_id)
            if not path.is_file():
                errors.append(Diagnostic("grounding.file", "missing source member", file_id=member.file_id))
                continue
            units = self.extract_units(member.file_id, path.read_text())
            if member.unit_key not in {u.unit_key for u in units}:
                errors.append(Diagnostic("grounding.unit", "unknown source unit", file_id=member.file_id))
        return errors

    def materialize_component(self, artifact, destination):
        for item in artifact.files:
            path = contained_path(destination, item.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                raise ValueError(f"preserving existing artifact file: {path}")
            path.write_text(item.content, encoding="utf-8")
        instructions = self.loading_instructions(artifact)
        return PublishedComponent(artifact.language, artifact.backend_id,
                                  tuple(item.path for item in artifact.files), instructions)

    def render_loading_instructions(self, published):
        return published.loading_instructions

    def task_environment(self, task, bundle):
        return TaskEnvironmentSpec(environment=self.bundle_environment(bundle) if bundle else {})

    def validate_repository_edits(self, repository):
        errors = []
        for path in self.eligible_files(repository, "."):
            errors.extend(self.validate_source(path.relative_to(repository).as_posix(), path.read_text()))
        return errors
