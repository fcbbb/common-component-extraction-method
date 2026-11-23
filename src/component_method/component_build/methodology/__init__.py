"""Transformation (methodology) extraction pipeline.

Public entry points:

* :func:`contracts.normalize_response` — validate one extraction response;
* :func:`curate.curate` — deterministic admission across the history corpus;
* :func:`review.review_entries` — independent agent review;
* :func:`publish.publish` — write a ``methodology-1`` library;
* :func:`pipeline.main` — the CLI that runs the stages in order.
"""
from .contracts import (  # noqa: F401
    TRANSFORMATION_SCHEMA,
    normalize_transformation,
    render_readme,
    validate_transformation,
)
from .corpus import load_corpus, verify_corpus  # noqa: F401
from .curate import curate  # noqa: F401
from .publish import publish, verify_library  # noqa: F401
from .review import review_entries  # noqa: F401

__all__ = [
    "TRANSFORMATION_SCHEMA",
    "curate",
    "load_corpus",
    "normalize_transformation",
    "publish",
    "render_readme",
    "review_entries",
    "validate_transformation",
    "verify_corpus",
    "verify_library",
]