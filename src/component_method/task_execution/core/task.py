"""Run one task attempt through the DSH backend."""

import argparse
import traceback
from pathlib import Path

from component_method.agent_runtime import selected_backend_name

from common import OUT, agent_rows, digest, hashes, now, read, rows, verify_inputs, write
from task_dsh import run_dsh_task


def _failure_payload(task_id, arm, status, error, agent_backend, diagnostics=None):
    payload = {
        "instance_id": task_id,
        "arm": arm,
        "status": status,
        "patch": "",
        "patch_available": False,
        "finished_at": now(),
        "component_usage": [],
        "model_calls": 0,
        "input_tokens": None,
        "output_tokens": None,
        "reported_cost_usd": None,
        "completion_validated": False,
        "agent_backend": agent_backend,
        "error": error,
    }
    if diagnostics is not None:
        payload["diagnostics"] = diagnostics
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--arm", choices=["direct", "components"], required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()

    agent_backend = selected_backend_name()
    verify_inputs()
    out = OUT / "tasks" / args.arm / args.task
    out.mkdir(parents=True, exist_ok=True)
    if (out / "result.json").exists():
        print("Existing attempt retained", args.task, args.arm)
        return

    official = next(row for row in rows() if row["instance_id"] == args.task)
    original = next(row for row in agent_rows() if row["instance_id"] == args.task)
    if args.bundle:
        manifest = read(args.bundle / "manifest.json")
        assert manifest["repository"] == official["repo"].lower()
        binding = read(OUT / "bindings" / (args.task + ".json"))
        assert binding["base_commit"] == official["base_commit"]
        assert binding["bundle_sha256"] == digest(hashes(args.bundle))

    write(out / "state.json", {"status": "starting", "started_at": now(), "arm": args.arm})
    try:
        payload = run_dsh_task(
            task_id=args.task,
            arm=args.arm,
            image=args.image,
            bundle=args.bundle,
            official=official,
            problem_statement=original["problem_statement"],
            out=out,
        )
    except KeyboardInterrupt:
        payload = _failure_payload(
            args.task,
            args.arm,
            "StoppedByUser",
            "Task stopped by user.",
            agent_backend,
        )
    except Exception as error:
        traceback.print_exc()
        payload = _failure_payload(
            args.task,
            args.arm,
            type(error).__name__,
            str(error),
            agent_backend,
            {"traceback": traceback.format_exc()},
        )

    write(out / "result.json", payload)
    write(out / "state.json", {"status": payload["status"], "finished_at": now()})
    print(args.task, args.arm, payload["status"], flush=True)


if __name__ == "__main__":
    main()
