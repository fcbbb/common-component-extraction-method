"""Reuse exact review inputs only while all declared review dependencies match."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path

from .extraction import locked_entry, save_entry
from .digest import code_digest, digest
from ..validation.service import _review_brief, _review_task_prompt


def _shell_segments(command: str):
    """Tokenize simple shell chains while preserving quoted operators."""
    if "\\\n" in command:
        raise ValueError("dynamic shell syntax")
    lexer = shlex.shlex(command, posix=False, punctuation_chars=";&|<>()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    segments, current, connector = [], [], None
    for token in lexer:
        if token in {"&&", "||", ";", "|", "\n"}:
            if current:
                segments.append((connector, current))
                current = []
            elif token != "\n":
                raise ValueError("empty shell command")
            connector = token
        elif re.fullmatch(r"[;&|<>()\n]+", token):
            # Permit a semicolon followed by a newline, but no redirections,
            # background execution, command substitution or subshell state.
            if token.strip(";\n"):
                raise ValueError("unsupported shell operator")
            if current:
                segments.append((connector, current))
                current = []
            connector = ";"
        else:
            # Fully quoted tokens can contain literal pipes and semicolons.
            single_quoted = token.startswith("'") and token.endswith("'")
            if not single_quoted and ("`" in token or re.search(r"\$[A-Za-z0-9_{(@*!?#$\[\-]", token)):
                raise ValueError("dynamic shell expansion")
            if token[:1] not in {"'", '"'} and any(character in token for character in "{}"):
                raise ValueError("shell brace expansion")
            words = shlex.split(token)
            if len(words) != 1:
                raise ValueError("unsupported shell word")
            current.append(words[0])
    if current:
        segments.append((connector, current))
    elif connector in {"&&", "||", "|"}:
        raise ValueError("incomplete shell chain")
    return segments


def _operands(parts: list[str]):
    """Separate read/search paths from options and pattern/script operands."""
    name, args = parts[0], parts[1:]
    value_options = {
        "sed": {"-e", "--expression"},
        "head": {"-n", "-c", "--lines", "--bytes"},
        "tail": {"-n", "-c", "--lines", "--bytes"},
        "nl": {"-b", "-d", "-f", "-h", "-i", "-l", "-n", "-s", "-v", "-w"},
        "rg": {"-e", "--regexp", "-f", "--file", "-g", "--glob", "--iglob", "-t", "--type",
               "-T", "--type-not", "-A", "-B", "-C", "--after-context", "--before-context", "--context",
               "-m", "--max-count", "--max-depth", "--max-columns", "--max-filesize", "--encoding",
               "--sort", "--sortr", "-r", "--replace", "--color", "--colors", "--type-add"},
        "grep": {"-e", "--regexp", "-f", "--file", "-A", "-B", "-C", "--after-context", "--before-context",
                 "--context", "-m", "--max-count", "--include", "--exclude", "--exclude-dir", "--exclude-from"},
    }.get(name, set())
    operands, auxiliary, scripts = [], [], []
    has_pattern = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            operands.extend(args[index + 1:])
            break
        if name in {"rg", "grep"} and (arg in {"--files", "--type-list"}):
            has_pattern = True
        if name == "find" and arg.startswith("-"):
            if any(item in {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf"} for item in args[index:]):
                raise ValueError("find can execute scripts or write files")
            break
        if name == "sed" and (arg.startswith("-f") or arg.startswith("--file") or arg.startswith("-i")):
            raise ValueError("external or mutating sed script")
        if name == "rg" and (arg.startswith("--pre") or arg.startswith("--hostname-bin") or arg == "--follow" or arg == "-L"):
            raise ValueError("search can follow links or run external programs")
        if arg.startswith(("--ignore-file", "--files0-from", "-files0-from")):
            raise ValueError("external path list or search configuration")
        option, equal, attached = arg.partition("=")
        if option in value_options:
            if equal:
                value = attached
            else:
                index += 1
                if index >= len(args):
                    raise ValueError("missing option value")
                value = args[index]
            if option in {"-e", "--regexp", "--expression", "-f", "--file", "--exclude-from"}:
                if option != "--exclude-from":
                    has_pattern = True
                if option in {"-f", "--file", "--exclude-from"}:
                    auxiliary.append(value)
                elif name == "sed":
                    scripts.append(value)
        elif name in {"rg", "grep"} and arg.startswith(("-e", "-f")) and len(arg) > 2:
            has_pattern = True
            if arg.startswith("-f"):
                auxiliary.append(arg[2:])
        elif name == "sed" and arg.startswith("-e") and len(arg) > 2:
            has_pattern = True
            scripts.append(arg[2:])
        elif not arg.startswith("-") or arg == "-":
            operands.append(arg)
        index += 1
    if name in {"rg", "grep", "sed"} and not has_pattern:
        if not operands:
            raise ValueError("missing search pattern or sed script")
        pattern = operands.pop(0)
        if name == "sed":
            scripts.append(pattern)
    if name == "sed" and (not scripts or any(
        not re.fullmatch(r"\s*(?:\d+|\$)(?:,(?:\d+|\$))?p\s*", script) for script in scripts)):
        # sed's r/e/w commands can read other files or execute programs. Only
        # source-inspection print ranges have a statically known read scope.
        raise ValueError("unsupported sed script")
    return operands, auxiliary


def _command_dependencies(command: str, repo: Path):
    root, cwd = repo.resolve(), repo.resolve()
    files, scopes = set(), set()

    def paths(word: str):
        if word == "/testbed" or word.startswith("/testbed/"):
            path = root / word.removeprefix("/testbed").lstrip("/")
        elif word.startswith("/"):
            raise ValueError("path outside repository")
        else:
            path = cwd / word
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("path escapes repository")
        if resolved.relative_to(root).as_posix() in {
            ".components", ".components/common.py",
            ".components/component.json",
        }:
            # These read-only artifact inputs are already covered by review_identity.
            return []
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent.is_relative_to(root)):
            raise ValueError("symlink-dependent command")
        if any(char in word for char in "*?["):
            relative = path.relative_to(root).as_posix()
            prefix = re.split(r"[\*\?\[]", relative, maxsplit=1)[0]
            scope = Path(prefix.rsplit("/", 1)[0]) if "/" in prefix else Path(".")
            scopes.add(scope.as_posix())
            return sorted(root.glob(relative))
        if not path.exists():
            raise ValueError("unresolved read/search path")
        return [resolved]

    segments = _shell_segments(command)
    for index, (connector, parts) in enumerate(segments):
        name = parts[0]
        if connector == "||" and parts != ["true"]:
            raise ValueError("conditional shell state")
        if name == "cd":
            piped_out = index + 1 < len(segments) and segments[index + 1][0] == "|"
            if connector == "|" or piped_out or len(parts) != 2 or parts[1] == "-":
                raise ValueError("unsupported working directory")
            destinations = paths(parts[1])
            if len(destinations) != 1 or not destinations[0].is_dir():
                raise ValueError("unresolved working directory")
            cwd = destinations[0]
            continue
        if name in {"pwd", "echo", "printf", "true"}:
            continue
        if name not in {"cat", "sed", "head", "tail", "nl", "wc", "rg", "grep", "find", "ls"}:
            raise ValueError("script or unsupported command")
        operands, auxiliary = _operands(parts)
        for word in auxiliary:
            for path in paths(word):
                files.add(path.relative_to(root).as_posix())
        operands = [word for word in operands if word != "-"]
        if name in {"rg", "grep", "find", "ls"}:
            if not operands and connector == "|" and "--files" not in parts:
                continue  # Search a previous command's output, not the filesystem.
            scopes.update(path.relative_to(root).as_posix() for word in (operands or ["."]) for path in paths(word))
            # Recursive searches may consult ignore rules in parent directories.
            for scope in list(scopes):
                path = root / scope
                for parent in [path.parent, *path.parents]:
                    if not parent.is_relative_to(root):
                        continue
                    for filename in (".gitignore", ".ignore", ".rgignore"):
                        config = parent / filename
                        if config.is_file():
                            files.add(config.relative_to(root).as_posix())
        elif operands:
            files.update(path.relative_to(root).as_posix() for word in operands for path in paths(word))
        elif connector != "|":
            raise ValueError("read command has no known input")
    return files, scopes


def observed_dependencies(trajectory: Path, repo: Path):
    """Conservatively account for tool commands as well as the reviewer's manifest."""
    try:
        payload = json.loads(trajectory.read_text())
        messages = payload["messages"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    scopes, files = set(), set()
    seen = False
    normalized_actions = []
    for call in payload.get("tool_calls") or []:
        if not isinstance(call, dict):
            scopes.add(".")
            continue
        action = call.get("input")
        if isinstance(action, dict):
            normalized_actions.append(action)
        else:
            scopes.add(".")
    for message in messages:
        if message.get("role") != "assistant":
            continue
        actions = (message.get("extra") or {}).get("actions", [])
        actions = list(actions)
        for call in message.get("tool_calls") or []:
            try:
                actions.append(json.loads(call.get("function", {}).get("arguments", "{}")))
            except (ValueError, TypeError):
                scopes.add(".")
        normalized_actions.extend(actions)
    for action in normalized_actions:
        if not isinstance(action, dict):
            scopes.add(".")
            continue
        command = action.get("command", "")
        if not isinstance(command, str):
            scopes.add(".")
            continue
        seen = True
        if re.fullmatch(r"\s*cat\s+<<\s*(['\"])([A-Za-z0-9_]+)\1\nCOMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n.*\n\2\s*", command, re.DOTALL):
            continue
        try:
            read, searched = _command_dependencies(command, repo)
            files.update(read)
            scopes.update(searched)
        except (ValueError, OSError):
            scopes.add(".")
    return {"files": sorted(files), "search_scopes": sorted(scopes)} if seen else None


def merge_review_dependencies(manifest, observed):
    """Keep malformed dependency claims from crashing reviews or enabling cache reuse."""
    if not isinstance(manifest, dict):
        return manifest
    result = dict(manifest)
    invalid = []
    for field in ("files", "search_scopes"):
        values = manifest.get(field)
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip()
                                               for value in values):
            invalid.append(field)
        declared = [value for value in values if isinstance(value, str) and value.strip()] if isinstance(values, list) else []
        result[field] = sorted(set(declared) | set(observed[field] if observed is not None else []))
    if invalid:
        result["complete"] = False
        result["dependency_errors"] = [f"{field} must be a list of non-empty repository-relative strings"
                                       for field in invalid]
    if observed is None:
        result.update(complete=False, trace_accounting="unrecognized_trace")
    else:
        result["trace_accounting"] = "conservative_shell_scopes"
    return result


