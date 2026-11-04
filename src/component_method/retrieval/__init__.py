"""Task-aware retrieval over a frozen validated component library."""

from .service import (
    RetrievalRequest,
    build_component_catalog,
    render_retrieval_task,
    run_retrieval_agent,
)
from .selection_bundle import materialize_selected_bundle
from .submission import validate_coverage, validate_selection

__all__ = [
    "RetrievalRequest",
    "build_component_catalog",
    "materialize_selected_bundle",
    "render_retrieval_task",
    "run_retrieval_agent",
    "validate_coverage",
    "validate_selection",
]
