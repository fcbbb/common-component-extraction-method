"""S1 verbatim signal: normalized-token clone detection (CCFinder-style, python-native).

Names are kept verbatim so this captures true copy-paste sharing; strings/numbers
collapse to placeholders so only literals differ.  Compare unit-level streams across
files, find maximal shared runs, then aggregate evidence per file pair.
"""
from __future__ import annotations

import io
import tokenize
from collections import defaultdict
from typing import Any

from component_method.signal_analysis.ngrams import NgramStream
from .units import Unit, container_of_row, parse_units

DEFAULT_K = 6
DEFAULT_MIN_RUN = 12


def _normalized_tokens(source: str) -> list[tuple[str, int]]:
    """(token_text, start_row) pairs, comments/whitespace stripped, STRING->str NUMBER->num."""
    out: list[tuple[str, int]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type in (tokenize.ENCODING, tokenize.NEWLINE, tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
                continue
            text = tok.string
            if tok.type == tokenize.STRING:
                text = "str"
            elif tok.type == tokenize.NUMBER:
                text = "num"
            out.append((text, tok.start[0]))
    except (tokenize.TokenError, IndentationError):
        pass
    return out


def _unit_streams(file_id: str, source: str) -> tuple[list[NgramStream], list[Unit] | None]:
    tree, units, error = parse_units(source)
    if tree is None or units is None:
        # Unparseable file: fall back to a single module-level stream.
        tokens = _normalized_tokens(source)
        return [NgramStream(file_id, "module", [t for t, _ in tokens], [r for _, r in tokens])], None
    raw = _normalized_tokens(source)
    buckets: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for text, row in raw:
        container = container_of_row(units, row)
        buckets[container.unit_id].append((text, row))
    return [NgramStream(file_id, unit_id, [t for t, _ in pairs], [r for _, r in pairs]) for unit_id, pairs in buckets.items()], units