def review_identity(payload, runner, experiment_dir):
    config_identity = getattr(runner, "agent_config_identity", None)
    from component_method.component_build.validation.artifact_service import artifact_backend, artifact_of, extraction_record

    proposed = payload.get("proposed_component", payload.get("candidate", payload))
    if "artifact" in extraction_record(proposed):
        from component_method.languages.prompts import review_prompt

        artifact = artifact_of(proposed)
        backend = artifact_backend(artifact)
        repository_root = getattr(runner, "repository_root", None)
        if repository_root and hasattr(backend, "set_repository"):
            backend.set_repository(Path(repository_root))
        return digest({"schema": 2, "component": proposed, "payload": payload,
                       "task": review_prompt(proposed, backend), "backend_identity": backend.identity().to_json(),
                       "agent_config": config_identity("review") if callable(config_identity) else None,
                       "model": getattr(runner, "model", None), "endpoint": getattr(runner, "base_url", None),
                       "review_runtime_image": getattr(runner, "image_id", None),
                       "task_runtime_image": getattr(runner, "runtime_image", None),
                       "code": code_digest("component_build/validation/artifact_service.py",
                                           "component_build/validation/execution.py",
                                           "component_build/submission.py", "component_build/extraction/runner.py",
                                           "component_build/cache/review.py")})
    return digest({"schema": 1, "task": _review_task_prompt(payload, experiment_dir),
                   "component_code": digest(_review_brief(payload)["component_code"]),
                   "agent_config": config_identity("review") if callable(config_identity) else None,
                   "model": getattr(runner, "model", None), "endpoint": getattr(runner, "base_url", None),
                   "review_runtime_image": getattr(runner, "image_id", None),
                   "task_runtime_image": getattr(runner, "runtime_image", None),
                   "code": code_digest("component_build/validation/service.py", "component_build/cache/review.py",
                                       "component_build/workspace.py", "component_build/submission.py",
                                       "component_build/extraction/runner.py", "agent_runtime/dsh_headless.py",
                                       "component_build/agent_configs/runtime.yaml",
                                       "component_build/agent_configs/review.yaml")})


