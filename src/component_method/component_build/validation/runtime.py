"""Compatibility import for historical Python validation callers.

Artifact v2 execution uses validation.execution and backend drivers.
"""
import sys
from component_method.languages.python import legacy_runtime as _implementation

sys.modules[__name__] = _implementation
