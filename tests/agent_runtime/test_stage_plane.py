from __future__ import annotations

import sys
from types import ModuleType

from component_method.agent_runtime import stage_plane
from component_method.task_execution.runtime_support import build_helpers


def _reset() -> None:
    stage_plane._resolve.cache_clear()
    clear = getattr(stage_plane._docker_plane_status, "cache_clear", None)
    if clear is not None:
        clear()


def test_explicit_plane_skips_the_docker_probe(monkeypatch):
    def probe() -> tuple[bool, str]:
        raise AssertionError("an explicit plane must not probe Docker")

    monkeypatch.setattr(stage_plane, "_docker_plane_status", probe)
    monkeypatch.setenv(stage_plane.STAGE_RUNTIME_ENVIRONMENT, "docker")
    _reset()

    assert stage_plane.stage_runtime() == "docker"
    assert stage_plane.stage_runtime_reason() == "explicit"

    monkeypatch.setenv(stage_plane.STAGE_RUNTIME_ENVIRONMENT, "host")
    _reset()

    assert stage_plane.stage_runtime() == "host"
    assert stage_plane.stage_runtime_reason() == "explicit"


def test_auto_uses_docker_when_the_probe_succeeds(monkeypatch):
    monkeypatch.delenv(stage_plane.STAGE_RUNTIME_ENVIRONMENT, raising=False)
    monkeypatch.setattr(
        stage_plane, "_docker_plane_status", lambda: (True, "docker daemon reachable")
    )
    _reset()

    assert stage_plane.stage_runtime() == "docker"
    assert stage_plane.stage_runtime_reason() == "auto: docker daemon reachable"


def test_auto_falls_back_when_the_runtime_image_is_not_ready(monkeypatch):
    class _Client:
        def ping(self):
            return True

        def close(self):
            pass

    docker_module = ModuleType("docker")
    docker_module.from_env = lambda timeout=2: _Client()
    monkeypatch.setitem(sys.modules, "docker", docker_module)

    def unavailable(client):
        raise RuntimeError("building the image did not finish within 300s")

    monkeypatch.setattr(build_helpers, "_ensure_image", unavailable)
    monkeypatch.setenv(stage_plane.STAGE_RUNTIME_ENVIRONMENT, "auto")
    _reset()

    assert stage_plane.stage_runtime() == "host"
    reason = stage_plane.stage_runtime_reason()
    assert reason.startswith("auto: docker runtime image not ready")
    assert "did not finish within" in reason


def test_auto_uses_docker_when_the_runtime_image_is_ready(monkeypatch):
    class _Client:
        def ping(self):
            return True

        def close(self):
            pass

    docker_module = ModuleType("docker")
    docker_module.from_env = lambda timeout=2: _Client()
    monkeypatch.setitem(sys.modules, "docker", docker_module)
    monkeypatch.setattr(
        build_helpers, "_ensure_image", lambda client: ("sha256:ready", "tag")
    )
    monkeypatch.setenv(stage_plane.STAGE_RUNTIME_ENVIRONMENT, "auto")
    _reset()

    assert stage_plane.stage_runtime() == "docker"
    assert stage_plane.stage_runtime_reason() == (
        "auto: docker daemon reachable and runtime image ready"
    )


def test_auto_falls_back_to_host_without_the_docker_client(monkeypatch):
    monkeypatch.setenv(stage_plane.STAGE_RUNTIME_ENVIRONMENT, "auto")
    monkeypatch.setattr(
        stage_plane,
        "_docker_plane_status",
        lambda: (False, "python docker package unavailable"),
    )
    _reset()

    assert stage_plane.stage_runtime() == "host"
    assert stage_plane.stage_runtime_reason() == (
        "auto: python docker package unavailable"
    )