def _references(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"file_id", "caller_file", "callee_file", "source_file", "target_file"} and isinstance(item, str):
                yield item
            else:
                yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)


def dependency_snapshot(repo, payload, review):
    """Hash citations, inputs, uncited reads, and full content of search scopes."""
    manifest = review.get("validation_dependencies")
    if not isinstance(manifest, dict) or manifest.get("complete") is not True:
        return None
    files, scopes = manifest.get("files"), manifest.get("search_scopes")
    if not isinstance(files, list) or not isinstance(scopes, list) or not files:
        return None
    root = repo.resolve()

    def checked(name):
        if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("dependency must be repository-relative")
        path = (root / name).resolve()
        if not path.is_relative_to(root) or ".git" in path.relative_to(root).parts:
            raise ValueError("dependency is outside the visible source")
        return path

    hashes = {}
    try:
        for name in sorted(set(files) | set(_references(payload)) | set(_references(review))):
            if name in {".components/common.py", ".components/component.json"}:
                continue
            path = checked(name)
            if not path.is_file():
                return None
            hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        for scope in scopes:
            if scope == ".components":
                continue
            path = checked(scope)
            if not path.exists():
                return None
            paths = [path] if path.is_file() else path.rglob("*")
            for child in paths:
                relative = child.relative_to(root)
                if ".git" in relative.parts:
                    continue
                if child.is_symlink():
                    return None
                if child.is_file():
                    hashes[relative.as_posix()] = hashlib.sha256(child.read_bytes()).hexdigest()
        namespace = sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                           if p.is_file() and ".git" not in p.relative_to(root).parts)
    except (ValueError, OSError, TypeError):
        return None
    return {"files": hashes, "namespace": digest(namespace), "search_scopes": scopes}


