"""Compatibility import for historical Python component cards."""
import sys
from component_method.languages.python import publication as _implementation

sys.modules[__name__] = _implementation
