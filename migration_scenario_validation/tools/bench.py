#!/usr/bin/env python3
"""Unified entry point for the paired migration benchmark.

One config (``bench.yaml``) and three arms over the same task packages, judge,
model and budgets:

* ``--arm default`` -- plain DSH (profile ``component-method``): the agent gets
  ``controlled_bash`` only and migrates directly.
* ``--arm method``  -- one main agent (profile ``component-method-migration``)
  that runs the fixed component-method workflow first (scan, extract, curate,
  publish, retrieve, materialize ``/workspace/component_bundle``) and then
  completes the same migration task in the same session.  The main agent has no
  step limit: a budget belongs only to a separate extra task-execution agent,
  which the runner does not start.

Commands::

    python3 tools/bench.py doctor                 # preflight for both arms
    python3 tools/bench.py doctor --arm method    # method-arm readiness
    python3 tools/bench.py verify                 # static check of all 60 tasks
    python3 tools/bench.py env                    # build the declared images
    python3 tools/bench.py gold --scenario windows_to_kylin
    python3 tools/bench.py run --arm default --scenario windows_to_kylin --only l1_poco_thread
    python3 tools/bench.py run --arm method  --all --runs 3 --label method_v1
    python3 tools/bench.py report --label default_v1
    python3 tools/bench.py compare --default-label default_v1 --method-label method_v1

Exit codes: 0 = ok, 1 = at least one gate failed, 2 = setup error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "bench.yaml"

SCENARIOS = (
    "ipp_to_vsipl",
    "windows_to_kylin",
    "windows_to_kylin_v3",
    "cuda_to_musa",
)
TASK_PARENTS = {
    "ipp_to_vsipl": "v1/ipp_vsipl_tasks",
    "windows_to_kylin": "v1/windows_to_kylin/tasks",
    "windows_to_kylin_v3": "v3/windows_to_kylin/tasks",
    "cuda_to_musa": "v1/cuda_to_musa/tasks",
}

PINNED_NODE = "24.9.0"
PINNED_DSH = "0.2.2-rc.1"

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default if default is not None else "")
        return _ENV_RE.sub(replace, value)
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


def load_config(path: Path) -> Dict[str, Any]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"ERROR config is not a mapping: {path}")
    return _expand(data)


def _repo_path(cfg: Dict[str, Any]) -> Path:
    value = str(cfg.get("repository_root") or "..")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else (ROOT / path)).resolve()


def _config_path(cfg: Dict[str, Any], key: str, default: str) -> Path:
    value = str((cfg.get("paths") or {}).get(key) or default)
    path = Path(value).expanduser()
    return (path if path.is_absolute() else (ROOT / path)).resolve()


def _run(argv: List[str], *, timeout: int = 60, cwd: Optional[Path] = None) -> Tuple[int, str]:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _load_local_env() -> None:
    """Make `bench.py` see the same non-secret settings as run-*.sh.

    ``bench.env`` is sourced by the shell entry points.  The direct Python
    commands used to require a manual `set -a; . ./bench.env`, which made
    `doctor` report a missing VSIPL_ROOT even when the file was correct.
    Empty values are ignored so an empty credential line cannot mask an
    inherited or repository-level value.
    """
    for key, value in _dotenv(ROOT / "bench.env").items():
        if value:
            os.environ.setdefault(key, value)


def _dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip("'\"")
    return values


class Report:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str]] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.rows.append(("OK", name, detail))

    def warn(self, name: str, detail: str = "") -> None:
        self.rows.append(("WARN", name, detail))

    def fail(self, name: str, detail: str = "") -> None:
        self.rows.append(("FAIL", name, detail))

    def counts(self) -> Dict[str, int]:
        counts = {"OK": 0, "WARN": 0, "FAIL": 0}
        for level, _, _ in self.rows:
            counts[level] += 1
        return counts

    def print(self) -> None:
        for level, name, detail in self.rows:
            print(f"{level:4} {name}" + (f"  {detail}" if detail else ""))


def _node_bin(repo: Path) -> Optional[str]:
    configured = os.environ.get("COMPONENT_DSH_NODE_BIN")
    if configured:
        return configured
    found = shutil.which("node")
    if found:
        return found
    fallback = Path.home() / ".nvm" / "versions" / "node" / f"v{PINNED_NODE}" / "bin" / "node"
    return str(fallback) if fallback.is_file() else None


def _check_dsh(report: Report, repo: Path, arm: Optional[str]) -> None:
    dsh_root = repo / "dsh"
    package = dsh_root / "package.json"
    if not package.is_file():
        report.fail("dsh package.json", str(package))
        return
    try:
        payload = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.fail("dsh package.json", str(exc))
        return
    version = str((payload.get("dependencies") or {}).get("@deepseek-ai/dsh") or "")
    if version == PINNED_DSH:
        report.ok("dsh version", version)
    else:
        report.fail("dsh version", f"expected {PINNED_DSH}, found {version or 'none'}")

    node = _node_bin(repo)
    if not node:
        report.fail("node", f"not found; install Node.js {PINNED_NODE}")
    else:
        rc, out = _run([node, "--version"], timeout=15)
        found = out.strip().removeprefix("v")
        if rc == 0 and found == PINNED_NODE:
            report.ok("node", f"{node} (v{found})")
        else:
            report.fail("node", f"expected v{PINNED_NODE}, found {found or out.strip() or 'error'}")

    dsh_bin = dsh_root / "node_modules" / ".bin" / "dsh"
    if dsh_bin.is_file():
        report.ok("dsh executable", str(dsh_bin.relative_to(repo)))
    else:
        report.fail("dsh executable", f"missing {dsh_bin}; run `npm ci` in dsh/")

    profiles = dsh_root / "profiles"
    names = {
        "default": os.environ.get("BENCH_DEFAULT_DSH_PROFILE", "component-method"),
        # The method arm is one main agent with the method plugins loaded.
        "method": os.environ.get(
            "BENCH_METHOD_DSH_PROFILE", "component-method-migration"
        ),
    }
    if arm == "default":
        names = {"default": names["default"]}
    elif arm == "method":
        names = {"method": names["method"]}
    for name, profile in names.items():
        patch = profiles / profile / "cordis.patch.yml"
        if patch.is_file():
            report.ok(f"profile {name}", profile)
        else:
            report.fail(f"profile {name}", f"missing {patch}")

    plugins = sorted(path for path in (dsh_root / "plugins").iterdir() if path.is_dir())
    missing = [
        plugin.name for plugin in plugins
        if (plugin / "package.json").is_file() and not (plugin / "dist" / "index.js").is_file()
    ]
    if missing:
        report.fail("dsh plugin bundles", f"missing dist for {', '.join(missing)}; run `npm run build`")
    else:
        report.ok("dsh plugin bundles", f"{len(plugins)} plugins built")


def _check_credentials(report: Report, repo: Path, allow_missing: bool) -> None:
    env = _dotenv(repo / ".env")
    values = {
        "OPENAI_API_BASE": env.get("OPENAI_API_BASE") or os.environ.get("OPENAI_API_BASE", ""),
        "OPENAI_API_KEY": env.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", ""),
        "MODEL_NAME": env.get("MODEL_NAME") or os.environ.get("MODEL_NAME", ""),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        level = report.warn if allow_missing else report.fail
        level("model credentials", f"missing {', '.join(missing)} (.env at the repository root or environment)")
    else:
        report.ok("model credentials", "OPENAI_API_BASE / OPENAI_API_KEY / MODEL_NAME present")


def _enabled_scenarios(cfg: Dict[str, Any], requested: Iterable[str]) -> List[str]:
    requested = list(requested)
    if requested:
        unknown = sorted(set(requested) - set(SCENARIOS))
        if unknown:
            raise SystemExit(f"ERROR unknown scenario(s): {', '.join(unknown)}")
        return requested
    scenarios = cfg.get("scenarios") or {}
    return [name for name in SCENARIOS if (scenarios.get(name) or {}).get("enabled", True)]


def _scenario_cfg(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    return dict((cfg.get("scenarios") or {}).get(name) or {})


def _image_exists(image: str) -> bool:
    rc, _ = _run(["docker", "image", "inspect", image], timeout=60)
    return rc == 0


def _check_stage_plane(report: Report, repo: Path) -> None:
    """Report which plane the method arm's nested stage agents will use."""
    src = repo / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from component_method.agent_runtime.stage_plane import (
            DOCKER_STAGE_RUNTIME,
            stage_runtime,
            stage_runtime_reason,
        )

        plane = stage_runtime()
        reason = stage_runtime_reason()
    except Exception as exc:  # noqa: BLE001 - preflight must not crash
        report.warn("stage plane", f"cannot resolve ({exc}); stages default to docker")
        return
    if plane == DOCKER_STAGE_RUNTIME:
        report.ok("stage plane", f"docker ({reason})")
    else:
        report.warn(
            "stage plane",
            f"host ({reason}); install the docker Python package "
            "(python3 -m pip install 'docker>=5.0.3') for container stages; "
            "host stages run without repository masking",
        )


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).resolve())
    repo = _repo_path(cfg)
    report = Report()

    if sys.version_info >= (3, 12):
        report.ok("python", sys.version.split()[0])
    else:
        report.fail("python", f"{sys.version.split()[0]}; the method package requires >=3.12")
    try:
        import yaml  # noqa: F401
        report.ok("pyyaml", "importable")
    except ImportError:
        report.fail("pyyaml", "pip install pyyaml")

    if (repo / "pyproject.toml").is_file() and (repo / "src" / "component_method").is_dir():
        report.ok("method repository", str(repo))
    else:
        report.fail("method repository", f"{repo} is not the component-method repository")
        report.print()
        return 2

    if args.arm != "origin":
        _check_dsh(report, repo, args.arm)
    if os.environ.get("COMPONENT_DSH_PROFILE"):
        report.warn(
            "COMPONENT_DSH_PROFILE",
            f"set to {os.environ['COMPONENT_DSH_PROFILE']}; bench.py passes profile_name "
            "explicitly, but unset it to avoid confusion",
        )

    _check_credentials(report, repo, args.allow_missing)

    rc, out = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=60)
    if rc == 0:
        report.ok("docker", out.strip())
    else:
        report.fail("docker", out.strip()[-200:] or "docker daemon unreachable")

    if args.arm in (None, "method"):
        _check_stage_plane(report, repo)

    for name in _enabled_scenarios(cfg, args.scenario):
        sc = _scenario_cfg(cfg, name)
        image = str(sc.get("image") or "")
        if image and _image_exists(image):
            report.ok(f"image {name}", image)
        else:
            report.fail(f"image {name}", f"{image or '(unset)'}; run `bench.py env --scenario {name}`")
        if name == "ipp_to_vsipl":
            raw = str(sc.get("vsipl_root") or "").strip()
            if not raw:
                report.fail(
                    "vsipl root",
                    "VSIPL_ROOT is not set; point it at a jvsip tree with "
                    "include/vsip.h and lib/libvsip.a",
                )
            else:
                vsipl = Path(raw).expanduser()
                if vsipl.is_dir():
                    report.ok("vsipl root", str(vsipl))
                else:
                    report.fail("vsipl root", f"{vsipl} is not a directory")
        if name == "cuda_to_musa":
            transport = str(sc.get("transport") or "auto")
            remote = Path(str(sc.get("remote_config") or "env/remote.yaml"))
            if not remote.is_absolute():
                remote = ROOT / remote
            if transport == "local":
                report.warn("musa transport", "local: agent path only, no S4000 judge")
            elif remote.is_file():
                report.ok("musa remote config", str(remote))
            else:
                report.fail("musa remote config", f"missing {remote}; copy env/remote.yaml.example")

    arm = args.arm
    if arm in (None, "method"):
        prompts = {
            "workflow system": ROOT / "config" / "prompts" / "method_workflow_system.txt",
        }
        missing = [name for name, path in prompts.items() if not path.is_file()]
        if missing:
            report.fail("method prompts", "missing: " + ", ".join(missing))
        else:
            report.ok("method prompts", "fixed component-method workflow present")
        profile_root = _repo_path(cfg) / "dsh" / "profiles"
        for name in ("component-method", "component-method-migration"):
            path = profile_root / name / "cordis.patch.yml"
            if path.is_file():
                report.ok(f"dsh profile {name}", str(path))
            else:
                report.fail(f"dsh profile {name}", f"{path} is missing")

    report.print()
    counts = report.counts()
    print(f"DOCTOR ok={counts['OK']} warn={counts['WARN']} fail={counts['FAIL']}")
    if counts["FAIL"] and not args.allow_missing:
        return 2
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    verify = [sys.executable, str(ROOT / "tools" / "verify_task.py")]
    for parent in TASK_PARENTS.values():
        verify.extend(["--parent", parent])
    rc, out = _run(verify, timeout=600)
    print(out.rstrip())
    if rc != 0:
        return rc
    pins = [sys.executable, str(ROOT / "tools" / "check_pins.py"), "--offline"]
    if args.parent:
        for parent in args.parent:
            pins.extend(["--parent", parent])
    rc, out = _run(pins, timeout=1800)
    print(out.rstrip())
    return rc


