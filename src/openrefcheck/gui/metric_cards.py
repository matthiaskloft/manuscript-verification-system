"""Shared top-row metric card data (verified/no-match/duplicate/review/retracted
counts), used by both the References and Summary screens so the same numbers don't
have to be computed twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from openrefcheck.gui.models import ReferenceResult

# Keys that double as the References screen's status filter — clicking one of these
# cards both shows its number and filters the table, instead of repeating the same
# status vocabulary in two separate rows.
#
# "retracted" is on this list although it is not a status: a reference can be verified,
# duplicated *and* retracted, so it filters across the others rather than beside them.
# It is here because a reviewer who sees the count needs one click to see which ones —
# a number they cannot act on is the least useful way to report a retraction.
FILTER_CARD_KEYS = frozenset({"all", "verified", "review", "halluc", "dup", "retracted"})

CARD_SPECS: list[tuple[str, str, str]] = [
    ("all", "All references", "#8a877f"),
    ("verified", "Verified references", "#5d8a4c"),
    ("review", "Needs manual review", "#c99526"),
    ("halluc", "No match found", "#bf4a2e"),
    ("dup", "Duplicates / incomplete", "#98958d"),
    ("retracted", "Retraction warnings", "#8a3c6b"),
]


@dataclass(frozen=True)
class ResultMetrics:
    n_total: int
    n_verified: int
    n_halluc: int
    n_dup: int
    n_review: int
    n_unchecked: int
    n_retracted: int


def compute_metrics(results: list[ReferenceResult]) -> ResultMetrics:
    n_total = len(results)
    n_unchecked = sum(1 for r in results if r.status == "unchecked")
    return ResultMetrics(
        n_total=n_total,
        n_verified=sum(1 for r in results if r.status == "verified"),
        n_halluc=sum(1 for r in results if r.status == "halluc"),
        n_dup=sum(1 for r in results if r.status == "dup"),
        n_review=sum(1 for r in results if r.status in ("review", "unchecked")),
        n_unchecked=n_unchecked,
        # `retracted` is True / False / None (never checked), and only True counts. `is`
        # rather than truthiness so the tri-state stays visible to anyone editing this.
        n_retracted=sum(1 for r in results if r.retracted is True),
    )


def card_value_note(key: str, metrics: ResultMetrics) -> tuple[str, str]:
    """(value, note) text for a given card key, matching the PySide apply_metrics()."""
    n_total = metrics.n_total
    if key == "all":
        return str(n_total), "in this document"
    if key == "verified":
        pct = round(metrics.n_verified / n_total * 100) if n_total else 0
        return f"{metrics.n_verified} / {n_total}", f"{pct} % of the list"
    if key == "halluc":
        return str(metrics.n_halluc), "no resolvable match"
    if key == "dup":
        return str(metrics.n_dup), f"{metrics.n_dup} duplicate(s)"
    if key == "review":
        return str(metrics.n_review), "incl. not-yet-checked"
    if key == "retracted":
        return str(metrics.n_retracted), "retraction on record (OpenAlex / Crossref)"
    return "—", ""
