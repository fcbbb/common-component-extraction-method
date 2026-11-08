"""Test outcomes required by the bundled official log parsers."""

from enum import Enum


class TestStatus(Enum):
    FAILED = "FAILED"
    PASSED = "PASSED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"