def cmd_env(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).resolve())
    failures = 0
    for name in _enabled_scenarios(cfg, args.scenario):
        sc = _scenario_cfg(cfg, name)
        image = str(sc.get("image") or "")
        commands = sc.get("build") or []
        if not commands:
            print(f"MANUAL {name}: no build command in bench.yaml; build {image} yourself")
            continue
        for command in commands:
            command = [str(part) for part in command]
            print(f"RUN {name}: {' '.join(command)}", flush=True)
            rc, out = _run(command, timeout=args.timeout)
            print(out.rstrip())
            if rc != 0:
                print(f"FAIL {name}: build command exited {rc}", file=sys.stderr)
                failures += 1
                break
    return 1 if failures else 0


def cmd_gold(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).resolve())
    argv = [sys.executable, str(ROOT / "tools" / "gold_sanity.py")]
    scenarios = _enabled_scenarios(cfg, args.scenario)
    for name in scenarios:
        argv.extend(["--parent", TASK_PARENTS[name]])
    argv.extend(["--label", args.label])
    if args.only:
        for task in args.only:
            argv.extend(["--only", task])
    if args.exclude:
        for task in args.exclude:
            argv.extend(["--exclude", task])
    if args.level:
        for level in args.level:
            argv.extend(["--level", level])
    if args.dry_run:
        argv.append("--dry-run")
    if args.no_prepare:
        argv.append("--no-prepare")
    print("RUN " + " ".join(argv), flush=True)
    rc = subprocess.call(argv, cwd=str(ROOT))
    return rc


