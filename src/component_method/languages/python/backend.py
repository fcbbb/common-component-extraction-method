"""Source capability adapter preserving the frozen Python extraction order."""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import sys
import textwrap
from typing import Iterable

from component_method.languages.contracts import (
    BackendIdentity, Diagnostic, SourceUnit, Span, TokenStream, stable_digest,
)
from .discovery import extract_unit_sources
from .units import CONTAINER_TYPES
from ..artifacts import ArtifactSupport


EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "site-packages", "node_modules",
    "build", "dist", "vendor", "third_party", "generated", "test", "tests",
}


class PythonBackend(ArtifactSupport):
    language_id = "python"
    backend_id = "python@1"
    capabilities = frozenset({"source", "lexical", "structure", "ancestry", "profile", "artifact",
                              "runtime", "publication", "task"})

    def build_profile(self, unit: SourceUnit):
        from .protocol import profile_unit

        return profile_unit(unit)

    def identity(self) -> BackendIdentity:
        package = Path(__file__).parent
        sources = sorted(package.glob("*.py"))
        sources += sorted(package.parent.glob("*.py"))
        digest = hashlib.sha256()
        for path in sources:
            digest.update(path.relative_to(package.parents[1]).as_posix().encode() + b"\0")
            digest.update(path.read_bytes())
        return BackendIdentity("python", "1", "stdlib-ast",
                               f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                               digest.hexdigest())

    def eligible_files(self, root: Path, source_subdir: str) -> Iterable[Path]:
        scan_root = root / source_subdir
        if not scan_root.resolve().is_relative_to(root.resolve()):
            raise ValueError("source root escapes repository")
        if not scan_root.is_dir():
            raise RuntimeError(f"source root is missing: {scan_root}")
        for current, dirs, names in os.walk(scan_root, topdown=True, followlinks=False):
            dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS)
            for name in sorted(names):
                if name.endswith(".py") and not name.startswith("test_") and not name.endswith("_test.py"):
                    path = Path(current) / name
                    if not path.resolve().is_relative_to(root.resolve()):
                        raise ValueError(f"source file escapes repository: {path}")
                    yield path

    def scan_policy(self) -> dict:
        return {
            "extensions": [".py"], "excluded_directory_names": sorted(EXCLUDED_DIRS),
            "excluded_filenames": ["test_*.py", "*_test.py"], "max_file_bytes": None,
            "ordering": "sorted parent files before sorted child directories",
        }

    def extract_legacy_units(self, file_id: str, source: str) -> list[dict[str, str]]:
        return extract_unit_sources([{"file_id": file_id, "source_code": source}])

    def extract_units(self, file_id: str, source: str) -> list[SourceUnit]:
        records = self.extract_legacy_units(file_id, source)
        nodes: dict[str, list[ast.AST]] = {}
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in tree.body:
                if not isinstance(node, CONTAINER_TYPES):
                    continue
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                nodes.setdefault(f"{kind}:{node.name}", []).append(node)
                if isinstance(node, ast.ClassDef):
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            nodes.setdefault(f"method:{node.name}.{child.name}", []).append(child)
        result = []
        occurrences: dict[str, int] = {}
        for record in records:
            unit_id = record["unit_id"]
            kind, _, name = unit_id.partition(":")
            name = name or "<module>"
            occurrence = occurrences.get(unit_id, 0)
            occurrences[unit_id] = occurrence + 1
            matching = nodes.get(unit_id, [])
            node = matching[occurrence] if matching else None
            start, end, signature = 1, max(1, len(source.splitlines())), ""
            if node is not None:
                start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
                end = node.end_lineno or node.lineno
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    signature = f"{node.name}({ast.unparse(node.args)})"
                    if node.returns is not None:
                        signature += f" -> {ast.unparse(node.returns)}"
                else:
                    signature = f"{node.name}({', '.join(ast.unparse(base) for base in node.bases)})"
            # Python permits repeated definitions with identical signatures.
            if len(matching) > 1:
                signature += f" [definition {occurrence + 1}]"
            metadata = {"legacy_unit_id": unit_id}
            if node is not None:
                metadata["definition_line"] = node.lineno
            if kind == "module" and tree is not None:
                covered = set()
                for item in tree.body:
                    if isinstance(item, CONTAINER_TYPES):
                        first = min([item.lineno, *[d.lineno for d in item.decorator_list]])
                        covered.update(range(first, (item.end_lineno or item.lineno) + 1))
                metadata["source_rows"] = [
                    row for row in range(1, len(source.splitlines()) + 1) if row not in covered
                ]
            result.append(SourceUnit(
                "python", self.backend_id, file_id, kind, name, name.rsplit(".", 1)[-1],
                name.rsplit(".", 1)[0] if kind == "method" else None,
                signature, Span(start, end), record["source_code"],
                metadata,
            ))
        return result

    def describe_unit_id(self, unit_id: str) -> dict:
        kind, _, name = unit_id.partition(":")
        return {
            "kind": kind, "qualified_name": name or "<module>",
            "display_name": name or "module",
            "parent_qualified_name": name.rpartition(".")[0] if kind == "method" else None,
        }

    def is_ancestor(self, parent: SourceUnit | dict, child: SourceUnit | dict) -> bool:
        def scope(value):
            if isinstance(value, SourceUnit):
                return value.file_id, value.language, value.backend_id, {
                    "kind": value.kind, "qualified_name": value.qualified_name,
                    "parent_qualified_name": value.parent_qualified_name,
                }
            return (value["file_id"], value.get("language", self.language_id),
                    value.get("backend_id", self.backend_id), self.describe_unit_id(value["unit_id"]))

        parent_file, parent_language, parent_backend, first = scope(parent)
        child_file, child_language, child_backend, second = scope(child)
        return (parent_file == child_file and parent_language == child_language
                and parent_backend == child_backend == self.backend_id
                and first["kind"] == "class" and second["kind"] == "method"
                and second["parent_qualified_name"] == first["qualified_name"])

    def file_token_streams(self, file_id: str, source: str,
                           signal: str) -> tuple[list[TokenStream], str | None]:
        from .lexical import _unit_streams
        from .structure import _skeleton_streams

        if signal == "clone":
            streams, _ = _unit_streams(file_id, source)
            error = None
        elif signal == "skeleton":
            streams, error = _skeleton_streams(file_id, source)
        else:
            raise ValueError(f"unsupported token signal: {signal}")
        units = {unit.metadata["legacy_unit_id"]: unit for unit in self.extract_units(file_id, source)}
        result = []
        for stream in streams:
            unit = units.get(stream.unit_id)
            info = self.describe_unit_id(stream.unit_id)
            result.append(TokenStream(
                unit.unit_key if unit else stable_digest([
                    self.language_id, self.backend_id, file_id, info["kind"], info["qualified_name"], ""
                ]),
                tuple(stream.tokens), tuple(stream.rows), file_id, stream.unit_id,
                info["display_name"], self.language_id, self.backend_id,
            ))
        return result, error

    def normalized_tokens(self, unit: SourceUnit) -> TokenStream:
        from .lexical import _normalized_tokens

        pairs = _normalized_tokens(textwrap.dedent(unit.source_code))
        rows = unit.metadata.get("source_rows")
        return TokenStream(
            unit.unit_key, tuple(token for token, _ in pairs),
            tuple(rows[row - 1] if rows else row + unit.span.start_line - 1 for _, row in pairs),
            unit.file_id, unit.metadata["legacy_unit_id"], unit.qualified_name,
            self.language_id, self.backend_id,
        )

    def structural_tokens(self, unit: SourceUnit) -> TokenStream:
        from .structure import _skeleton_streams

        streams, _ = _skeleton_streams(unit.file_id, textwrap.dedent(unit.source_code))
        wanted = unit.metadata["legacy_unit_id"]
        if unit.kind == "method":
            wanted = f"function:{unit.display_name}"
        stream = next((stream for stream in streams if stream.unit_id == wanted), None)
        rows = unit.metadata.get("source_rows")
        return TokenStream(
            unit.unit_key, tuple(stream.tokens) if stream else (),
            tuple(rows[row - 1] if rows else row + unit.span.start_line - 1
                  for row in stream.rows) if stream else (),
            unit.file_id, unit.metadata["legacy_unit_id"], unit.qualified_name,
            self.language_id, self.backend_id,
        )

    def validate_source(self, file_id: str, source: str) -> list[Diagnostic]:
        try:
            compile(source, file_id, "exec")
        except (SyntaxError, ValueError) as exc:
            return [Diagnostic("python.syntax", str(exc), file_id=file_id)]
        return []

    def loading_instructions(self, artifact):
        return "Add the component root to the existing Python import path and import the declared modules and symbols."

    def bundle_environment(self, bundle):
        return {"PYTHONPATH": str(bundle), "COMPONENT_BUNDLE": str(bundle)}

    def prepare_smoke(self, artifact, case, workspace):
        from .artifact_runtime import prepare_smoke

        return prepare_smoke(self, artifact, case, workspace)

    def agent_instructions(self, role):
        return "Python files use .py. Smoke files define run(common); metadata.module names the component module. Entrypoint signatures must match extracted source units."

    def toolchain_probes(self):
        return (("python3", "--version"),)
