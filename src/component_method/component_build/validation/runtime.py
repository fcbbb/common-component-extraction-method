"""Compile, import, and invoke a temporary component reference in a subprocess."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import hashlib
from pathlib import Path
from typing import Any

from ..workspace import COMPONENT_DIRECTORY, TASK_RUNTIME_ACTIVATION, prepare_component_mount


def _defined_top_level(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _smoke_calls_entrypoints(
    source: str,
    entrypoint_names: set[str],
    class_entrypoints: set[str] | None = None,
) -> tuple[bool, list[str]]:
    tree = ast.parse(source)
    run_function = next(
        (
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "run"
        ),
        None,
    )
    if run_function is None or not run_function.args.args:
        return False, []
    parameter = run_function.args.args[0].arg
    aliases: dict[str, str] = {}
    for node in ast.walk(run_function):
        value = getattr(node, "value", None)
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == parameter
            and value.attr in entrypoint_names
        ):
            targets = (
                node.targets if isinstance(node, ast.Assign)
                else [node.target] if isinstance(node, ast.AnnAssign)
                else []
            )
            for target in targets:
                if isinstance(target, ast.Name):
                    aliases[target.id] = value.attr

    calls: set[str] = set()
    subclasses: dict[str, set[str]] = {}
    for node in ast.walk(run_function):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = set()
        for base in node.bases:
            if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id == parameter:
                bases.add(base.attr)
            elif isinstance(base, ast.Name) and base.id in aliases:
                bases.add(aliases[base.id])
        supported = bases & (class_entrypoints or set())
        if supported:
            subclasses[node.name] = supported
    for node in ast.walk(run_function):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == parameter
        ):
            calls.add(node.func.attr)
        elif isinstance(node.func, ast.Name) and node.func.id in aliases:
            calls.add(aliases[node.func.id])
        elif isinstance(node.func, ast.Name) and node.func.id in subclasses:
            calls.update(subclasses[node.func.id])
    return entrypoint_names <= calls, sorted(calls)


def _execution_observer_source() -> str:
    """Observe original Python callables without replacing functions or class identities."""
    return '''
import ast
import functools

observations = {}
watched_codes = {}
class_entries = {}
seen_frames = set()
_observing = False

def _literal_value(value, seen=None):
    if type(value) in (str, bytes, int, float, complex, bool, type(None)):
        return {"type": type(value).__name__, "literal": repr(value)}
    if type(value) in (list, tuple, dict, set):
        seen = set() if seen is None else seen
        if id(value) in seen:
            return None
        seen.add(id(value))
        children = [item for pair in value.items() for item in pair] if type(value) is dict else value
        safe = all(_literal_value(item, seen) is not None for item in children)
        seen.remove(id(value))
        if safe:
            return {"type": type(value).__name__, "literal": repr(value)}
    return None

def _observation(entrypoint, path, arguments, positional):
    if not _observing:
        return None
    return {"entrypoint": entrypoint, "path": path,
            "arguments": {name: encoded for name, value in arguments.items()
                          if (encoded := _literal_value(value)) is not None},
            "positional": [_literal_value(value) for value in positional]}

def _commit(record):
    if _observing and record is not None:
        observations[json.dumps(record, sort_keys=True)] = record

def _bound_values(function, args, kwargs, receiver=False):
    try:
        signature = inspect.signature(function)
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        arguments = dict(bound.arguments)
        positional = []
        positional_names = []
        for parameter in signature.parameters.values():
            if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
                positional_names.append(parameter.name)
                positional.append(arguments[parameter.name])
            elif parameter.kind == inspect.Parameter.VAR_POSITIONAL:
                positional.extend(arguments.pop(parameter.name, ()))
            elif parameter.kind == inspect.Parameter.VAR_KEYWORD:
                arguments.update(arguments.pop(parameter.name, {}))
        if receiver:
            if positional:
                positional.pop(0)
            if positional_names:
                arguments.pop(positional_names[0], None)
        return arguments, positional
    except (TypeError, ValueError):
        return dict(kwargs), list(args[1:] if receiver else args)

def _watch(function, entrypoint, path, receiver=False):
    if inspect.isfunction(function):
        watched_codes.setdefault(function.__code__, []).append((function, entrypoint, path, receiver))

for name in expected:
    value = getattr(common, name)
    if inspect.isclass(value):
        class_entries[name] = value
        for method_name in {key for base in value.__mro__ for key in vars(base)}:
            member = inspect.getattr_static(value, method_name)
            receiver = not isinstance(member, staticmethod)
            if isinstance(member, (staticmethod, classmethod)):
                member = member.__func__
            _watch(member, name, name + "." + method_name, receiver)
    else:
        _watch(value, name, name)

def _same_function_frame(function, frame):
    if function.__globals__ is not frame.f_globals:
        return False
    try:
        return all(name in frame.f_locals and frame.f_locals[name] is cell.cell_contents
                   for name, cell in zip(function.__code__.co_freevars, function.__closure__ or ()))
    except ValueError:
        return False

def _profile(frame, event, arg):
    if event != "call" or frame.f_code not in watched_codes or frame in seen_frames:
        return
    # Retain the frame itself: resumed coroutines/generators share it, and IDs may be reused.
    seen_frames.add(frame)
    code = frame.f_code
    args = [frame.f_locals[name] for name in code.co_varnames[:code.co_argcount]]
    kwargs = {name: frame.f_locals[name] for name in
              code.co_varnames[code.co_argcount:code.co_argcount + code.co_kwonlyargcount]}
    extra = code.co_argcount + code.co_kwonlyargcount
    if code.co_flags & inspect.CO_VARARGS:
        args.extend(frame.f_locals.get(code.co_varnames[extra], ()))
        extra += 1
    if code.co_flags & inspect.CO_VARKEYWORDS:
        kwargs.update(frame.f_locals.get(code.co_varnames[extra], {}))
    matches = []
    for function, entrypoint, path, receiver in watched_codes[code]:
        if not _same_function_frame(function, frame):
            continue
        if receiver:
            instance = args[0] if args else None
            cls = class_entries[entrypoint]
            if not (isinstance(instance, cls) or (inspect.isclass(instance) and issubclass(instance, cls))):
                continue
        matches.append((function, entrypoint, path, receiver))
    # Shared code is insufficient evidence when distinct function objects remain indistinguishable.
    if len({id(function) for function, _, _, _ in matches}) != 1:
        return
    for function, entrypoint, path, receiver in matches:
        arguments, positional = _bound_values(function, args, kwargs, receiver)
        _commit(_observation(entrypoint, path, arguments, positional))

def _observe_class(function):
    if not inspect.isclass(function):
        return function
    supported = [name for name, cls in class_entries.items() if issubclass(function, cls)]
    if not supported:
        return function
    @functools.wraps(function)
    def construct(*args, **kwargs):
        arguments, positional = _bound_values(function, args, kwargs)
        records = [_observation(name, name, arguments, positional) for name in supported]
        result = function(*args, **kwargs)
        for record in records:
            _commit(record)
        return result
    return construct

class ObserveConstructors(ast.NodeTransformer):
    def visit_Call(self, node):
        self.generic_visit(node)
        # Normal functions remain unchanged, preserving frame-sensitive builtins.
        node.func = ast.copy_location(ast.Call(func=ast.Name(id="_observe_class", ctx=ast.Load()),
                                              args=[node.func], keywords=[]), node.func)
        return node

smoke_path = pathlib.Path(temp_dir) / "test.py"
tree = ast.fix_missing_locations(ObserveConstructors().visit(ast.parse(smoke_path.read_text())))
smoke_namespace = {"__name__": "community_component_smoke", "__file__": str(smoke_path),
                   "_observe_class": _observe_class}
exec(compile(tree, str(smoke_path), "exec"), smoke_namespace)
runner = smoke_namespace.get("run")
'''.strip()


def _runner_source(repo_root: Path, temp_dir: Path, entrypoints: list[str]) -> str:
    repo_literal = json.dumps(str(repo_root.resolve()))
    temp_literal = json.dumps(str(temp_dir.resolve()))
    names_literal = json.dumps(entrypoints)
    return f"""
