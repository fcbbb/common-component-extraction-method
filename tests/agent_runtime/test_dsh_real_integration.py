import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time

import pytest

from component_method.agent_runtime.contracts import AgentRunRequest
from component_method.agent_runtime.dsh_headless import DshHeadlessBackend


pytestmark = pytest.mark.skipif(
    os.environ.get("COMPONENT_DSH_REAL_INTEGRATION") != "1",
    reason="set COMPONENT_DSH_REAL_INTEGRATION=1 to run the Docker-backed DSH POC",
)


class _ModelHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).requests.append(payload)
        request_number = len(type(self).requests)
        if request_number == 1:
            content = None
            tool_call = {
                "index": 0,
                "id": "call-inspect",
                "type": "function",
                "function": {
                    "name": "controlled_bash",
                    "arguments": json.dumps(
                        {
                            "command": "pwd; cat sentinel.txt; env",
                            "cwd": "/testbed",
                            "timeout_seconds": 10,
                        }
                    ),
                },
            }
            finish_reason = "tool_calls"
        elif request_number == 2:
            content = None
            tool_call = {
                "index": 0,
                "id": "call-submit",
                "type": "function",
                "function": {
                    "name": "controlled_bash",
                    "arguments": json.dumps(
                        {
                            "command": (
                                "printf valid > /component-output/result.txt; "
                                "printf 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\\n'"
                            ),
                            "cwd": "/testbed",
                            "timeout_seconds": 10,
                        }
                    ),
                },
            }
            finish_reason = "tool_calls"
        else:
            content = "resumed"
            tool_call = None
            finish_reason = "stop"

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        created = int(time.time())
        delta = {"role": "assistant"}
        if content is not None:
            delta["content"] = content
        if tool_call is not None:
            delta["tool_calls"] = [tool_call]
        chunks = [
            {
                "id": f"chatcmpl-{request_number}",
                "object": "chat.completion.chunk",
                "created": created,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": f"chatcmpl-{request_number}",
                "object": "chat.completion.chunk",
                "created": created,
                "model": "fixture-model",
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": finish_reason}
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 3,
                    "total_tokens": 13,
                },
            },
        ]
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def _request(output_dir, container_name, *, resume_session_id=None, task="inspect and submit"):
    return AgentRunRequest(
        run_id="real-integration",
        role="extraction",
        model="fixture-model",
        system_prompt="Use controlled_bash to inspect the workspace and submit valid files.",
        task_prompt=task,
        output_dir=output_dir,
        container_name=container_name,
        container_cwd="/testbed",
        command_timeout_seconds=30,
        total_timeout_seconds=60,
        step_limit=10,
        submission_mode="files",
        submission_role="extraction",
        resume_session_id=resume_session_id,
    )


def test_real_dsh_headless_tool_loop_and_resume(tmp_path):
    docker = pytest.importorskip("docker")
    repository = Path(__file__).resolve().parents[2]
    node_bin = Path(
        os.environ.get(
            "COMPONENT_DSH_NODE_BIN",
            "/home/fcbbbb/.nvm/versions/node/v24.9.0/bin/node",
        )
    )
    if not node_bin.is_file():
        pytest.skip("pinned Node.js binary is unavailable")
    workspace = tmp_path / "workspace"
    submission = tmp_path / "submission"
    workspace.mkdir()
    submission.mkdir()
    submission.chmod(0o777)
    (workspace / "sentinel.txt").write_text("workspace-visible\n")
    checker = tmp_path / "check_output.py"
    checker.write_text(
        "from pathlib import Path\n"
        "target = Path('/component-output/result.txt')\n"
        "if not target.is_file() or target.read_text().strip() != 'valid':\n"
        "    print('Submission check failed')\n"
        "    raise SystemExit(1)\n"
        "print('valid')\n"
    )
    container_name = f"component-dsh-real-{os.getpid()}-{time.time_ns()}"
    client = docker.from_env()
    container = client.containers.create(
        image=os.environ.get(
            "COMPONENT_DSH_DOCKER_TEST_IMAGE",
            "task-guided-demo10/elastic-curator:1085-runtime",
        ),
        entrypoint=[],
        name=container_name,
        command=["sleep", "infinity"],
        working_dir="/testbed",
        volumes={
            str(workspace): {"bind": "/testbed", "mode": "ro"},
            str(submission): {"bind": "/component-output", "mode": "rw"},
            str(checker): {
                "bind": "/component-tools/check_output.py",
                "mode": "ro",
            },
        },
        network_mode="none",
        read_only=True,
        tmpfs={"/tmp": "rw,nosuid,nodev,size=64m,mode=1777"},
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    _ModelHandler.requests = []
    server_thread.start()
    output_dir = tmp_path / "run"
    try:
        container.start()
        backend = DshHeadlessBackend(
            api_key="fixture-key",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            repository_root=repository,
            node_bin=node_bin,
            host_environment={"NO_PROXY": "127.0.0.1,localhost"},
        )
        result = backend.run(_request(output_dir, container_name))

        assert result.status == "Submitted"
        assert result.completion_validated is True
        assert result.session_id
        assert [call["tool"] for call in result.tool_calls] == [
            "controlled_bash",
            "controlled_bash",
        ]
        assert "workspace-visible" in result.tool_calls[0]["result"]
        assert "OPENAI_API_KEY" not in result.tool_calls[0]["result"]
        assert all(
            [tool["function"]["name"] for tool in request["tools"]]
            == ["controlled_bash"]
            for request in _ModelHandler.requests[:2]
        )

        resumed = backend.run(
            _request(
                output_dir,
                container_name,
                resume_session_id=result.session_id,
                task="reply with resumed and do not submit",
            )
        )
        assert resumed.session_id == result.session_id
        assert resumed.status == "NoValidatedSubmission"
        assert resumed.final_output == "resumed"
        assert (output_dir / "dsh_events.jsonl").read_text().count('"type":"final"') == 2
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        try:
            container.remove(force=True)
        except Exception:
            pass
