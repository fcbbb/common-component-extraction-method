"""Execute trusted backend invocations inside a pinned, offline container."""

import os

import docker
from requests.exceptions import ReadTimeout

from component_method.languages.contracts import ProcessResult


def execute_invocation(invocation, workspace, repository, *, client=None):
    if client is None:
        owned_client = docker.from_env()
        try:
            return execute_invocation(invocation, workspace, repository, client=owned_client)
        finally:
            owned_client.close()
    if not repository.runtime_image:
        raise ValueError("multi-language validation requires the matching repository image")
    image = client.images.get(repository.runtime_image)
    if not image.id.startswith("sha256:"):
        raise ValueError("runtime image must resolve to an immutable image ID")
    mounts = {str(repository.resolved_root()): {"bind": "/repository", "mode": "ro"}}
    for source, destination, mode in (("artifact", "/artifact", "ro"), ("smoke", "/smoke", "ro"),
                                      ("driver", "/driver", "ro"), ("build", "/work", "rw")):
        mounts[str((workspace / source).resolve())] = {"bind": destination, "mode": mode}
    container = client.containers.run(
        image.id, list(invocation.argv), detach=True, entrypoint=[], working_dir=invocation.workdir,
        user=f"{os.getuid()}:{os.getgid()}",
        environment=invocation.environment, volumes=mounts, network_mode="none", read_only=True,
        cap_drop=["ALL"], security_opt=["no-new-privileges:true"], pids_limit=128,
        mem_limit="1g", nano_cpus=2_000_000_000, tmpfs={"/tmp": "rw,nosuid,size=64m"},
        log_config=docker.types.LogConfig(type="json-file", config={"max-size": "1m", "max-file": "1"}),
    )
    try:
        try:
            status = container.wait(timeout=invocation.timeout_seconds)["StatusCode"]
            timed_out = False
        except ReadTimeout:
            container.kill()
            status, timed_out = 124, True
        stdout = container.logs(stdout=True, stderr=False)[-1048576:].decode(errors="replace")
        stderr = container.logs(stdout=False, stderr=True)[-1048576:].decode(errors="replace")
        return ProcessResult(status, stdout, stderr, timed_out), {
            "image_id": image.id, "network_mode": "none", "repository_read_only": True,
            "artifact_read_only": True, "limits": {"pids": 128, "memory": "1g", "cpus": 2},
        }
    finally:
        container.remove(force=True)