def cached_review(cache_root, repo, payload, runner, experiment_dir, operation):
    """Lock identical prompts; retain variants for different dependency snapshots."""
    if cache_root is None:
        return operation(), {"status": "disabled"}
    key = review_identity(payload, runner, experiment_dir)
    root = cache_root / key
    with locked_entry(cache_root, key):
        for path in sorted(root.glob("*.json")):
            try:
                saved = json.loads(path.read_text())
                review = saved["response"]
                snapshot = dependency_snapshot(repo, payload, review)
                if snapshot is not None and snapshot == saved["inputs"]:
                    return review, {"status": "hit", "key": key, "dependency_key": path.stem,
                                    "file_count": len(snapshot["files"])}
            except (OSError, ValueError, KeyError, TypeError):
                continue
        review = operation()
        snapshot = dependency_snapshot(repo, payload, review)
        if snapshot is None or review.get("status") not in {"confirmed", "rejected"}:
            return review, {"status": "not_cacheable", "key": key, "reason": "Incomplete dependency manifest or uncertain review"}
        root.mkdir(parents=True, exist_ok=True)
        dependency_key = digest(snapshot)
        save_entry(root / f"{dependency_key}.json", snapshot, review)
        return review, {"status": "miss", "key": key, "dependency_key": dependency_key,
                        "file_count": len(snapshot["files"])}
