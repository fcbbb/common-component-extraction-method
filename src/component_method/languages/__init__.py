"""Language capabilities and versioned pipeline contracts."""

from .registry import LanguageRegistry, default_registry, normalize_language_config

__all__ = ["LanguageRegistry", "default_registry", "normalize_language_config"]
