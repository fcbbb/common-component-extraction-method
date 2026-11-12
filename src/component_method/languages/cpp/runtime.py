"""C++ execution evidence from compiler-generated function entry callbacks."""

from ..runtime import prepare_workspace, write_driver


OBSERVER = r'''
#include <stdio.h>
#include <stdlib.h>
extern "C" void __cyg_profile_func_enter(void *fn, void *) {
    const char *path = getenv("COMPONENT_TRACE");
    if (!path) return;
    FILE *out = fopen(path, "a");
    if (out) { fprintf(out, "%p\n", fn); fclose(out); }
}
extern "C" void __cyg_profile_func_exit(void *, void *) {}
'''


def prepare_smoke(backend, artifact, case, workspace):
    metadata = prepare_workspace(backend, artifact, case, workspace)
    required_ids = {case.entrypoint_id}
    for expected in case.expected_paths:
        if isinstance(expected, dict) and isinstance(expected.get("entrypoint_id"), str):
            required_ids.add(expected["entrypoint_id"])
    resolved = backend.resolve_entrypoints(artifact, required_ids)
    targets = {}
    for entry, unit in resolved.items():
        symbol = unit.metadata.get("mangled_name")
        if not symbol:
            raise ValueError(f"entrypoint has no executable linkage symbol: {entry}")
        targets[entry] = symbol
    standard = artifact.runtime.get("standard", backend.options.get("standard", "c++17"))
    if standard not in {"c++11", "c++14", "c++17", "c++20", "c++23"}:
        raise ValueError("unsupported C++ language standard")
    if set(artifact.runtime) - {"standard"}:
        raise ValueError("artifact may not supply build commands or compiler flags")
    artifact_sources = [
        f for f in artifact.files
        if f.role == "source" and f.path.endswith((".cpp", ".cc", ".cxx"))
    ]
    artifact_source_keys = {(f.path, f.content) for f in artifact_sources}
    sources = [("/artifact/", f) for f in artifact_sources]
    sources += [
        ("/smoke/", f) for f in case.files
        if f.path.endswith((".cpp", ".cc", ".cxx"))
        and (f.path, f.content) not in artifact_source_keys
    ]
    if not sources:
        raise ValueError("C++ smoke case requires source files")
    (workspace / "driver/observer.cpp").write_text(OBSERVER, encoding="utf-8")
    commands = [["g++", "-c", "/driver/observer.cpp", "-o", "/work/observer.o"]]
    objects = []
    for index, (prefix, source) in enumerate(sources):
        flags = backend.runtime_flags(source.path)
        selected_standard = artifact.runtime.get("standard") or backend.options.get("standard")
        standard_flags = ["-std=" + standard] if selected_standard or not any(f.startswith("-std=") for f in flags) else []
        target = f"/work/source-{index}.o"
        # Repository compile_commands often define NDEBUG.  Smoke cases use
        # assert() as their observable behaviour, so keep assertions enabled
        # even when the original build was a release build.
        commands.append(["g++", *flags, *standard_flags, "-UNDEBUG", "-O0", "-g", "-fno-inline",
                         "-finstrument-functions", "-fno-pie",
                         "-I/artifact", "-I/artifact/include",
                         "-I/repository", "-I/repository/include",
                         "-c", prefix + source.path, "-o", target])
        objects.append(target)
    commands.append(["g++", "-no-pie", *objects, "/work/observer.o", "-o", "/work/probe"])
    body = f'''report['toolchain']['compiler'] = command(['g++', '--version'], 'compiler-version')
report['toolchain']['target'] = command(['g++', '-dumpmachine'], 'compiler-target').strip()
commands = {commands!r}
report['toolchain']['build_commands'] = commands
for index, argv in enumerate(commands):
    command(argv, 'build-' + str(index))
symbols = command(['nm', '--defined-only', '/work/probe'], 'symbols')
addresses = {{}}
for line in symbols.splitlines():
    fields = line.split()
    if len(fields) == 3:
        addresses.setdefault(fields[2], set()).add(int(fields[0], 16))
# libclang can spell a typedef such as std::mt19937 as unsigned int on one
# target while the compiler mangles the concrete type as unsigned long.  Match
# the declared entrypoint name against demangled symbols as a fallback instead
# of trusting the extracted metadata spelling alone.
demangled = command(['nm', '-C', '--defined-only', '/work/probe'], 'symbols-demangled')
named_addresses = {{}}
for line in demangled.splitlines():
    fields = line.split(None, 2)
    if len(fields) != 3:
        continue
    address, _, name = fields
    for target_name in {targets!r}:
        if name == target_name or name.startswith(target_name + '('):
            named_addresses.setdefault(target_name, set()).add(int(address, 16))
os.environ['COMPONENT_TRACE'] = '/work/trace.log'
command(['/work/probe'], 'smoke')
trace = pathlib.Path('/work/trace.log')
observed = {{int(line, 16) for line in trace.read_text().splitlines()}} if trace.exists() else set()
targets = {targets!r}
report['executed'] = [
    name for name, symbol in targets.items()
    if (addresses.get(symbol, set()) | named_addresses.get(name, set())) & observed
]
report['trace_address_count'] = len(observed)
report['trace_addresses'] = [hex(address) for address in sorted(observed)[:64]]
report['target_addresses'] = {{
    name: [hex(address) for address in sorted(
        addresses.get(symbol, set()) | named_addresses.get(name, set())
    )]
    for name, symbol in targets.items()
}}
report['resolved_symbols'] = targets
'''
    return write_driver(workspace, metadata, body, evidence_level="compiler_function_instrumentation")
