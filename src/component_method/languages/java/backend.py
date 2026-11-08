"""Java source facts from a maintained parser, without invoking host tools."""

import hashlib
from importlib.metadata import version
from pathlib import Path

from ..artifacts import ArtifactSupport
from ..contracts import BackendIdentity, Diagnostic, SourceUnit, Span, TokenStream, UnitProfile


class JavaBackend(ArtifactSupport):
    language_id = "java"
    backend_id = "java@1"
    capabilities = frozenset({"source", "lexical", "structure", "ancestry", "profile", "artifact",
                              "runtime", "publication", "task"})

    def identity(self):
        digest = hashlib.sha256()
        for path in sorted(Path(__file__).parent.glob("*.py")) + sorted(Path(__file__).parent.parent.glob("*.py")):
            digest.update(path.name.encode() + b"\0" + path.read_bytes())
        return BackendIdentity("java", "1", "tree-sitter-java", version("tree-sitter-java"),
                               digest.hexdigest(), {"tree_sitter": version("tree-sitter")})

    def scan_policy(self):
        return {"extensions": [".java"], "excluded_directory_names":
                [".git", "build", "target", "vendor", "generated", "test", "tests"]}

    def eligible_files(self, root, source_subdir):
        from ..contracts import contained_path

        scan = root if source_subdir == "." else contained_path(root, source_subdir)
        if not scan.is_dir():
            raise ValueError("missing Java source root")
        for path in sorted(scan.rglob("*.java")):
            if any(p in self.scan_policy()["excluded_directory_names"] for p in path.relative_to(scan).parts):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("source file escapes repository")
            yield path

    @staticmethod
    def _parse(source):
        from tree_sitter import Language, Parser
        import tree_sitter_java

        return Parser(Language(tree_sitter_java.language())).parse(source.encode())

    def extract_units(self, file_id, source):
        tree = self._parse(source)
        encoded = source.encode()
        text = lambda node: encoded[node.start_byte:node.end_byte].decode() if node else ""
        package = ""
        for node in tree.root_node.children:
            if node.type == "package_declaration":
                package = next((text(c) for c in node.named_children if c.type in {"identifier", "scoped_identifier"}), "")
        kinds = {"class_declaration": "class", "interface_declaration": "interface",
                 "enum_declaration": "enum", "record_declaration": "class",
                 "method_declaration": "method", "constructor_declaration": "constructor"}
        result = []

        def walk(node, owner):
            next_owner = owner
            if node.type in kinds:
                name = text(node.child_by_field_name("name"))
                qualified = ".".join(p for p in (owner, name) if p)
                parameters = node.child_by_field_name("parameters")
                types = [text(p.child_by_field_name("type")) for p in parameters.named_children] if parameters else []
                signature = name + "(" + ", ".join(types) + ")"
                refs, calls, fields, tokens, structure = set(), set(), set(), [], []

                def facts(child):
                    if child.is_named:
                        structure.append((child.type, child.start_point.row + 1))
                    if child.type == "identifier":
                        refs.add(text(child))
                    if child.type == "method_invocation":
                        calls.add(text(child.child_by_field_name("name")))
                    if child.type == "field_access":
                        fields.add(text(child.child_by_field_name("field")))
                    if not child.children and child.type not in {"line_comment", "block_comment"}:
                        token = "ID" if child.type in {"identifier", "type_identifier"} else (
                            "LIT" if "literal" in child.type else text(child))
                        tokens.append((token, child.start_point.row + 1))
                    for descendant in child.children:
                        facts(descendant)

                facts(node)
                result.append(SourceUnit("java", self.backend_id, file_id, kinds[node.type], qualified,
                                         name, owner or None, signature,
                                         Span(node.start_point.row + 1, node.end_point.row + 1), text(node), {
                                             "tokens": tokens, "structure": structure, "references": sorted(refs),
                                             "calls": sorted(calls), "state": sorted(fields),
                                             "parameter_types": types, "class_name": owner,
                                             "parse_errors": tree.root_node.has_error,
                                         }))
                next_owner = qualified
            for child in node.children:
                walk(child, next_owner)

        walk(tree.root_node, package)
        return result

    def _stream(self, unit, key):
        pairs = unit.metadata[key]
        return TokenStream(unit.unit_key, tuple(p[0] for p in pairs), tuple(p[1] for p in pairs),
                           unit.file_id, unit.unit_key, unit.display_name, self.language_id, self.backend_id)

    def normalized_tokens(self, unit):
        return self._stream(unit, "tokens")

    def structural_tokens(self, unit):
        return self._stream(unit, "structure")

    def file_token_streams(self, file_id, source, signal):
        return [self._stream(u, {"clone": "tokens", "skeleton": "structure"}[signal])
                for u in self.extract_units(file_id, source)], None

    def build_profile(self, unit):
        calls = tuple(unit.metadata["calls"])
        return UnitProfile(unit.unit_key, (unit.qualified_name, unit.display_name),
                           tuple(unit.metadata["references"]), calls=calls,
                           registration_keys=tuple(c for c in calls if c.startswith("register")),
                           state_reads=tuple(unit.metadata["state"]), related_members=calls,
                           owner_name=unit.parent_qualified_name, member_name=unit.display_name)

    def is_ancestor(self, parent, child):
        return (isinstance(parent, SourceUnit) and isinstance(child, SourceUnit)
                and parent.file_id == child.file_id and parent.unit_key != child.unit_key
                and child.qualified_name.startswith(parent.qualified_name + ".")
                and parent.span.start_line <= child.span.start_line
                and parent.span.end_line >= child.span.end_line)

    def describe_unit_id(self, unit_id):
        return {"kind": "unknown", "display_name": unit_id, "qualified_name": unit_id}

    def validate_source(self, file_id, source):
        if self._parse(source).root_node.has_error:
            return [Diagnostic("java.parse", "Java parser reported a syntax error", file_id=file_id)]
        return []

    def loading_instructions(self, artifact):
        return "Compile the component sources with the repository JDK; add the resulting classes to its existing classpath."

    def bundle_environment(self, bundle):
        return {"CLASSPATH": str(bundle), "COMPONENT_BUNDLE": str(bundle)}

    def prepare_smoke(self, artifact, case, workspace):
        from .runtime import prepare_smoke

        return prepare_smoke(self, artifact, case, workspace)

    def agent_instructions(self, role):
        return "Use .java source files in package directories. Methods have fully qualified class and method names. Smoke code defines public static void main(String[] args); metadata.main_class names that class (default Smoke). Preserve exact parameter signatures."

    def toolchain_probes(self):
        return (("javac", "-version"), ("java", "--version"))
