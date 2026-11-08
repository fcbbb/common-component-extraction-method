"""Compatibility API for saved v1 reviews and existing controller imports.

Artifact v2 validation is implemented in artifact_service; the compatibility
entrypoints dispatch structured artifacts there before interpreting v1 fields.
"""
import sys
from component_method.languages.python import legacy_validation as _implementation

sys.modules[__name__] = _implementation
