#!/usr/bin/env python3
"""Freeze and verify the task-blind source corpus of a V2 library.

V2 is library-first: the component library is extracted before any task
exists, from the source-side production code, callers and build files only.
This tool records that corpus deterministically so every task in the family
can prove it read the same frozen snapshot.

It never reads a task package.  The corpus is selected from a pinned Git
commit with explicit include/exclude patterns; the selection and the resulting
content digests are written to ``lock.json`` next to the freeze spec.

``snapshot.evaluator_side`` is an assertion list for paths that must never
enter the corpus (for example the target-platform implementations that are the
gold for the task family).  Those patterns are excluded automatically, and
both ``snapshot`` and ``verify`` fail if a selected or already-locked path
matches one of them.

Usage::

    python3 tools/freeze_library.py snapshot \
        --spec v2/windows_to_kylin/library/freeze.yaml

    python3 tools/freeze_library.py verify \
        --spec v2/windows_to_kylin/library/freeze.yaml \
        --local-cache ~/.cache/migration-bench/repos

    # after the component library has been reviewed and published:
    python3 tools/freeze_library.py publish \
        --spec v2/windows_to_kylin/library/freeze.yaml \
        --library-root /path/to/published/library --component-count 42

The lock's corpus digest is computed over file bytes, not Git object ids, so
it stays meaningful if the repository is mirrored or re-packed:

    sha256( concat(sorted("path\0sha256(content)\n")) )

``--offline`` restricts the tool to a repository already present in the local
cache; without it a missing cache entry is cloned from ``library.repo``.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK_SCHEMA = "v2-library-lock-v1"
SPEC_SCHEMA = "v2-library-freeze-v1"


class FreezeError(RuntimeError):
    pass


def _run(cmd: List[str], *, timeout: int = 600, input_bytes: Optional[bytes] = None) -> Tuple[int, bytes]:
    proc = subprocess.run(
        cmd,
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or b"") + (proc.stderr or b"")


def _git(repo: Path, *args: str, timeout: int = 600) -> bytes:
    rc, out = _run(["git", "-C", str(repo), *args], timeout=timeout)
    if rc != 0:
        raise FreezeError(f"git {' '.join(args)} failed: {out.decode('utf-8', 'replace')[-2000:]}")
    return out


def _repo_slug(url: str) -> str:
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)


def _cache_root(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    base = os.environ.get("MIGRATION_BENCH_CACHE")
    if base:
        return Path(base).expanduser().resolve() / "repos"
    return Path.home() / ".cache" / "migration-bench" / "repos"


def _ensure_repo(spec: Dict[str, Any], cache: Path, *, offline: bool, repo_arg: Optional[str]) -> Path:
    if repo_arg:
        repo = Path(repo_arg).expanduser().resolve()
        if not (repo / ".git").exists() and not (repo / "HEAD").exists():
            raise FreezeError(f"--repo is not a Git repository: {repo}")
        return repo

    lib = spec.get("library") or {}
    url = str(lib.get("repo") or "")
    commit = str(lib.get("commit") or "")
    if not url or not commit:
        raise FreezeError("library.repo and library.commit are required")
    repo = cache / f"{_repo_slug(url)}-{commit[:12]}"
    if (repo / ".git").exists() or (repo / "HEAD").is_file():
        return repo
    if offline:
        raise FreezeError(f"repository not in local cache and --offline is set: {repo}")
    repo.parent.mkdir(parents=True, exist_ok=True)
    print(f"== cloning {url} (blobless) ==", file=sys.stderr)
    rc, out = _run(["git", "clone", "--filter=blob:none", "--no-checkout", url, str(repo)], timeout=1800)
    if rc != 0:
        raise FreezeError(out.decode("utf-8", "replace")[-2000:])
    return repo


def _ensure_commit(repo: Path, commit: str, tag: str, *, offline: bool) -> None:
    rc, _ = _run(["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"], timeout=120)
    if rc == 0:
        return
    if offline:
        raise FreezeError(f"commit {commit} is not in {repo} and --offline is set")
    _run(["git", "-C", str(repo), "fetch", "--depth", "1", "origin", commit], timeout=1800)
    rc, _ = _run(["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"], timeout=120)
    if rc != 0 and tag:
        _run(["git", "-C", str(repo), "fetch", "--depth", "1", "origin", f"refs/tags/{tag}"], timeout=1800)
    rc, _ = _run(["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"], timeout=120)
    if rc != 0:
        raise FreezeError(f"commit {commit} is not available in {repo}")


def _literal_root(pattern: str) -> str:
    wildcard_positions = [pattern.find(ch) for ch in "*?[" if pattern.find(ch) >= 0]
    if not wildcard_positions:
        return pattern
    head = pattern[: min(wildcard_positions)]
    return head.rstrip("/") or "."


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _list_paths(repo: Path, commit: str, include: List[str], exclude: List[str]) -> List[str]:
    if not include:
        raise FreezeError("snapshot.include is empty")
    roots = sorted({_literal_root(pattern) for pattern in include})
    if "." in roots:
        raise FreezeError(
            "every snapshot.include pattern must start with a literal path component; "
            f"got {roots}"
        )
    out = _git(repo, "ls-tree", "-r", "--name-only", commit, "--", *roots)
    paths = [line for line in out.decode("utf-8", "replace").splitlines() if line]
    selected = [p for p in paths if _matches(p, include) and not _matches(p, exclude)]
    if not selected:
        raise FreezeError("snapshot selection is empty")
    return sorted(selected)


def _batch_blobs(repo: Path, commit: str, paths: List[str]) -> Dict[str, bytes]:
    """Read all selected blobs through one ``git cat-file --batch`` process."""
    proc = subprocess.Popen(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    for path in paths:
        proc.stdin.write(f"{commit}:{path}\n".encode("utf-8"))
    proc.stdin.close()
    blobs: Dict[str, bytes] = {}
    for path in paths:
        header = proc.stdout.readline()
        if not header:
            raise FreezeError(f"git cat-file stopped before {path}")
        parts = header.split()
        if len(parts) != 3 or parts[1] != b"blob":
            raise FreezeError(f"unexpected cat-file header for {path}: {header!r}")
        size = int(parts[2])
        blobs[path] = proc.stdout.read(size)
        proc.stdout.read(1)  # trailing newline
    stderr = proc.stderr.read()
    rc = proc.wait()
    if rc != 0:
        raise FreezeError(stderr.decode("utf-8", "replace")[-2000:])
    return blobs


def _load_spec(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        spec = yaml.safe_load(fh) or {}
    if not isinstance(spec, dict):
        raise FreezeError(f"{path}: spec must be a mapping")
    if spec.get("schema") != SPEC_SCHEMA:
        raise FreezeError(f"{path}: schema must be {SPEC_SCHEMA!r}")
    snapshot = spec.get("snapshot") or {}
    if not snapshot.get("task_blind"):
        raise FreezeError(f"{path}: snapshot.task_blind must be true")
    for pattern in snapshot.get("include") or []:
        text = str(pattern)
        if text.startswith("v2/") or "task.yaml" in text or "tasks/" in text:
            raise FreezeError(
                f"{path}: include pattern {text!r} would pull task material into the corpus"
            )
    evaluator_side = snapshot.get("evaluator_side") or []
    if not isinstance(evaluator_side, list):
        raise FreezeError(f"{path}: snapshot.evaluator_side must be a list")
    for pattern in evaluator_side:
        if not str(pattern).strip():
            raise FreezeError(f"{path}: snapshot.evaluator_side contains an empty pattern")
    return spec


def _spec_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lock_path(spec_path: Path, explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return spec_path.parent / "lock.json"


def _corpus(spec: Dict[str, Any], repo: Path) -> Dict[str, Any]:
    lib = spec.get("library") or {}
    commit = str(lib.get("commit") or "")
    snapshot = spec.get("snapshot") or {}
    include = [str(x) for x in snapshot.get("include") or []]
    exclude = [str(x) for x in snapshot.get("exclude") or []]
    evaluator_side = [str(x) for x in snapshot.get("evaluator_side") or []]
    effective_exclude = list(dict.fromkeys(exclude + evaluator_side))
    paths = _list_paths(repo, commit, include, effective_exclude)
    leaked = [p for p in paths if _matches(p, evaluator_side)]
    if leaked:
        raise FreezeError(
            "corpus contains evaluator-side implementation: " + ", ".join(leaked[:10])
        )
    blobs = _batch_blobs(repo, commit, paths)

    files: List[Dict[str, Any]] = []
    digest = hashlib.sha256()
    total_bytes = 0
    for path in paths:
        data = blobs[path]
        file_digest = hashlib.sha256(data).hexdigest()
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
        files.append({
            "path": path,
            "sha256": file_digest,
            "size": len(data),
            "blob": _git(repo, "rev-parse", f"{commit}:{path}").decode().strip(),
        })
        total_bytes += len(data)

    tree = _git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    subdir = str(lib.get("subdir") or "").strip("/")
    subtree = None
    if subdir:
        subtree = _git(repo, "rev-parse", f"{commit}:{subdir}").decode().strip()
    return {
        "include": include,
        "exclude": effective_exclude,
        "evaluator_side": evaluator_side,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "digest": digest.hexdigest(),
        "algorithm": "sha256",
        "mode": "content",
        "files": files,
        "tree": {"commit_tree": tree, "subdir_tree": subtree},
    }


def _published_library_digest(root: Path) -> Tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for current, dirs, names in os.walk(root):
        dirs.sort()
        for name in sorted(names):
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_digest.encode("ascii"))
            digest.update(b"\n")
            count += 1
    return digest.hexdigest(), count


def _base_lock(spec_path: Path, spec: Dict[str, Any], repo: Path) -> Dict[str, Any]:
    lib = spec.get("library") or {}
    return {
        "schema": LOCK_SCHEMA,
        "spec_sha256": _spec_sha256(spec_path),
        "library": {
            "id": str(lib.get("id") or ""),
            "version": int(lib.get("version") or 1),
            "repo": str(lib.get("repo") or ""),
            "commit": str(lib.get("commit") or ""),
            "tag": str(lib.get("tag") or ""),
            "subdir": str(lib.get("subdir") or ""),
            "license": str(lib.get("license") or ""),
            "language_backend": str((lib.get("language_backend") or "cpp@1")),
            "task_blind": bool((spec.get("snapshot") or {}).get("task_blind")),
        },
        "corpus": _corpus(spec, repo),
        "publication": {
            "status": "pending_publication",
            "library_digest": None,
            "component_count": None,
            "published_at": None,
        },
        "generated_by": "tools/freeze_library.py",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def cmd_snapshot(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec).expanduser().resolve()
    spec = _load_spec(spec_path)
    repo = _ensure_repo(spec, _cache_root(args.local_cache), offline=args.offline, repo_arg=args.repo)
    lib = spec.get("library") or {}
    _ensure_commit(repo, str(lib.get("commit") or ""), str(lib.get("tag") or ""), offline=args.offline)
    lock = _base_lock(spec_path, spec, repo)
    out = _lock_path(spec_path, args.lock)
    out.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    corpus = lock["corpus"]
    print(
        f"FROZEN {lock['library']['id']}@{str(lock['library']['commit'])[:12]} "
        f"files={corpus['file_count']} bytes={corpus['total_bytes']} "
        f"digest=sha256:{corpus['digest']}"
    )
    print(f"wrote {out}")
    return 0


def _manifest_core(files: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Path/content manifest without Git blob ids.

    Blob ids are kept in the lock as an audit trail, but they depend on the
    repository's object format; the verifiable identity is path + content.
    """
    return [
        {"path": item.get("path"), "sha256": item.get("sha256"), "size": item.get("size")}
        for item in files
    ]


