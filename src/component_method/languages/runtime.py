"""Trusted driver construction and strict observation decoding."""

import json
from pathlib import Path
import secrets

from .contracts import ExecutionObservation, RuntimeInvocation, contained_path


def prepare_workspace(backend, artifact, case, workspace):
    if case.entrypoint_id not in {e.entrypoint_id for e in artifact.entrypoints}:
        raise ValueError("smoke case names an undeclared entrypoint")
    for directory, files in (("artifact", artifact.files), ("smoke", case.files)):
        for item in files:
            path = contained_path(workspace / directory, item.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item.content, encoding="utf-8")
    for name in ("driver", "build"):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    return {"case_id": case.case_id, "language": backend.language_id,
            "backend_id": backend.backend_id, "entrypoints": [e.entrypoint_id for e in artifact.entrypoints],
            "nonce": secrets.token_hex(24)}


def write_driver(workspace, metadata, body, *, evidence_level):
    prefix = '''import json, os, pathlib, resource, subprocess, sys
resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
os.chdir('/work')
report = {"executed": [], "toolchain": {}, "evidence_level": EVIDENCE_LEVEL}
def command(argv, label):
    with open('/work/' + label + '.stdout', 'wb') as out, open('/work/' + label + '.stderr', 'wb') as err:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, check=False)
    stdout = pathlib.Path('/work/' + label + '.stdout').read_bytes()[:1048576].decode(errors='replace')
    stderr = pathlib.Path('/work/' + label + '.stderr').read_bytes()[:1048576].decode(errors='replace')
    report[label] = {"argv": argv, "returncode": result.returncode, "stdout": stdout, "stderr": stderr}
    if result.returncode:
        raise RuntimeError(label + ' failed: ' + stderr[-8000:])
    return stdout
try:
'''
    suffix = '''
except BaseException as exc:
    report['error'] = type(exc).__name__ + ': ' + str(exc)
print(RESULT_MARKER + json.dumps(report, sort_keys=True))
sys.exit(1 if 'error' in report else 0)
'''
    source = ("EVIDENCE_LEVEL = " + repr(evidence_level) + "\nRESULT_MARKER = "
              + repr("COMPONENT_RESULT_" + metadata["nonce"] + ":") + "\n" + prefix
              + "\n".join("    " + line for line in body.splitlines()) + suffix)
    (workspace / "driver/run.py").write_text(source, encoding="utf-8")
    return RuntimeInvocation(("python3", "/driver/run.py"), "/work", metadata=metadata)


def parse_observations(invocation, result):
    metadata = invocation.metadata
    marker = "COMPONENT_RESULT_" + metadata["nonce"] + ":"
    records = [line[len(marker):] for line in result.stdout.splitlines() if line.startswith(marker)]
    report = json.loads(records[-1]) if len(records) == 1 else {"error": "missing or duplicate runtime observation"}
    executed = set(report.get("executed", [])) if not report.get("error") and not result.timed_out and result.returncode == 0 else set()
    return [ExecutionObservation(metadata["language"], metadata["backend_id"], metadata["case_id"], entry,
                                 entry in executed, report.get("evidence_level", "none"), report)
            for entry in metadata["entrypoints"]]
