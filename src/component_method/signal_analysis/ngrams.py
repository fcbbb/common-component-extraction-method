"""Generic shared-run detection over token streams (S1 verbatim / S2 skeleton share this core)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NgramStream:
    """An ordered token sequence belonging to one code unit of one file."""

    file_id: str
    unit_id: str  # e.g. "module", "func:solve", "class:Parser"
    tokens: list[str] = field(default_factory=list)
    rows: list[int] = field(default_factory=list)  # 1-based start row per token, aligned with tokens


@dataclass
class SharedRun:
    file_a: str
    unit_a: str
    file_b: str
    unit_b: str
    tokens: int
    start_a: int
    end_a: int  # exclusive
    start_b: int
    end_b: int  # exclusive
    rows_a: tuple[int, int]  # (min, max) 1-based rows spanned in file_a
    rows_b: tuple[int, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_a": self.file_a,
            "unit_a": self.unit_a,
            "file_b": self.file_b,
            "unit_b": self.unit_b,
            "tokens": self.tokens,
            "rows_a": [self.rows_a[0], self.rows_a[1]],
            "rows_b": [self.rows_b[0], self.rows_b[1]],
        }


def _rows_span(stream: NgramStream, start: int, end: int) -> tuple[int, int]:
    lo = min(stream.rows[start:end]) if start < end else 0
    hi = max(stream.rows[start:end]) if start < end else 0
    return (lo, hi)


def find_shared_runs(
    streams: list[NgramStream],
    k: int = 6,
    min_run: int = 12,
    *,
    max_stream_frequency: int = 0,
) -> list[SharedRun]:
    """Maximal runs of identical consecutive tokens between units of *different* files.

    Every k-gram is indexed; matching seeds are extended left and right to maximal
    equality runs.  Overlapping duplicate seeds for the same unit pair are dropped
    via accepted-interval tracking, so each maximal run is reported once.
    """
    index: dict[tuple[str, ...], list[tuple[int, int]]] = {}
    for si, stream in enumerate(streams):
        tokens = stream.tokens
        if len(tokens) < k:
            continue
        for pos in range(len(tokens) - k + 1):
            index.setdefault(tuple(tokens[pos : pos + k]), []).append((si, pos))

    runs: list[SharedRun] = []
    # Accepted maximal intervals per stream pair, keyed (si_a, si_b) with si_a < si_b.
    # Track both coordinates so repeated matches cannot count the same token span twice
    # on either side of a unit pair.
    accepted: dict[tuple[int, int], list[tuple[int, int, int, int]]] = {}
    for occurrences in index.values():
        by_stream: dict[int, list[int]] = {}
        for si, pos in occurrences:
            by_stream.setdefault(si, []).append(pos)
        if max_stream_frequency and len(by_stream) > max_stream_frequency:
            # Ubiquitous syntax n-grams (e.g. C++ punctuation triples) create
            # quadratic pair work without adding discriminative evidence.
            continue
        stream_ids = sorted(by_stream)
        for i in range(len(stream_ids)):
            for j in range(i + 1, len(stream_ids)):
                sa_i, sa_j = stream_ids[i], stream_ids[j]
                stream_a = streams[sa_i]
                stream_b = streams[sa_j]
                if stream_a.file_id == stream_b.file_id:
                    continue
                tokens_a, tokens_b = stream_a.tokens, stream_b.tokens
                key = (sa_i, sa_j)
                covered = accepted.setdefault(key, [])
                for p in by_stream[sa_i]:
                    if any(start_a <= p < end_a for start_a, end_a, _, _ in covered):
                        continue
                    for q in by_stream[sa_j]:
                        if any(start_b <= q < end_b for _, _, start_b, end_b in covered):
                            continue
                        # extend left
                        start_p, start_q = p, q
                        while (
                            start_p > 0
                            and start_q > 0
                            and tokens_a[start_p - 1] == tokens_b[start_q - 1]
                        ):
                            start_p -= 1
                            start_q -= 1
                        # extend right
                        end_p, end_q = p + 1, q + 1
                        while (
                            end_p < len(tokens_a)
                            and end_q < len(tokens_b)
                            and tokens_a[end_p] == tokens_b[end_q]
                        ):
                            end_p += 1
                            end_q += 1
                        overlaps_accepted = any(
                            start_p < accepted_end_a
                            and accepted_start_a < end_p
                            or start_q < accepted_end_b
                            and accepted_start_b < end_q
                            for accepted_start_a, accepted_end_a, accepted_start_b, accepted_end_b in covered
                        )
                        if end_p - start_p >= min_run and not overlaps_accepted:
                            covered.append((start_p, end_p, start_q, end_q))
                            runs.append(
                                SharedRun(
                                    file_a=stream_a.file_id,
                                    unit_a=stream_a.unit_id,
                                    file_b=stream_b.file_id,
                                    unit_b=stream_b.unit_id,
                                    tokens=end_p - start_p,
                                    start_a=start_p,
                                    end_a=end_p,
                                    start_b=start_q,
                                    end_b=end_q,
                                    rows_a=_rows_span(stream_a, start_p, end_p),
                                    rows_b=_rows_span(stream_b, start_q, end_q),
                                )
                            )
                            break  # p is covered; move to next seed
    return runs


def pair_shared_tokens(runs: list[SharedRun]) -> dict[tuple[str, str], int]:
    """Sum of shared run tokens per unordered file pair."""
    acc: dict[tuple[str, str], int] = {}
    for run in runs:
        key = tuple(sorted([run.file_a, run.file_b]))
        acc[key] = acc.get(key, 0) + run.tokens
    return acc
