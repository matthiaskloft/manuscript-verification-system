"""Pure aggregation helpers shared by the Summary screen's live charts and the
HTML report's embedded chart images, so the two never drift apart."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from refcheck.extraction.citation_matching import CitationMatch
from refcheck.extraction.document_artifact import DocumentArtifact
from refcheck.gui import citation_display
from refcheck.gui.models import ReferenceResult

CURRENT_YEAR = 2026
AGE_BINS = [(0, 2, "0–2"), (3, 5, "3–5"), (6, 10, "6–10"), (11, 15, "11–15"), (16, 25, "16–25"), (26, 999, "25+")]
# How many topic bars the panel draws. OpenAlex gives up to three topics per work, so a
# thirty-entry bibliography can name sixty distinct ones; past about eight the panel stops
# showing breadth and starts showing a list.
MAX_TOPIC_BARS = 8

# How often the cited works are themselves cited, in bands. Roughly order-of-magnitude,
# because citation counts are heavily skewed — a reference list will hold a dozen works
# under 50 citations and one over 10,000, and equal-width bins would put everything in the
# first bar. The bands are what a reader can actually act on ("three of these are barely
# cited at all", "two are landmarks"), which a per-reference bar chart never said.
# The outlet chart's default floor, shared by the Summary screen's control and the
# report's chart so the two open on the same view. Strict, matching the "More than N"
# label: at 1 the chart shows outlets cited at least twice. A reference list is mostly
# outlets appearing exactly once, and a bar chart of fifty one-tall bars says nothing
# about where the manuscript's literature actually concentrates.
DEFAULT_OUTLET_THRESHOLD = 1

CITATION_BINS = [
    (0, 0, "0"),
    (1, 9, "1–9"),
    (10, 49, "10–49"),
    (50, 199, "50–199"),
    (200, 999, "200–999"),
    (1000, 10**12, "1000+"),
]


def age_bin_counts(results: list[ReferenceResult]) -> tuple[list[str], list[int]]:
    labels = [b[2] for b in AGE_BINS]
    counts = [sum(1 for r in results if r.year and lo <= CURRENT_YEAR - r.year <= hi) for lo, hi, _ in AGE_BINS]
    return labels, counts


def topic_breakdown(results: list[ReferenceResult]) -> tuple[list[str], list[int]]:
    """How many of the cited works fall under each subject area, largest last.

    Reads OpenAlex's `topics`, carried on every matched reference. It used to read a
    singular `ReferenceResult.topic` against a hard-coded list of five subject names, and
    nothing in the real pipeline ever set that field — so this panel showed its empty state
    on every check ever run.

    A work carries up to three topics and is counted under each, so the bars sum to more
    than the number of references. That is the honest shape for "breadth": a paper that
    sits across three areas belongs in all three, and normalising it away would understate
    exactly the interdisciplinary spread the panel is there to show.

    Deduped by DOI like `outlet_breakdown`, so a reference the list prints twice does not
    make its subject area look twice as central.
    """
    seen_dois: set[str] = set()
    counts: Counter[str] = Counter()
    for result in results:
        if not result.topics:
            continue
        doi = result.doi.casefold()
        if doi in seen_dois:
            continue
        seen_dois.add(doi)
        counts.update(result.topics)
    ordered = sorted(counts.items(), key=lambda kv: (kv[1], kv[0].casefold()))
    ordered = ordered[-MAX_TOPIC_BARS:]
    return [topic for topic, _ in ordered], [count for _, count in ordered]


def unique_citation_values(results: list[ReferenceResult]) -> list[int]:
    """One citation count per unique source (deduped by DOI so a duplicate status
    reference doesn't double-count the same underlying source), sorted descending."""
    seen: dict[str, int] = {}
    for r in results:
        # A reference whose lookup reported no count is left out rather than plotted as a
        # zero bar: the chart is about how much the cited literature is itself cited, and
        # an unknown drawn at zero is a claim the lookup never made.
        if r.status in ("verified", "dup") and r.doi and r.citations is not None:
            seen.setdefault(r.doi, r.citations)
    return sorted(seen.values(), reverse=True)


def citation_bin_counts(results: list[ReferenceResult]) -> tuple[list[str], list[int]]:
    """How many references fall in each citation band — the same shape as
    `age_bin_counts`, and read the same way: bands across, references up.

    Built on `unique_citation_values`, so a reference sharing a DOI with an earlier one is
    counted once and a reference whose lookup reported no count is left out rather than
    banked as a zero. "0" is a real band and means the lookup said zero.
    """
    labels = [label for _lo, _hi, label in CITATION_BINS]
    values = unique_citation_values(results)
    counts = [
        sum(1 for value in values if lo <= value <= hi) for lo, hi, _label in CITATION_BINS
    ]
    return labels, counts


def citation_rows(
    results: Sequence[ReferenceResult],
    matches: Sequence[CitationMatch],
    run_status: str,
    *,
    artifact: DocumentArtifact | None = None,
    include_passages: bool = False,
) -> list[dict]:
    """The in-text citation table for the report, one row per reference.

    Wording comes from `citation_display`, so the report says what the screen said. That
    is the same reason the chart helpers above are here: a report that disagrees with the
    application it came from is worse than one that omits the section.

    `include_passages` is this side's own opt-in and defaults off. The screen's gate was
    removed on request (2026-08-11) and this one deliberately was not: an export leaves the
    session, and reading a sentence in the app is not the same decision as writing it into
    a file. Without it the rows carry counts and flags and no manuscript text; the passages
    are read here, from the artifact, and only when the caller has been told to include
    them.
    """
    numbers = [r.n for r in results]
    records = citation_display.per_reference(numbers, matches, run_status)
    rows = []
    for result in results:
        record = records[result.n]
        passages: list[str] = []
        if include_passages and artifact is not None:
            passages = [
                artifact.paragraph_text(place.match.anchor)
                for place in citation_display.places_for(result.n, matches)
            ]
        rows.append(
            {
                "n": result.n,
                "raw": result.raw,
                "times_cited": record.times_cited,
                "uncited": record.uncited,
                "label": record.label,
                "passages": passages,
            }
        )
    return rows


def outlet_breakdown(
    results: list[ReferenceResult], min_unique_citations: int = DEFAULT_OUTLET_THRESHOLD
) -> tuple[list[str], list[int]]:
    """Count unique matched works by journal, publisher, or preprint server.

    `min_unique_citations` is a *strict* floor, matching the screen's "More than N"
    wording: the default of 1 shows outlets the manuscript draws on at least twice.
    """
    seen_dois: set[str] = set()
    counts: Counter[str] = Counter()
    for result in results:
        if result.status not in ("verified", "dup") or not result.outlet:
            continue
        doi = result.doi.casefold()
        if doi in seen_dois:
            continue
        seen_dois.add(doi)
        counts[result.outlet] += 1
    ordered = sorted(
        ((outlet, count) for outlet, count in counts.items() if count > min_unique_citations),
        key=lambda item: (item[1], item[0].casefold()),
    )
    return [label for label, _ in ordered], [count for _, count in ordered]