def _run_origin(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    scenarios = _enabled_scenarios(cfg, args.scenario)
    if args.all:
        scenarios = _enabled_scenarios(cfg, [])
    if args.smoke:
        # origin does not support the MUSA remote execution plane.
        scenarios = [name for name in scenarios if name != "cuda_to_musa"]
        args.only = ["l2_rubberband_fft", "l2_libuv_thread"]
        if args.runs is None:
            args.runs = 1
    label = args.label or ("origin-smoke" if args.smoke else "origin-all")
    report_root = _config_path(cfg, "report_root", "reports/bench")
    workspace_root = _config_path(cfg, "workspace_root", "reports/bench/workspaces")
    report_dir = report_root / label
    workspaces = workspace_root / label
    argv: List[str] = [
        sys.executable,
        str(ROOT / "tools" / "origin_trial.py"),
        "--label", label,
        "--report-dir", str(report_dir),
        "--workspace-root", str(workspaces),
        "--repository-root", str(_repo_path(cfg)),
    ]
    for name in scenarios:
        argv.extend(["--parent", TASK_PARENTS[name]])
    for task in args.only or []:
        argv.extend(["--only", task])
    for task in args.exclude or []:
        argv.extend(["--exclude", task])
    for level in args.level or []:
        argv.extend(["--level", level])
    budgets = dict(cfg.get("budgets") or {})
    for flag, key in (
        ("--runs", "runs"),
        ("--context-window", "context_window"),
        ("--prepare-timeout", "prepare_timeout"),
        ("--judge-timeout", "judge_timeout"),
    ):
        value = args.__dict__.get(key)
        if value is None:
            value = budgets.get(key)
        if value is not None:
            argv.extend([flag, str(value)])
    if args.origin_context_chars is not None:
        argv.extend(["--origin-context-chars", str(args.origin_context_chars)])
    if args.origin_max_output_tokens is not None:
        argv.extend(["--origin-max-output-tokens", str(args.origin_max_output_tokens)])
    if args.command_timeout is not None:
        argv.extend(["--timeout", str(args.command_timeout)])
    if args.model:
        argv.extend(["--model", args.model])
    if args.api_base:
        argv.extend(["--api-base", args.api_base])
    if args.api_key:
        argv.extend(["--api-key", args.api_key])
    if args.dry_run:
        argv.append("--dry-run")
    ipp = _scenario_cfg(cfg, "ipp_to_vsipl")
    if ipp.get("image"):
        argv.extend(["--ipp-image", str(ipp["image"])])
    if ipp.get("vsipl_root"):
        argv.extend(["--vsipl-root", str(Path(str(ipp["vsipl_root"])).expanduser())])
    kylin = _scenario_cfg(cfg, "windows_to_kylin")
    if kylin.get("image"):
        argv.extend(["--kylin-image", str(kylin["image"])])
    if args.dry_run:
        print("DRY  " + " ".join(argv))
    print(f"RUN arm=origin profile=(none) label={label} scenarios={','.join(scenarios)}", flush=True)
    return subprocess.call(argv, cwd=str(ROOT))


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).resolve())
    arm = args.arm
    if arm == "origin":
        return _run_origin(args, cfg)
    arm_cfg = dict((cfg.get("arms") or {}).get(arm) or {})
    profile = args.dsh_profile or str(arm_cfg.get("dsh_profile") or "")
    if not profile:
        print(f"ERROR no DSH profile configured for arm {arm}", file=sys.stderr)
        return 2

    scenarios = _enabled_scenarios(cfg, args.scenario)
    if args.all:
        scenarios = _enabled_scenarios(cfg, [])
    if args.smoke:
        # One task per scenario; the same three tasks for both arms.
        args.only = ["l2_rubberband_fft", "l2_libuv_thread", "b_l2_layer_norm"]
        if args.runs is None:
            args.runs = 1
    label = args.label or (f"{arm}-smoke" if args.smoke else f"{arm}-all")
    report_root = _config_path(cfg, "report_root", "reports/bench")
    workspace_root = _config_path(cfg, "workspace_root", "reports/bench/workspaces")
    report_dir = report_root / label
    workspaces = workspace_root / label

    budgets = dict(cfg.get("budgets") or {})
    argv: List[str] = [
        sys.executable,
        str(ROOT / "tools" / "migration_trial.py"),
        "--arm", arm,
        "--dsh-profile", profile,
        "--label", label,
        "--report-dir", str(report_dir),
        "--workspace-root", str(workspaces),
        "--repository-root", str(_repo_path(cfg)),
    ]
    for name in scenarios:
        argv.extend(["--parent", TASK_PARENTS[name]])
    for task in args.only or []:
        argv.extend(["--only", task])
    for task in args.exclude or []:
        argv.extend(["--exclude", task])
    for level in args.level or []:
        argv.extend(["--level", level])

    def budget(flag: str, key: str) -> None:
        value = args.__dict__.get(key)
        if value is None:
            value = budgets.get(flag.lstrip("-").replace("-", "_"))
        if value is not None:
            argv.extend([flag, str(value)])

    budget("--runs", "runs")
    budget("--step-limit", "step_limit")
    budget("--context-window", "context_window")
    budget("--max-output-tokens", "max_output_tokens")
    budget("--command-timeout", "command_timeout")
    budget("--total-timeout", "total_timeout")
    budget("--prepare-timeout", "prepare_timeout")
    budget("--judge-timeout", "judge_timeout")
    budget("--method-main-timeout", "method_main_timeout")
    budget("--method-step-limit", "method_step_limit")
    budget("--method-extraction-workers", "method_extraction_workers")
    budget("--method-review-workers", "method_review_workers")
    budget("--method-agent-timeout", "method_agent_timeout")

    if args.method_addendum:
        argv.extend(["--method-addendum", args.method_addendum])
    if args.method_prompt:
        argv.extend(["--method-prompt", args.method_prompt])
    if args.bundle:
        argv.extend(["--bundle", args.bundle])

    stage_image = args.method_stage_image or str(arm_cfg.get("stage_image") or "")
    if stage_image:
        argv.extend(["--method-stage-image", str(stage_image)])
    if args.method_stage_runtime != "auto":
        argv.extend(["--method-stage-runtime", args.method_stage_runtime])

    # Model routing is resolved by migration_trial itself: CLI flag, then the
    # repository-root .env, then the inherited environment.  Do not duplicate
    # it here -- that .env must keep winning over a stale shell export.
    if args.model:
        argv.extend(["--model", args.model])
    if args.api_base:
        argv.extend(["--api-base", args.api_base])
    if args.api_key:
        argv.extend(["--api-key", args.api_key])
    if args.fake_model:
        argv.append("--fake-model")
    if args.dry_run:
        argv.append("--dry-run")
    if args.no_prepare:
        argv.append("--no-prepare")
    if args.seed_gold:
        argv.append("--seed-gold")
    if args.keep_containers:
        argv.append("--keep-containers")

    ipp = _scenario_cfg(cfg, "ipp_to_vsipl")
    if ipp.get("image"):
        argv.extend(["--ipp-image", str(ipp["image"])])
    if ipp.get("vsipl_root"):
        argv.extend(["--vsipl-root", str(Path(str(ipp["vsipl_root"])).expanduser())])
    kylin = _scenario_cfg(cfg, "windows_to_kylin")
    if kylin.get("image"):
        argv.extend(["--kylin-image", str(kylin["image"])])
    musa = _scenario_cfg(cfg, "cuda_to_musa")
    if musa.get("remote_config"):
        argv.extend(["--remote-config", str(musa["remote_config"])])
    if args.musa_transport:
        argv.extend(["--musa-transport", args.musa_transport])
    elif musa.get("transport"):
        argv.extend(["--musa-transport", str(musa["transport"])])

    if args.dry_run:
        print("DRY  " + " ".join(argv))
    print(f"RUN arm={arm} profile={profile} label={label} scenarios={','.join(scenarios)}", flush=True)
    return subprocess.call(argv, cwd=str(ROOT))


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _attempt_rows(report_dir: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in sorted(report_dir.glob("*/run*/attempt.json")):
        value = _read_json(path)
        if not value:
            continue
        rows.append(value)
    return rows


def cmd_report(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).resolve())
    report_root = _config_path(cfg, "report_root", "reports/bench")
    report_dir = Path(args.label).expanduser()
    if not report_dir.is_absolute():
        report_dir = report_root / args.label
    summary = _read_json(report_dir / "summary.json") or {}
    rows = _attempt_rows(report_dir)
    if not summary and not rows:
        print(f"ERROR no report at {report_dir}", file=sys.stderr)
        return 2

    lines = [
        f"# Migration benchmark report: {args.label}",
        "",
        f"- arm: `{summary.get('arm', '?')}`",
        f"- condition: `{summary.get('condition', '?')}`",
        f"- dsh profile: `{summary.get('dsh_profile', '?')}`",
        f"- dsh: `{(summary.get('dsh_runtime') or {}).get('dsh_version', '?')}`"
        f"  node: `{(summary.get('dsh_runtime') or {}).get('node_version', '?')}`",
        f"- model: `{summary.get('model', '?')}`",
        f"- runs per task: {summary.get('runs_per_task', '?')}",
        "",
        "| task | scenario | level | run | status | agent | build | tests | api | seconds |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {task} | {scenario} | {level} | {run} | {status} | {agent} | {build} | "
            "{tests} | {api} | {seconds} |".format(
                task=row.get("task", ""),
                scenario=row.get("scenario", ""),
                level=row.get("level", ""),
                run=row.get("run", ""),
                status=row.get("status", ""),
                agent=row.get("agent_status", ""),
                build=row.get("build", ""),
                tests=row.get("tests", ""),
                api=row.get("api_removal", ""),
                seconds=row.get("duration_s", ""),
            )
        )
    counts = summary.get("counts") or {}
    lines += [
        "",
        f"SUMMARY pass={counts.get('pass', 0)} fail={counts.get('fail', 0)} "
        f"error={counts.get('error', 0)} skip={counts.get('skip', 0)}",
    ]
    (report_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"WROTE {report_dir / 'report.md'}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).resolve())
    report_root = _config_path(cfg, "report_root", "reports/bench")

    def load(label: str) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
        path = Path(label).expanduser()
        if not path.is_absolute():
            path = report_root / label
        summary = _read_json(path / "summary.json") or {}
        latest: Dict[str, Dict[str, Any]] = {}
        for row in _attempt_rows(path):
            task = str(row.get("task") or "")
            run = int(row.get("run") or 0)
            if task not in latest or run >= int(latest[task].get("run") or 0):
                latest[task] = row
        return summary, latest

    default_summary, default_rows = load(args.default_label)
    method_summary, method_rows = load(args.method_label)
    tasks = sorted(set(default_rows) | set(method_rows))
    if not tasks:
        print("ERROR no attempt records in either label", file=sys.stderr)
        return 2

    lines = [
        "# Paired comparison",
        "",
        f"- default: `{args.default_label}` (profile `{default_summary.get('dsh_profile', '?')}`)",
        f"- method: `{args.method_label}` (profile `{method_summary.get('dsh_profile', '?')}`, "
        f"main `{method_summary.get('method_profile', '?')}`)",
        "",
        "| task | default | method | delta |",
        "|---|---|---|---|",
    ]
    default_pass = method_pass = both = 0
    for task in tasks:
        d = default_rows.get(task, {})
        m = method_rows.get(task, {})
        ds = str(d.get("status", "-"))
        ms = str(m.get("status", "-"))
        default_pass += ds == "pass"
        method_pass += ms == "pass"
        both += ds == "pass" and ms == "pass"
        delta = "-" if ds == ms else ("better" if ms == "pass" else "worse")
        lines.append(f"| {task} | {ds} | {ms} | {delta} |")
    usable_bundles = [
        row for row in method_rows.values()
        if (row.get("component_bundle") or {}).get("ok")
    ]
    components = sum(
        int((row.get("component_bundle") or {}).get("component_count") or 0)
        for row in usable_bundles
    )
    # B attempts that never reached judging produced no usable bundle or lost
    # the method runtime; they are invalid B results, not failures of the task.
    # A validated empty selection is different: retrieval abstained because no
    # library component covers the task, which is a legitimate outcome and is
    # reported on its own line.
    def _no_match(row: Dict[str, Any]) -> bool:
        bundle = row.get("component_bundle") or {}
        return bool(bundle.get("ok")) and int(bundle.get("component_count") or 0) == 0

    no_match = sum(1 for row in method_rows.values() if _no_match(row))
    invalid_method = sum(
        1
        for row in method_rows.values()
        if str(row.get("status")) == "error"
        and not (row.get("judge") or {}).get("report")
        and not _no_match(row)
    )
    lines += [
        "",
        f"TASKS {len(tasks)}  default_pass={default_pass}  method_pass={method_pass}  both={both}",
        (
            f"BUNDLES attempts={len(method_rows)} "
            f"usable={len(usable_bundles)} components={components}"
        ),
        (
            f"RETRIEVAL_NO_MATCH {no_match} "
            "(validated empty selection; method arm has nothing to transfer)"
        ),
        (
            f"INVALID_METHOD {invalid_method} "
            "(workflow unavailable or no usable bundle; not counted as a method result)"
        ),
    ]
    print("\n".join(lines))
    (report_root / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"WROTE {report_root / 'comparison.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check both arms' prerequisites")
    doctor.add_argument("--arm", choices=["default", "method", "origin"])
    doctor.add_argument("--scenario", action="append", default=[])
    doctor.add_argument("--allow-missing", action="store_true",
                        help="missing credentials/images warn instead of fail")
    doctor.set_defaults(func=cmd_doctor)

    verify = sub.add_parser("verify", help="static task-package and pin checks")
    verify.add_argument("--parent", action="append", default=[])
    verify.set_defaults(func=cmd_verify)

    env = sub.add_parser("env", help="build the images declared in bench.yaml")
    env.add_argument("--scenario", action="append", default=[])
    env.add_argument("--timeout", type=int, default=7200)
    env.set_defaults(func=cmd_env)

    gold = sub.add_parser("gold", help="run the gold positive controls")
    gold.add_argument("--scenario", action="append", default=[])
    gold.add_argument("--only", action="append", default=[])
    gold.add_argument("--exclude", action="append", default=[])
    gold.add_argument("--level", action="append", default=[])
    gold.add_argument("--label", default="gold")
    gold.add_argument("--dry-run", action="store_true")
    gold.add_argument("--no-prepare", action="store_true")
    gold.set_defaults(func=cmd_gold)

    run = sub.add_parser("run", help="run one arm over the selected tasks")
    run.add_argument("--arm", choices=["default", "method", "origin"], required=True)
    run.add_argument("--scenario", action="append", default=[])
    run.add_argument("--all", action="store_true", help="all enabled scenarios")
    run.add_argument("--smoke", action="store_true",
                     help="one task per scenario (l2_rubberband_fft / l2_libuv_thread / b_l2_layer_norm)")
    run.add_argument("--only", action="append", default=[])
    run.add_argument("--exclude", action="append", default=[])
    run.add_argument("--level", action="append", default=[])
    run.add_argument("--label", default="")
    run.add_argument("--runs", type=int)
    run.add_argument("--step-limit", type=int)
    run.add_argument("--context-window", type=int)
    run.add_argument("--max-output-tokens", type=int)
    run.add_argument("--command-timeout", type=int)
    run.add_argument("--total-timeout", type=int)
    run.add_argument("--prepare-timeout", type=int)
    run.add_argument("--no-prepare", action="store_true",
                     help="reuse the task work/ tree prepared by an earlier run")
    run.add_argument("--judge-timeout", type=int)
    run.add_argument("--method-main-timeout", type=int)
    run.add_argument("--method-step-limit", type=int)
    run.add_argument("--method-extraction-workers", type=int)
    run.add_argument("--method-review-workers", type=int)
    run.add_argument("--method-agent-timeout", type=int)
    run.add_argument("--method-stage-image", default="")
    run.add_argument("--method-stage-runtime", choices=("auto", "docker", "host"),
                     default="auto",
                     help="nested method stage plane; auto probes the Docker API and "
                          "falls back to host when the daemon or its Python client is "
                          "unavailable")
    run.add_argument("--dsh-profile", default="")
    run.add_argument("--method-addendum", default="")
    run.add_argument("--method-prompt", default="",
                     help="replace the fixed method workflow prompt (retrieval-only "
                          "or extraction-only conditions)")
    run.add_argument("--bundle", default="",
                     help="prebuilt component library staged for the method task's "
                          "retrieval stage (requires --method-prompt)")
    run.add_argument("--model", default="")
    run.add_argument("--api-base", default="")
    run.add_argument("--api-key", default="")
    run.add_argument("--fake-model", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--seed-gold", action="store_true")
    run.add_argument("--origin-context-chars", type=int, default=None)
    run.add_argument("--origin-max-output-tokens", type=int, default=None)
    run.add_argument("--keep-containers", action="store_true")
    run.add_argument("--musa-transport", choices=["auto", "ssh", "local"])
    run.set_defaults(func=cmd_run)

    report = sub.add_parser("report", help="render one label's attempt records")
    report.add_argument("--label", required=True)
    report.set_defaults(func=cmd_report)

    compare = sub.add_parser("compare", help="paired default-vs-method table")
    compare.add_argument("--default-label", required=True)
    compare.add_argument("--method-label", required=True)
    compare.set_defaults(func=cmd_compare)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _load_local_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())