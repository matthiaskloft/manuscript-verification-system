"""Shared data model for a single checked reference, used across GUI screens."""

from __future__ import annotations

from dataclasses import dataclass

STATUS_KEYS = ("verified", "review", "halluc", "dup", "unchecked")

STATUS_LABELS = {
    "verified": "Verified",
    "review": "Needs review",
    "halluc": "No match found",
    "dup": "Duplicate",
    "unchecked": "Not checked",
}

# Shorter form for the reference-table badge, where a long label like "No match
# found" would make row-to-row column widths inconsistent (each table row is
# an independently laid-out widget, so badge width directly shifts everything after
# it). The full label is still used as a tooltip and in the detail panel.
STATUS_LABELS_SHORT = {
    "verified": "Verified",
    "review": "Needs review",
    "halluc": "No match",
    "dup": "Duplicate",
    "unchecked": "Not checked",
}


@dataclass(frozen=True)
class Candidate:
    """A plausible alternative match offered in the manual-review queue."""

    title: str
    doi: str
    similarity: float
    year: int | None = None
    source: str = ""  # "OpenAlex" / "Crossref" — which lookup surfaced this candidate
    outlet: str = ""
    # The evidence a reviewer needs to choose between candidates, mirroring what the
    # reference card shows for the winner. See VerificationCandidate for why.
    citations_crossref: int | None = None
    citations_openalex: int | None = None
    retracted: bool | None = None
    retraction_doi: str = ""
    abstract: str = ""
    topics: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceResult:
    n: int
    raw: str
    title: str
    doi: str
    status: str  # one of STATUS_KEYS
    confidence: float
    year: int | None = None
    # How often the wider literature cites the matched work (OpenAlex `cited_by_count` /
    # Crossref `is-referenced-by-count`). None means no lookup reported one, which is a
    # different fact from a work nobody has cited yet — and the difference is the whole
    # value of the figure, since 0 is otherwise indistinguishable from "we never asked".
    citations: int | None = None
    # The same figure as each source reported it. They disagree substantially — measured,
    # 8,121 (Crossref) against 10,653 (OpenAlex) for one DOI — because each counts only the
    # citing works it indexes, so the card shows both rather than picking for the reader.
    citations_crossref: int | None = None
    citations_openalex: int | None = None
    # None means no lookup answered — never "clean". A reference whose verification failed
    # or never ran must not be able to look like one that came back clear, because the two
    # lead a reviewer to opposite actions and only one of them was earned.
    retracted: bool | None = None
    retraction_doi: str = ""  # the notice's own DOI, where the source named it
    # The matched work's abstract and subject areas (OpenAlex). Public metadata about a
    # published work, not manuscript text — no visibility gate applies to these.
    abstract: str = ""
    topics: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    source: str = ""  # "OpenAlex" / "Crossref" — empty if unchecked
    outlet: str = ""  # journal, publisher, or preprint server reported by the lookup
    queried: str = ""  # e.g. "14:09" — empty if unchecked
    candidates: tuple[Candidate, ...] = ()  # only meaningful for review/unchecked status
    dup_of: int | None = None  # ref number of the earlier entry this DOI duplicates — "dup" status only
    manual_note: str = ""  # e.g. "Recategorized from Duplicate at 14:32" — set on manual override