import importlib.util
import asyncio
import inspect
import json
import pathlib
import socket
import sys

def _deny_network(*args, **kwargs):
    raise RuntimeError("network access is disabled in the component smoke runner")

socket.create_connection = _deny_network
socket.socket.connect = _deny_network
socket.socket.connect_ex = _deny_network

repo_root = {repo_literal}
temp_dir = {temp_literal}
expected = {names_literal}
sys.path.insert(0, temp_dir)
sys.path.insert(1, repo_root)
print("COMPONENT_RUNTIME_ENVIRONMENT=" + json.dumps({{"executable": sys.executable, "prefix": sys.prefix, "python_version": sys.version}}))

import common
for name in expected:
    value = getattr(common, name, None)
    if not callable(value):
        raise TypeError("entrypoint is absent or not callable: " + name)
print("COMPONENT_IMPORT_OK")

{_execution_observer_source()}
if not callable(runner):
    raise TypeError("test.py must define callable run(common)")
_observing = True
sys.setprofile(_profile)
try:
    result = runner(common)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
finally:
    sys.setprofile(None)
    _observing = False
    seen_frames.clear()
    print("COMPONENT_EXECUTION_TRACE=" + json.dumps(list(observations.values()), ensure_ascii=False))
if result is False:
    raise AssertionError("smoke driver returned False")
