"""发布包内的任务数据、模型配置和运行路径。"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from component_method.runtime_paths import offline_task_root, resolve_release_path


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("COMPONENT_METHOD_TASK_ROOT", Path.cwd())).resolve()
CONFIG = RUNTIME_ROOT / "config"
OUT = ROOT / "outputs"
sys.path[:0] = [str(RUNTIME_ROOT / "adapters"), str(RUNTIME_ROOT / "core")]
ACTIVATION = "export PATH=/usr/local/bin:/usr/bin:/bin; export PYTHONPYCACHEPREFIX=/tmp/pycache"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def hashes(root):
    root = Path(root)
    if not root.is_dir():
        return {}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and "component_bundle" not in path.relative_to(root).parts
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    }


def task_config():
    return read(ROOT / "config.json")


def task_data_root():
    return offline_task_root(task_config()["task_id"])


def rows():
    public = read(task_data_root() / "task.json")
    private = read(task_data_root() / "evaluation_only" / "task_private.json")
    return [
        {
            **public,
            "patch": private.get("reference_patch", ""),
            "test_patch": private.get("test_patch", ""),
            "install_config": private.get("install_config", {}),
        }
    ]


def agent_rows():
    public = read(task_data_root() / "task.json")
    return [{key: public.get(key) for key in ("instance_id", "problem_statement", "interface")}]


def evaluation_adjustments():
    private = read(task_data_root() / "evaluation_only" / "task_private.json")
    value = private.get("evaluation_adjustments", {})
    return value if isinstance(value, dict) else {}


def settings():
    cfg = task_config()
    public = rows()[0]
    library_manifest = read(task_data_root() / "component_library" / "manifest.json")
    source_root = resolve_release_path(cfg["repository_root"])
    base = read(CONFIG / "experiment.json")
    return {
        **base,
        "model": cfg["model"],
        "expected_api_base": cfg["api_base"],
        "groups": [
            {
                "group_id": cfg["task_id"],
                "repo": public["repo"],
                "task_ids": [cfg["task_id"]],
                "extraction_commit": library_manifest["source_commit"],
                "runtime_image": cfg["runtime_image"],
                "source_root": str(source_root),
                "source_sha256": digest(hashes(source_root)),
            }
        ],
    }


def groups():
    return settings()["groups"]


MODEL = task_config()["model"]


def model_env():
    cfg = task_config()
    api_key = os.environ.get("OPENAI_API_KEY")
    api_base = os.environ.get("OPENAI_API_BASE") or cfg["api_base"]
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
    if not api_base:
        raise RuntimeError("OPENAI_API_BASE is required")
    if cfg.get("api_base") and api_base.rstrip("/") != cfg["api_base"].rstrip("/"):
        raise RuntimeError("Effective API destination differs from the prepared task config.")
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = api_key
    env["OPENAI_API_BASE"] = api_base
    env["OPENAI_BASE_URL"] = api_base
    env["MODEL_NAME"] = cfg["model"]
    env["REQUEST_TIMEOUT"] = str(settings()["api_request_timeout"])
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(RUNTIME_ROOT / "core"), str(RUNTIME_ROOT / "adapters")]
    )
    return env


def model_config():
    return {
        "model_name": MODEL,
        "model_kwargs": {
            "drop_params": True,
            "temperature": 0.0,
            "api_base": model_env()["OPENAI_API_BASE"],
        },
        "litellm_model_registry": str(CONFIG / "pricing.json"),
    }


def input_identity():
    files = {
        "task_config": hashlib.sha256((ROOT / "config.json").read_bytes()).hexdigest(),
        "task_public": hashlib.sha256((task_data_root() / "task.json").read_bytes()).hexdigest(),
        "task_private": hashlib.sha256(
            (task_data_root() / "evaluation_only" / "task_private.json").read_bytes()
        ).hexdigest(),
        "config": hashes(CONFIG),
        "core": hashes(RUNTIME_ROOT / "core"),
        "adapters": hashes(RUNTIME_ROOT / "adapters"),
    }
    return digest(files)


def verify_inputs():
    manifest = read(OUT / "prepared.json")
    if manifest["input_sha256"] != input_identity():
        raise RuntimeError("Prepared inputs/code changed; use a fresh output directory.")
    return manifest
