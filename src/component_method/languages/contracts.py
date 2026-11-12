"""Versioned facts exchanged between the pipeline and language backends."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar


def stable_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def relative_path(value: str) -> str:
    """Require canonical portable paths before resolving against any workspace."""
    if (not isinstance(value, str) or not value or "\\" in value
            or ":" in value or "\x00" in value):
        raise ValueError(f"invalid relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        raise ValueError(f"invalid relative path: {value!r}")
    return value


def contained_path(root: Path, value: str) -> Path:
    relative_path(value)
    root = root.resolve()
    current = root
    for part in PurePosixPath(value).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symbolic link in artifact path: {value}")
    if not current.resolve().is_relative_to(root):
        raise ValueError(f"path escapes workspace: {value}")
    return current


class JsonRecord:
    schema: ClassVar[str]

    def to_json(self) -> dict[str, Any]:
        result = asdict(self)
        if hasattr(self, "schema"):
            result = {"schema": self.schema, **result}
        # Tuples become JSON arrays, including in nested records.
        return json.loads(json.dumps(result, ensure_ascii=False))


@dataclass(frozen=True)
class BackendIdentity(JsonRecord):
    language: str
    backend_version: str
    parser: str
    parser_version: str
    implementation_sha256: str
    toolchain: dict[str, Any] = field(default_factory=dict)

    @property
    def backend_id(self) -> str:
        return f"{self.language}@{self.backend_version}"


@dataclass(frozen=True)
class Span:
    start_line: int
    end_line: int

    def __post_init__(self) -> None:
        if (type(self.start_line) is not int or type(self.end_line) is not int
                or self.start_line < 1 or self.end_line < self.start_line):
            raise ValueError("source span must be positive and inclusive")


UNIT_KINDS = frozenset({
    "module", "namespace", "function", "class", "struct", "union", "enum",
    "method", "interface", "constructor", "destructor", "type", "constant_group",
    "template", "concept", "macro", "translation_unit",
})


@dataclass(frozen=True)
class SourceUnit(JsonRecord):
    schema: ClassVar[str] = "source-unit-v2"
    language: str
    backend_id: str
    file_id: str
    kind: str
    qualified_name: str
    display_name: str
    parent_qualified_name: str | None
    signature: str
    span: Span
    source_code: str
    metadata: dict[str, Any] = field(default_factory=dict)
    unit_key: str = field(init=False)

    def __post_init__(self) -> None:
        relative_path(self.file_id)
        if self.kind not in UNIT_KINDS:
            raise ValueError(f"unsupported source-unit kind: {self.kind}")
        if not self.language or not self.backend_id.startswith(f"{self.language}@"):
            raise ValueError("source unit language and backend identity disagree")
        identity = [self.language, self.backend_id, self.file_id, self.kind,
                    self.qualified_name, self.signature]
        object.__setattr__(self, "unit_key", stable_digest(identity))

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> SourceUnit:
        payload = dict(value)
        if payload.pop("schema", None) != cls.schema:
            raise ValueError("unsupported source-unit schema")
        expected_key = payload.pop("unit_key", None)
        payload["span"] = Span(**payload["span"])
        unit = cls(**payload)
        if expected_key != unit.unit_key:
            raise ValueError("source-unit identity does not match its fields")
        return unit


@dataclass(frozen=True)
class SourceUnitRef(JsonRecord):
    language: str
    backend_id: str
    file_id: str
    unit_key: str


@dataclass(frozen=True)
class UnitProfile(JsonRecord):
    unit_key: str
    defined_symbols: tuple[str, ...] = ()
    referenced_symbols: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()
    registration_keys: tuple[str, ...] = ()
    flow_names: tuple[str, ...] = ()
    state_reads: tuple[str, ...] = ()
    state_writes: tuple[str, ...] = ()
    related_members: tuple[str, ...] = ()
    protocol_markers: tuple[str, ...] = ()
    owner_name: str | None = None
    member_name: str = ""
    ignored_calls: tuple[str, ...] = ()
    ignored_names: tuple[str, ...] = ()
    lifecycle_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class TokenStream(JsonRecord):
    unit_key: str
    tokens: tuple[str, ...]
    rows: tuple[int, ...]
    file_id: str = ""
    unit_id: str = ""
    display_name: str = ""
    language: str = ""
    backend_id: str = ""

    def __post_init__(self) -> None:
        if len(self.tokens) != len(self.rows) or any(type(row) is not int or row < 1 for row in self.rows):
            raise ValueError("each token needs a positive source row")


@dataclass(frozen=True)
class ArtifactFile(JsonRecord):
    path: str
    content: str
    role: str = "source"

    def __post_init__(self) -> None:
        relative_path(self.path)
        if not isinstance(self.content, str):
            raise ValueError("artifact content must be text")


def validate_files(files: tuple[ArtifactFile, ...]) -> None:
    if not files:
        raise ValueError("artifact must contain files")
    paths = [item.path for item in files]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate artifact file path")
    for path in paths:
        if any(parent.as_posix() in paths for parent in PurePosixPath(path).parents):
            raise ValueError("artifact file conflicts with a parent directory")


@dataclass(frozen=True)
class Entrypoint(JsonRecord):
    kind: str
    qualified_name: str
    signature: str = ""
    purpose: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def entrypoint_id(self) -> str:
        return self.metadata.get("entrypoint_id", self.qualified_name)


@dataclass(frozen=True)
class ComponentArtifact(JsonRecord):
    schema: ClassVar[str] = "component-artifact-v2"
    language: str
    backend_id: str
    files: tuple[ArtifactFile, ...]
    entrypoints: tuple[Entrypoint, ...]
    runtime: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_files(self.files)
        if not self.language or not self.backend_id.startswith(f"{self.language}@"):
            raise ValueError("artifact language and backend identity disagree")

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> ComponentArtifact:
        payload = dict(value)
        if payload.pop("schema", None) != cls.schema:
            raise ValueError("unsupported component-artifact schema")
        payload["files"] = tuple(ArtifactFile(**item) for item in payload["files"])
        payload["entrypoints"] = tuple(Entrypoint(**item) for item in payload["entrypoints"])
        return cls(**payload)


@dataclass(frozen=True)
class SmokeCase(JsonRecord):
    schema: ClassVar[str] = "smoke-case-v2"
    case_id: str
    entrypoint_id: str
    files: tuple[ArtifactFile, ...]
    expected_paths: tuple[dict[str, Any], ...] = ()
    sources: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_files(self.files)

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> SmokeCase:
        payload = dict(value)
        if payload.pop("schema", None) != cls.schema:
            raise ValueError("unsupported smoke-case schema")
        metadata = dict(payload.get("metadata", {}))
        for key in ("language", "backend_id"):
            if key in payload:
                declared = payload.pop(key)
                if not isinstance(declared, str) or not declared:
                    raise ValueError(f"smoke case {key} must be a non-empty string")
                if key in metadata and metadata[key] != declared:
                    raise ValueError(f"conflicting smoke case {key}")
                metadata[key] = declared
        # Reviewers commonly add explanatory top-level fields such as
        # description or expected_exit_code to a smoke case.  Keep the strict
        # structural fields explicit and carry unknown fields as metadata
        # rather than rejecting an otherwise valid case.
        structural = {"case_id", "entrypoint_id", "files", "expected_paths", "sources", "metadata"}
        for key in list(payload):
            if key not in structural:
                metadata[key] = payload.pop(key)
        payload["metadata"] = metadata
        payload["files"] = tuple(ArtifactFile(**item) for item in payload["files"])
        for key in ("expected_paths", "sources"):
            payload[key] = tuple(payload.get(key, []))
        return cls(**payload)


@dataclass(frozen=True)
class Diagnostic(JsonRecord):
    code: str
    message: str
    severity: str = "error"
    file_id: str | None = None


@dataclass(frozen=True)
class RuntimeInvocation(JsonRecord):
    """A trusted backend's argv, to be executed by the isolated controller."""
    argv: tuple[str, ...]
    workdir: str
    environment: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 60
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessResult(JsonRecord):
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class ExecutionObservation(JsonRecord):
    language: str
    backend_id: str
    case_id: str
    entrypoint_id: str
    executed: bool
    evidence_level: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublishedComponent(JsonRecord):
    language: str
    backend_id: str
    files: tuple[str, ...]
    loading_instructions: str


@dataclass(frozen=True)
class TaskEnvironmentSpec(JsonRecord):
    environment: dict[str, str] = field(default_factory=dict)
    mounts: tuple[dict[str, Any], ...] = ()
