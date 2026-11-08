"""Multi-file Python smoke cases observed through interpreter frame events."""

from ..runtime import prepare_workspace, write_driver


def prepare_smoke(backend, artifact, case, workspace):
    metadata = prepare_workspace(backend, artifact, case, workspace)
    resolved = backend.resolve_entrypoints(artifact)
    targets = {}
    units = backend.artifact_units(artifact)
    for name, unit in resolved.items():
        frames = [unit]
        if unit.kind == "class":
            frames = [u for u in units if u.parent_qualified_name == unit.qualified_name
                      and u.display_name in {"__init__", "__new__"}]
        targets[name] = [("/artifact/" + u.file_id, u.display_name,
                          [u.span.start_line, u.metadata.get("definition_line", u.span.start_line)]) for u in frames]
    module = case.metadata.get("module", artifact.files[0].path.removesuffix(".py").replace("/", "."))
    if not all(part.isidentifier() for part in module.split(".")):
        raise ValueError("invalid component module name")
    test_file = case.metadata.get("test_file", case.files[0].path)
    if test_file not in {f.path for f in case.files}:
        raise ValueError("smoke module is missing")
    if artifact.runtime:
        raise ValueError("Python artifacts may not supply runtime commands")
    body = f'''import importlib, importlib.util
sys.path[:0] = ['/artifact', '/repository', '/smoke']
observed = set()
targets = {targets!r}
def observe(frame, event, arg):
    if event == 'call':
        for name, frames in targets.items():
            for filename, function_name, lines in frames:
                if (frame.f_code.co_filename == filename and frame.f_code.co_name == function_name
                        and frame.f_code.co_firstlineno in lines):
                    observed.add(name)
sys.setprofile(observe)
try:
    common = importlib.import_module({module!r})
    spec = importlib.util.spec_from_file_location('component_smoke', {'/smoke/' + test_file!r})
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    result = smoke.run(common)
    if __import__('inspect').isawaitable(result):
        result = __import__('asyncio').run(result)
    if result is False:
        raise AssertionError('smoke case returned False')
finally:
    sys.setprofile(None)
report['executed'] = sorted(observed)
report['toolchain']['interpreter'] = sys.version
'''
    return write_driver(workspace, metadata, body, evidence_level="interpreter_frame_events")
