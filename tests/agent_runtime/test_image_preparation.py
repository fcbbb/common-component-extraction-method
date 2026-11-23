from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import docker
import pytest

from component_method.task_execution.runtime_support import build_helpers


class _BlockingImages:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def get(self, tag):
        raise docker.errors.ImageNotFound(tag, None)

    def build(self, **kwargs):
        self.started.set()
        self.release.wait(10)
        return SimpleNamespace(id="sha256:built"), []


class _ReadyImages:
    def get(self, tag):
        raise docker.errors.ImageNotFound(tag, None)

    def build(self, **kwargs):
        return SimpleNamespace(id="sha256:built"), []


def test_missing_image_is_built_within_the_deadline():
    client = SimpleNamespace(images=_ReadyImages())

    image_id, tag = build_helpers._ensure_image(client, timeout=5)

    assert image_id == "sha256:built"
    assert tag == build_helpers.IMAGE_TAG


def test_a_stalled_build_fails_fast_instead_of_hanging():
    images = _BlockingImages()
    client = SimpleNamespace(images=images)

    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="did not finish within") as caught:
            build_helpers._ensure_image(client, timeout=0.1)
    finally:
        images.release.set()

    assert time.monotonic() - started < 5
    assert build_helpers.IMAGE_BUILD_TIMEOUT_ENVIRONMENT in str(caught.value)


def test_build_errors_are_reported_with_the_tag():
    class _Failing:
        def get(self, tag):
            raise docker.errors.ImageNotFound(tag, None)

        def build(self, **kwargs):
            raise docker.errors.APIError("registry unreachable")

    client = SimpleNamespace(images=_Failing())

    with pytest.raises(RuntimeError, match=build_helpers.IMAGE_TAG):
        build_helpers._ensure_image(client, timeout=5)