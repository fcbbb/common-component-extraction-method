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
    resolved = backend.resolve_entrypoints(artifact)
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
    sources = [("/artifact/", f) for f in artifact.files if f.path.endswith((".cpp", ".cc", ".cxx"))]
    sources += [("/smoke/", f) for f in case.files if f.path.endswith((".cpp", ".cc", ".cxx"))]
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
        commands.append(["g++", *flags, *standard_flags, "-O0", "-g", "-fno-inline",
                         "-finstrument-functions", "-fno-pie", "-I/artifact", "-I/artifact/include",
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
os.environ['COMPONENT_TRACE'] = '/work/trace.log'
command(['/work/probe'], 'smoke')
trace = pathlib.Path('/work/trace.log')
observed = {{int(line, 16) for line in trace.read_text().splitlines()}} if trace.exists() else set()
targets = {targets!r}
report['executed'] = [name for name, symbol in targets.items() if addresses.get(symbol, set()) & observed]
report['trace_address_count'] = len(observed)
report['resolved_symbols'] = targets
'''
    return write_driver(workspace, metadata, body, evidence_level="compiler_function_instrumentation")
