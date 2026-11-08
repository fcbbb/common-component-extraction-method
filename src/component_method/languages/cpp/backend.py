"""Clang source facts; compilation database arguments are never executed."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import shlex

from ..contracts import BackendIdentity, Diagnostic, SourceUnit, Span, TokenStream, UnitProfile
from ..artifacts import ArtifactSupport


class CppBackend(ArtifactSupport):
    language_id = "cpp"
    backend_id = "cpp@1"
    capabilities = frozenset({"source", "lexical", "structure", "ancestry", "profile", "artifact",
                              "runtime", "publication", "task"})
    extensions = frozenset({".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h"})

    def __init__(self, options=None):
        self.options = options or {}
        self.repository = None
        self.commands = {}
        self.database_digest = None

    def configure(self, options):
        return type(self)(options)

    def set_repository(self, root):
        from ..contracts import contained_path

        self.repository = root.resolve()
        self.commands = {}
        self.database_digest = None
        configured = self.options.get("compilation_database", "compile_commands.json")
        database = contained_path(root, configured)
        if database.is_file():
            self.database_digest = hashlib.sha256(database.read_bytes()).hexdigest()
            for row in json.loads(database.read_text()):
                directory = Path(row["directory"])
                if not directory.is_absolute():
                    directory = root / directory
                if not directory.resolve().is_relative_to(root.resolve()):
                    raise ValueError("compilation database directory escapes repository")
                path = (directory / row["file"]).resolve()
                if not path.is_relative_to(root.resolve()):
                    raise ValueError("compilation database source escapes repository")
                args = row.get("arguments") or shlex.split(row["command"])
                self.commands[path.relative_to(root.resolve()).as_posix()] = self._parse_flags(args[1:], directory)

    @staticmethod
    def _parse_flags(args, directory):
        result = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in {"-I", "-isystem", "-iquote", "-include"}:
                if i + 1 >= len(args):
                    raise ValueError(f"missing compilation database argument for {arg}")
                result.extend((arg, str((directory / args[i + 1]).resolve())))
                i += 2
                continue
            if arg in {"-D", "-U"}:
                if i + 1 >= len(args):
                    raise ValueError(f"missing compilation database argument for {arg}")
                result.extend((arg, args[i + 1]))
                i += 2
                continue
            if arg.startswith("-I"):
                result.extend(("-I", str((directory / arg[2:]).resolve())))
            elif arg.startswith(("-D", "-U", "-std=", "--target=")):
                result.append(arg)
            i += 1
        return result

    def identity(self):
        package = Path(__file__).parent
        digest = hashlib.sha256()
        for path in sorted(package.glob("*.py")) + sorted(package.parent.glob("*.py")):
            digest.update(path.name.encode() + b"\0" + path.read_bytes())
        return BackendIdentity(self.language_id, "1", "libclang", version("libclang"),
                               digest.hexdigest(), {
                                   "standard": self.options.get("standard", "c++17"),
                                   "compilation_database_sha256": self.database_digest,
                                   "parse_arguments": self.commands,
                                   "target": self.options.get("target", "compiler-default"),
                               })

    def scan_policy(self):
        return {"extensions": sorted(self.extensions), "excluded_directory_names":
                [".git", "build", "dist", "vendor", "third_party", "generated", "tests", "test"]}

    def eligible_files(self, root, source_subdir):
        from ..contracts import contained_path

        scan = root if source_subdir == "." else contained_path(root, source_subdir)
        if not scan.is_dir():
            raise ValueError(f"missing source root: {scan}")
        excluded = set(self.scan_policy()["excluded_directory_names"])
        for path in sorted(scan.rglob("*")):
            if path.suffix in self.extensions and path.is_file():
                if any(p in excluded for p in path.relative_to(scan).parts):
                    continue
                if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
                    raise ValueError(f"source file escapes repository: {path}")
                yield path

    def _parse(self, file_id, source, files=None, standard=None):
        from clang import cindex

        root = self.repository or Path("/component-source")
        filename = str(root / file_id)
        args = ["-x", "c++", f"-std={self.options.get('standard', 'c++17')}"]
        if self.options.get("target"):
            args.append(f"--target={self.options['target']}")
        args += self.commands.get(file_id, [])
        if standard:
            if standard not in {"c++11", "c++14", "c++17", "c++20", "c++23"}:
                raise ValueError("unsupported C++ language standard")
            args.append("-std=" + standard)
        args += ["-I", str(root), "-I", str(root / "include")]
        for pattern in ("/usr/include/c++/*", "/usr/include/*-linux-gnu/c++/*", "/usr/lib/gcc/*/*/include"):
            import glob

            for include in sorted(glob.glob(pattern)):
                if Path(include).is_dir():
                    args += ["-isystem", include]
        virtual = {str(root / key): value for key, value in (files or {}).items()}
        virtual[filename] = source
        return cindex.Index.create().parse(filename, args=args, unsaved_files=list(virtual.items()),
                                           options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)

    @staticmethod
    def _qualified(cursor):
        names = []
        while cursor is not None and cursor.kind.name != "TRANSLATION_UNIT":
            if cursor.spelling:
                names.append(cursor.spelling)
            cursor = cursor.semantic_parent
        return "::".join(reversed(names))

    def _units(self, file_id, source, files=None, standard=None):
        tree = self._parse(file_id, source, files, standard)
        kinds = {"NAMESPACE": "namespace", "FUNCTION_DECL": "function", "FUNCTION_TEMPLATE": "template",
                 "CLASS_DECL": "class", "CLASS_TEMPLATE": "template", "STRUCT_DECL": "struct",
                 "CXX_METHOD": "method", "CONSTRUCTOR": "constructor", "DESTRUCTOR": "destructor",
                 "ENUM_DECL": "enum", "UNION_DECL": "union"}
        encoded = source.encode()
        filename = str((self.repository or Path("/component-source")) / file_id)
        result = []

        def walk(cursor):
            for child in cursor.get_children():
                if child.location.file is None or child.location.file.name != filename:
                    continue
                kind = kinds.get(child.kind.name)
                if kind and (child.is_definition() or kind in {"function", "method", "constructor", "destructor"}):
                    start, end = child.extent.start, child.extent.end
                    tokens = list(child.get_tokens())
                    text = encoded[start.offset:end.offset].decode()
                    qname = self._qualified(child)
                    signature = child.type.spelling + " " + child.displayname
                    refs, calls, fields = set(), set(), set()
                    structure = []

                    def facts(node):
                        structure.append((node.kind.name, node.location.line))
                        if node.kind.name in {"DECL_REF_EXPR", "MEMBER_REF_EXPR", "TYPE_REF", "TEMPLATE_REF"}:
                            refs.add(node.spelling)
                            if node.referenced:
                                refs.add(self._qualified(node.referenced))
                        if node.kind.name == "CALL_EXPR":
                            calls.add(node.spelling)
                            if node.referenced:
                                calls.add(self._qualified(node.referenced))
                        if node.kind.name == "MEMBER_REF_EXPR":
                            fields.add(node.spelling)
                        for descendant in node.get_children():
                            facts(descendant)

                    facts(child)
                    normalized = [("ID" if t.kind.name == "IDENTIFIER" else
                                   "LIT" if t.kind.name == "LITERAL" else t.spelling, t.location.line)
                                  for t in tokens if t.kind.name != "COMMENT"]
                    owner = self._qualified(child.semantic_parent) or None
                    if child.semantic_parent.kind.name == "TRANSLATION_UNIT":
                        owner = None
                    result.append(SourceUnit(self.language_id, self.backend_id, file_id, kind, qname,
                                             child.spelling, owner, signature, Span(start.line, end.line), text, {
                                                 "tokens": normalized, "structure": structure,
                                                 "references": sorted(refs - {""}), "calls": sorted(calls - {""}),
                                                 "state": sorted(fields), "usr": child.get_usr(),
                                                 "mangled_name": child.mangled_name,
                                                 "is_definition": child.is_definition(),
                                                 "diagnostics": [str(d) for d in tree.diagnostics],
                                             }))
                walk(child)

        walk(tree.cursor)
        # Forward declarations and definitions share a semantic identity.
        unique = {}
        for unit in result:
            if unit.unit_key not in unique or unit.metadata["is_definition"]:
                unique[unit.unit_key] = unit
        return list(unique.values())

    def extract_units(self, file_id, source):
        return self._units(file_id, source)

    def artifact_units(self, artifact):
        files = {item.path: item.content for item in artifact.files}
        return [unit for item in artifact.files if Path(item.path).suffix in self.extensions
                for unit in self._units(item.path, item.content, files, artifact.runtime.get("standard"))]

    def artifact_diagnostics(self, artifact):
        files = {item.path: item.content for item in artifact.files}
        return [Diagnostic("cpp.parse", str(d), file_id=item.path)
                for item in artifact.files if Path(item.path).suffix in self.extensions
                for d in self._parse(item.path, item.content, files, artifact.runtime.get("standard")).diagnostics if d.severity >= 3]

    def runtime_flags(self, file_id):
        flags = self.commands.get(file_id)
        if flags is None:
            variants = {tuple(value) for value in self.commands.values()}
            if len(variants) > 1:
                raise ValueError("C++ artifact must preserve source paths when compilation database flags differ")
            flags = list(next(iter(variants), ()))
        if self.options.get("target") or any(flag.startswith("--target=") for flag in flags):
            raise ValueError("C++ cross-target runtime needs a matching compiler image/backend")
        mapped = []
        for flag in flags:
            path = Path(flag)
            if path.is_absolute() and self.repository and path.is_relative_to(self.repository):
                flag = "/repository/" + path.relative_to(self.repository).as_posix()
            mapped.append(flag)
        return mapped

    def _stream(self, unit, key):
        pairs = unit.metadata[key]
        return TokenStream(unit.unit_key, tuple(p[0] for p in pairs), tuple(p[1] for p in pairs),
                           unit.file_id, unit.unit_key, unit.display_name, self.language_id, self.backend_id)

    def normalized_tokens(self, unit):
        return self._stream(unit, "tokens")

    def structural_tokens(self, unit):
        return self._stream(unit, "structure")

    def file_token_streams(self, file_id, source, signal):
        units = self.extract_units(file_id, source)
        key = {"clone": "tokens", "skeleton": "structure"}[signal]
        return [self._stream(u, key) for u in units], None

    def build_profile(self, unit):
        calls = tuple(unit.metadata["calls"])
        return UnitProfile(unit.unit_key, (unit.qualified_name, unit.display_name),
                           tuple(unit.metadata["references"]), calls=calls,
                           registration_keys=tuple(c for c in calls if "register" in c.lower()),
                           state_reads=tuple(unit.metadata["state"]), related_members=calls,
                           owner_name=unit.parent_qualified_name, member_name=unit.display_name)

    def is_ancestor(self, parent, child):
        return (isinstance(parent, SourceUnit) and isinstance(child, SourceUnit)
                and parent.file_id == child.file_id and parent.unit_key != child.unit_key
                and parent.span.start_line <= child.span.start_line
                and parent.span.end_line >= child.span.end_line
                and child.qualified_name.startswith(parent.qualified_name + "::"))

    def describe_unit_id(self, unit_id):
        return {"kind": "unknown", "display_name": unit_id, "qualified_name": unit_id}

    def validate_source(self, file_id, source):
        return [Diagnostic("cpp.parse", str(d), file_id=file_id) for d in
                self._parse(file_id, source).diagnostics if d.severity >= 3]

    def loading_instructions(self, artifact):
        return "Add this component's include directory to the existing C++ build and compile its source files with the repository toolchain."

    def bundle_environment(self, bundle):
        return {"CPLUS_INCLUDE_PATH": str(bundle / "include") + ":" + str(bundle), "COMPONENT_BUNDLE": str(bundle)}

    def prepare_smoke(self, artifact, case, workspace):
        from .runtime import prepare_smoke

        return prepare_smoke(self, artifact, case, workspace)

    def agent_instructions(self, role):
        return "Use C++ headers and sources with qualified namespace and class symbols and exact overload signatures. A smoke source defines main() and asserts the selected operation. Headers may live in include/. Runtime optionally declares standard (c++11, c++14, c++17, c++20, c++23)."

    def toolchain_probes(self):
        return (("g++", "--version"), ("g++", "-dumpmachine"), ("nm", "--version"))
