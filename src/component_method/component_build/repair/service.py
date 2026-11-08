"""Compatibility API for v1 repair callers; v2 repairs use artifact records."""
import sys
from component_method.languages.python import legacy_repair as _implementation

sys.modules[__name__] = _implementation
