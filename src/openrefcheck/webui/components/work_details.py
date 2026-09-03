"""What a matched work looks like on screen, wherever it is shown.

Two places show one: the References screen's fold-out, describing the work a reference
resolved to, and the manual review queue's candidate list, describing works it *might*
resolve to. They are the same object seen at two moments — before the identification and
after it — so they are rendered by the same code. A reviewer who learns to read one has
learned to read the other, and a fact that appears on one and not the other is a fact
someone will assume is absent rather than unrendered.

That mattered concretely: the candidate list showed a title, a source, a year and a
similarity score. Choosing between candidates is the identification the automated match
could not make, and it was being asked for on less evidence than the screen shows about a
match nobody has to decide. A *retracted* candidate was the sharp end — selectable, with
nothing to say so, and confirming it writes a retracted work into the reference list.
"""

from __future__ import annotations

# Topics and keywords are different vocabularies and are tinted apart, so a reader can see
# at a glance which list a term came from — OpenAlex's topics are curated subject areas,
# its keywords are finer and noisier.
TOPIC_TINT = "#eaeff2"
KEYWORD_TINT = "#f1eef3"


def cited_by_text(citations_crossref: int | None, citations_openalex: int | None) -> str:
    """Both sources' citation counts, attributed.

    They disagree substantially — measured, 8,121 (Crossref) against 10,653 (OpenAlex) for
    the same DOI — because each counts only the citing works it indexes. Showing one number
    would make the reader's answer depend on which source happened to win the match, with
    nothing on screen to say so.
    """
    reported = [
        f"{count:,} ({source})"
        for source, count in (
            ("Crossref", citations_crossref),
            ("OpenAlex", citations_openalex),
        )
        if count is not None
    ]
    return " / ".join(reported) if reported else "—"


def imprint_text(year: int | None, outlet: str) -> str:
    """Year and venue on one line — the two facts that separate a preprint, a chapter and
    an article that share a title."""
    return " · ".join(str(part) for part in (year, outlet) if part)


def retraction_url(retraction_doi: str) -> str | None:
    return f"https://doi.org/{retraction_doi}" if retraction_doi else None