print("COMPONENT_CALL_OK")
print(json.dumps({{"status": "ok", "result_type": type(result).__name__}}, ensure_ascii=False))
""".strip()


def _docker_smoke_command(
    runtime_image: str,
    output_dir: Path,
    timeout_seconds: int,
    repo_root: Path,
    runtime_activation: str | None = None,
) -> list[str]:
    validation_mount = (
        f"type=bind,src={output_dir.resolve()},dst={COMPONENT_DIRECTORY},readonly"
    )
    prepare_component_mount(repo_root)
    workspace_mount = f"type=bind,src={repo_root.resolve()},dst=/testbed,readonly"
    hidden_pristine = output_dir / "hidden_pristine_repo"
    hidden_pristine.mkdir(exist_ok=True)
    pristine_mount = (
        f"type=bind,src={hidden_pristine.resolve()},dst=/root/my_repo,readonly"
    )
    container_command = (
        (runtime_activation or TASK_RUNTIME_ACTIVATION) + " && "
        f"timeout --signal=KILL {int(timeout_seconds)}s "
        f"python -I {COMPONENT_DIRECTORY}/invoke.py"
    )
    return [
        "docker", "run", "--rm", "--pull=never", "--entrypoint", "/bin/bash",
        "--network", "none",
        # Keep host inputs read-only, but leave the disposable container layer
        # writable for framework caches and other normal runtime state.
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m,mode=1777",
        "--security-opt", "no-new-privileges",
        "--cap-drop", "ALL",
        "--pids-limit", "64",
        "--mount", validation_mount,
        "--mount", workspace_mount,
        "--mount", pristine_mount,
        "--workdir", "/testbed",
        "--env", "HOME=/tmp",
        "--env", "TMPDIR=/tmp",
        "--env", "TEMP=/tmp",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "PYTHONNOUSERSITE=1",
        runtime_image,
        "-lc", container_command,
    ]


def validate_callable_artifact(
    *,
    component_id: str,
    library_content: str,
    smoke_content: str,
    entrypoints: list[dict[str, Any]],
    repo_root: Path,
    output_dir: Path,
    timeout_seconds: int = 20,
    runtime_image: str | None = None,
    runtime_activation: str | None = None,
    container_manager: Any = None,
    container: Any = None,
    container_workdir: str = "/testbed",
    grounding_members: list[str] | None = None,
    all_sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Check grounded source, syntax, public callables, and an actual smoke call."""
    output_dir.mkdir(parents=True, exist_ok=True)
    library_path = output_dir / "common.py"
    smoke_path = output_dir / "test.py"
    library_path.write_text(library_content, encoding="utf-8")
    smoke_path.write_text(smoke_content, encoding="utf-8")

    entrypoint_names = [
        item.get("name") for item in entrypoints
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item.get("kind") in {"function", "class"}
    ]
    entrypoints_valid = (
        bool(entrypoints)
        and len(entrypoint_names) == len(entrypoints)
        and len(set(entrypoint_names)) == len(entrypoint_names)
    )
    result: dict[str, Any] = {
        "component_id": component_id,
        "status": "failed",
        "compile": {"ok": False},
        "import": {"ok": False},
        "call": {"ok": False},
        "entrypoints": entrypoint_names,
        "runtime": (
            {"kind": "docker_image", "image": runtime_image, "workdir": "/testbed"}
            if runtime_image
            else (
                {"kind": "task_container", "workdir": container_workdir}
                if container_manager is not None and container is not None
                else {"kind": "host_python", "executable": sys.executable}
            )
        ),
    }
    if not library_content.strip() or not smoke_content.strip() or not entrypoints_valid:
        result["status"] = "invalid_schema"
        result["reason"] = (
            "library, smoke test, and unique function/class entrypoints are required"
        )
        return result

    try:
        compile(library_content, str(library_path), "exec")
        compile(smoke_content, str(smoke_path), "exec")
        defined = _defined_top_level(library_content)
        ast.parse(smoke_content)
    except (SyntaxError, ValueError) as exc:
        result["status"] = "compile_failed"
        result["reason"] = f"{type(exc).__name__}: {exc}"
        result["compile"] = {"ok": False, "error": str(exc)}
        return result
    result["compile"] = {"ok": True}

    missing = sorted(set(entrypoint_names) - defined)
    if missing:
        result["status"] = "entrypoint_missing"
        result["reason"] = "entrypoints are not defined at module scope: " + ", ".join(missing)
        return result
    if grounding_members and all_sources:
        try:
            from ..context.component_context import (
                _validate_common_reference,
            )
            grounding = _validate_common_reference(
                {"library": {"content": library_content}},
                {"cluster_id": component_id, "members": grounding_members},
                all_sources,
                output_dir / "grounding",
                allow_repository_imports=True,
            )
        except Exception as exc:
            grounding = {
                "status": "grounding_check_failed",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        result["grounding"] = grounding
        if grounding.get("status") not in {"ok"}:
            result["status"] = grounding.get("status", "grounding_check_failed")
            result["reason"] = grounding.get("reason", "local source grounding failed")
            return result

    runner_path = output_dir / "invoke.py"
    use_task_container = container_manager is not None and container is not None
    runner_repo_root = Path("/testbed") if runtime_image or use_task_container else repo_root
    if runtime_image:
        runner_temp_dir = Path(COMPONENT_DIRECTORY)
    elif use_task_container:
        safe_component_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", component_id)[:80]
        case_key = hashlib.sha256(str(output_dir.resolve()).encode()).hexdigest()[:12]
        runner_temp_dir = Path(container_workdir) / ".components" / f"{safe_component_id}-{case_key}"
    else:
        runner_temp_dir = output_dir
    runner_path.write_text(
        _runner_source(runner_repo_root, runner_temp_dir, entrypoint_names),
        encoding="utf-8",
    )
    safe_home = output_dir / "home"
    safe_tmp = output_dir / "tmp"
    safe_home.mkdir(exist_ok=True)
    safe_tmp.mkdir(exist_ok=True)
    env = {
        "HOME": str(safe_home),
        "TMPDIR": str(safe_tmp),
        "TEMP": str(safe_tmp),
        "TMP": str(safe_tmp),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
    }
    try:
        if use_task_container:
            payload_dir = output_dir / "container_payload"
            payload_dir.mkdir(parents=True, exist_ok=True)
            for name in ("common.py", "test.py", "invoke.py"):
                (payload_dir / name).write_bytes((output_dir / name).read_bytes())
            container_temp_dir = str(runner_temp_dir)
            container_manager.copy_to_container(
                container,
                payload_dir,
                container_temp_dir,
            )
            command = (
                f"timeout --signal=KILL {int(timeout_seconds)}s "
                f"python -I {container_temp_dir}/invoke.py"
            )
            exit_code, output = container_manager.exec_command(
                container,
                command,
                timeout=timeout_seconds + 10,
                workdir=container_workdir,
                log_file=output_dir / "container_runtime.log",
            )
            completed = subprocess.CompletedProcess(
                args=command,
                returncode=exit_code,
                stdout=output,
                stderr="",
            )
        else:
            completed = subprocess.run(
                _docker_smoke_command(
                    runtime_image,
                    output_dir,
                    timeout_seconds,
                    repo_root,
                    runtime_activation,
                )
                if runtime_image
                else [sys.executable, "-I", str(runner_path)],
                cwd=Path.cwd() if runtime_image else output_dir,
                env=os.environ.copy() if runtime_image else env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 10 if runtime_image else timeout_seconds,
                check=False,
            )
    except subprocess.TimeoutExpired as exc:
        result["status"] = "call_timeout"
        result["reason"] = f"smoke invocation exceeded {timeout_seconds} seconds"
        result["call"] = {
            "ok": False,
            "timeout_seconds": timeout_seconds,
            "stdout": (exc.stdout or b"").decode("utf-8", errors="replace")[-4000:]
            if isinstance(exc.stdout, bytes) else str(exc.stdout or "")[-4000:],
            "stderr": (exc.stderr or b"").decode("utf-8", errors="replace")[-4000:]
            if isinstance(exc.stderr, bytes) else str(exc.stderr or "")[-4000:],
        }
        return result
    except OSError as exc:
        result["status"] = "runtime_launch_failed"
        result["reason"] = f"{type(exc).__name__}: {exc}"
        result["call"] = {"ok": False, "stderr": str(exc)}
        return result

    result["import"] = {
        "ok": "COMPONENT_IMPORT_OK" in completed.stdout,
    }
    result["call"] = {
        "ok": "COMPONENT_CALL_OK" in completed.stdout and completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-8000:],
    }
    try:
        runtime_record = next(line.removeprefix("COMPONENT_RUNTIME_ENVIRONMENT=")
                              for line in completed.stdout.splitlines()
                              if line.startswith("COMPONENT_RUNTIME_ENVIRONMENT="))
        result["runtime_environment"] = json.loads(runtime_record)
    except (StopIteration, ValueError):
        result["runtime_environment"] = None
    try:
        trace = next(line.removeprefix("COMPONENT_EXECUTION_TRACE=")
                     for line in reversed(completed.stdout.splitlines())
                     if line.startswith("COMPONENT_EXECUTION_TRACE="))
        observations = json.loads(trace)
        if not isinstance(observations, list) or not all(isinstance(item, dict) for item in observations):
            raise ValueError("invalid execution trace")
    except (StopIteration, ValueError):
        observations = None
    result["execution_observations"] = observations or []
    if completed.returncode in {124, 137}:
        result["status"] = "call_timeout"
        result["reason"] = f"smoke invocation exceeded {timeout_seconds} seconds"
        return result
    if completed.returncode != 0:
        result["status"] = "call_failed"
        result["reason"] = "component import or smoke invocation failed"
        return result
    if observations is None:
        result["status"] = "execution_trace_missing"
        result["reason"] = "smoke runtime did not provide actual component call observations"
        result["call"]["ok"] = False
        return result
    result["execution_observations"] = observations
    seen_calls = sorted({item.get("entrypoint") for item in observations if isinstance(item.get("entrypoint"), str)})
    result["smoke_entrypoint_calls"] = seen_calls
    if not set(entrypoint_names) <= set(seen_calls):
        result["status"] = "smoke_does_not_call_entrypoints"
        result["reason"] = "run(common) did not execute every declared component entrypoint"
        result["call"]["ok"] = False
        return result
    result["status"] = "ok"
    return result