def _load_lock(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        lock = json.load(fh)
    if lock.get("schema") != LOCK_SCHEMA:
        raise FreezeError(f"{path}: schema must be {LOCK_SCHEMA!r}")
    return lock


def cmd_verify(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec).expanduser().resolve()
    spec = _load_spec(spec_path)
    lock_path = _lock_path(spec_path, args.lock)
    lock = _load_lock(lock_path)
    repo = _ensure_repo(spec, _cache_root(args.local_cache), offline=args.offline, repo_arg=args.repo)
    lib = spec.get("library") or {}
    _ensure_commit(repo, str(lib.get("commit") or ""), str(lib.get("tag") or ""), offline=args.offline)
    current = _base_lock(spec_path, spec, repo)

    errors: List[str] = []
    evaluator_side = [
        str(x) for x in (spec.get("snapshot") or {}).get("evaluator_side") or []
    ]
    locked_paths = [
        str(f.get("path") or "") for f in (lock.get("corpus") or {}).get("files") or []
    ]
    leaked = sorted(p for p in locked_paths if _matches(p, evaluator_side))
    if leaked:
        errors.append(
            "lock corpus contains evaluator-side implementation: "
            + ", ".join(leaked[:10])
        )
    if current["spec_sha256"] != lock.get("spec_sha256"):
        errors.append("freeze spec changed since the lock was written")
    for key in ("id", "commit", "subdir", "version", "language_backend", "task_blind"):
        if current["library"].get(key) != (lock.get("library") or {}).get(key):
            errors.append(f"library.{key} differs: lock={lock.get('library', {}).get(key)!r} now={current['library'].get(key)!r}")
    old = lock.get("corpus") or {}
    new = current["corpus"]
    if old.get("digest") != new["digest"]:
        errors.append(f"corpus digest differs: lock={old.get('digest')} now={new['digest']}")
    if old.get("file_count") != new["file_count"]:
        errors.append(f"corpus file count differs: lock={old.get('file_count')} now={new['file_count']}")
    if _manifest_core(old.get("files") or []) != _manifest_core(new["files"]):
        errors.append("per-file manifest differs")

    publication = lock.get("publication") or {}
    if publication.get("status") == "published":
        if not publication.get("library_digest"):
            errors.append("publication.status is published but library_digest is empty")
        if args.library_root:
            digest, count = _published_library_digest(Path(args.library_root).expanduser().resolve())
            if digest != publication.get("library_digest"):
                errors.append(f"published library digest differs: lock={publication.get('library_digest')} now={digest}")
            if count != publication.get("component_count"):
                errors.append(f"published component count differs: lock={publication.get('component_count')} now={count}")

    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1
    print(
        f"OK {lock['library']['id']}@{str(lock['library']['commit'])[:12]} "
        f"files={new['file_count']} digest=sha256:{new['digest']} "
        f"publication={(publication.get('status') or 'unknown')}"
    )
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec).expanduser().resolve()
    _load_spec(spec_path)
    lock_path = _lock_path(spec_path, args.lock)
    lock = _load_lock(lock_path)
    library_root = Path(args.library_root).expanduser().resolve()
    if not library_root.is_dir():
        raise FreezeError(f"--library-root is not a directory: {library_root}")
    digest, count = _published_library_digest(library_root)
    if args.component_count is not None and int(args.component_count) != count:
        raise FreezeError(
            f"--component-count {args.component_count} does not match {count} files under {library_root}"
        )
    lock["publication"] = {
        "status": "published",
        "library_digest": digest,
        "component_count": count,
        "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "library_root": str(library_root),
    }
    lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"PUBLISHED library_digest=sha256:{digest} component_count={count}")
    print(f"wrote {lock_path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    for name in ("snapshot", "verify", "publish"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--spec", required=True, help="library freeze spec (YAML)")
        cmd.add_argument("--lock", default=None, help="lock path (default: lock.json next to the spec)")
        cmd.add_argument("--repo", default=None, help="existing Git repository to read")
        cmd.add_argument("--local-cache", default=None, help="repo cache root (default: $MIGRATION_BENCH_CACHE/repos)")
        cmd.add_argument("--offline", action="store_true", help="do not clone or fetch")
        if name == "publish":
            cmd.add_argument("--library-root", required=True, help="published component library directory")
            cmd.add_argument("--component-count", type=int, default=None)
        if name == "verify":
            cmd.add_argument("--library-root", default=None, help="also verify the published library tree")

    args = ap.parse_args(argv)
    try:
        if args.command == "snapshot":
            return cmd_snapshot(args)
        if args.command == "verify":
            return cmd_verify(args)
        return cmd_publish(args)
    except (FreezeError, OSError, yaml.YAMLError) as exc:  # noqa: BLE001 - CLI boundary
        print(f"ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())