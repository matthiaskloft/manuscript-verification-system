"""What the screens and the report are allowed to say about in-text citations.

Phase 5 of docs/plans/plan-in-text-citation-parsing.md. `citation_matching` answers what
each marker cites; this module answers what a reviewer may be *told* about it, which is a
narrower question and the one the plan keeps putting guards around.

Pure, and deliberately separate from `webui/pages/`. Two callers need the same answers —
the References screen and the exported report — and a wording that drifts between them is
a wording the reader cannot trust. It is also the only way this layer gets tested: the
NiceGUI pages have no test harness in this project, so anything with a judgement in it
belongs here rather than inside a `render()`.

**The run status decides whether a per-reference claim exists at all.** This is the whole
reason the module is not three lines of dict comprehension. "No marker cites reference 7"
is a finding about the manuscript; "we detected no markers anywhere" is a fact about the
tool, and the second one makes every reference look like the first. `unused_reference_
numbers` says as much in its own docstring and cannot enforce it, because it is handed
numbers and matches with no status among them. Here the status comes first and the
per-reference verdict is withheld unless it can mean something.

No passage text passes through this module. The context viewer reads those straight from
the artifact, behind its own opt-in.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from openrefcheck.extraction.citation_matching import (
    CitationMatch,
    MatchStatus,
    citation_counts,
    unused_reference_numbers,
)
from openrefcheck.gui.real_pipeline import (
    CITATIONS_FAILED,
    CITATIONS_NONE_DETECTED,
    CITATIONS_NONE_MATCHED,
    CITATIONS_NOT_RUN,
    CITATIONS_OK,
)

# What the reference detail panel labels the figure. It sits directly under "Cited by",
# which is OpenAlex's count of the wider literature citing this work — the opposite
# direction and off by orders of magnitude — so the two labels have to be readable as a
# pair: "Cited by" is the world citing this work, "Cited in text" is this manuscript
# citing it. The plan called the collision out before either was rendered.
CITED_FIELD = "Cited in text"

# Why a reference carries no citation figure, when the reason is about the run rather than
# about the reference. Phrased as facts about the search, because that is what they are.
_RUN_NOTE = {
    CITATIONS_NONE_DETECTED: "no in-text citations were detected in this manuscript",
    # Not "none were found to cite it", which is the finding this state exists to withhold.
    # The markers were read; what failed is matching them to this list, and saying so is
    # what tells a reviewer to suspect the extracted bibliography rather than the writing.
    CITATIONS_NONE_MATCHED: (
        "in-text citations were detected, but none could be matched to this reference list"
    ),
    CITATIONS_NOT_RUN: "the in-text citation search did not run",
    CITATIONS_FAILED: "the in-text citation search failed",
}


@dataclass(frozen=True)
class ReferenceCitations:
    """What may be shown next to one reference.

    `uncited` is the plan's unused-reference flag and is False whenever the run could not
    support the claim — see the module docstring. `label` always says something: a reader
    who sees a blank cannot tell "nothing cites this" from "we did not look", which is the
    distinction the whole state machine exists to preserve.

    `possible` counts the markers that list this reference among their candidates without
    resolving to it. They are why `uncited` can be False while `times_cited` is 0: an
    entry a marker might be citing is not an entry nothing cites, and reporting it as
    unused would rest a finding on the one status that exists to say "don't know".
    """

    n: int
    times_cited: int = 0
    possible: int = 0
    uncited: bool = False
    label: str = ""
    # Whether the run could support a claim about this reference at all. Explicit rather
    # than inferred from the other fields: every one of them reads as a legitimate zero
    # when nothing was searched, which is the confusion this whole module exists to stop.
    searched: bool = False

    @property
    def figure(self) -> str:
        """The compact form, for a grid cell sitting under a row of other numbers.

        A count, because that is what the cell above it holds, and a sentence in a numeric
        column reads as a different kind of fact than it is. The prose stays in `label`,
        where the answer has room — the review queue and the report both have it, and a
        grid cell does not.

        "—" when nothing was searched, matching how the same panel writes an unknown
        "Cited by". A 0 there would be a finding, and this is not one.
        """
        if not self.searched:
            return "—"
        if self.possible and not self.times_cited:
            return f"0 (+{self.possible} ambiguous)"
        return str(self.times_cited)


@dataclass(frozen=True)
class DocumentCitations:
    """What may be shown about the manuscript as a whole.

    `orphaned` markers name no reference in this list, so they belong here rather than in
    any row: an orphan's whole content is that there is no row for it. `unresolved` and
    `ambiguous` are counted but are not findings — they are the tool declining to guess,
    and a screen that presents them as problems with the manuscript misreports both.
    """

    run_status: str = CITATIONS_NOT_RUN
    resolved: int = 0
    ambiguous: int = 0
    orphaned: int = 0
    unresolved: int = 0
    uncited_references: tuple[int, ...] = ()
    headline: str = ""

    @property
    def searched(self) -> bool:
        """Whether this run can support any per-reference claim at all."""
        return self.run_status == CITATIONS_OK


def per_reference(
    reference_numbers: Iterable[int],
    matches: Sequence[CitationMatch],
    run_status: str,
) -> dict[int, ReferenceCitations]:
    """One display record per reference number, keyed by `ReferenceResult.n`.

    Every number gets an entry, including the ones nothing has to say about, so a caller
    can render a row without checking whether the dict has the key — a screen that renders
    one reference differently because it happens to be missing from a mapping is a bug
    that only shows on real documents.
    """
    numbers = list(reference_numbers)
    if run_status != CITATIONS_OK:
        note = _RUN_NOTE.get(run_status, _RUN_NOTE[CITATIONS_NOT_RUN])
        return {n: ReferenceCitations(n=n, label=note.capitalize()) for n in numbers}

    counts = citation_counts(matches)
    # The unused flag comes from citation_matching rather than from `possible` below, even
    # though the two agree today. That rule — an ambiguous marker's whole shortlist counts
    # as cited — is a decision about what may be claimed, and it belongs in one place; a
    # second copy here would be a copy free to drift while still looking right.
    unused = set(unused_reference_numbers(numbers, matches))
    possible: dict[int, int] = {}
    for match in matches:
        for candidate in match.candidates:
            possible[candidate] = possible.get(candidate, 0) + 1

    records = {}
    for n in numbers:
        times = counts.get(n, 0)
        maybe = possible.get(n, 0)
        records[n] = ReferenceCitations(
            n=n,
            times_cited=times,
            possible=maybe,
            uncited=n in unused,
            label=_reference_label(times, maybe),
            searched=True,
        )
    return records


def _reference_label(times_cited: int, possible: int) -> str:
    if times_cited == 1:
        return "Cited once in this manuscript"
    if times_cited > 1:
        return f"Cited {times_cited} times in this manuscript"
    if possible == 1:
        return "One citation may name this reference, but is ambiguous"
    if possible > 1:
        return f"{possible} citations may name this reference, but are ambiguous"
    return "No in-text citation found for this reference"


@dataclass(frozen=True)
class CitationPlace:
    """One place in the manuscript a reference is cited from — an anchor, never a passage.

    `certain` is False for a marker that lists this reference among its candidates without
    resolving to it. Those are shown, because the reviewer deciding an ambiguous marker is
    exactly who needs to read the sentence around it, but they are labelled: a passage
    presented as "this is where you are cited" when the tool does not know that is the
    same false confidence the four statuses exist to avoid.
    """

    match: CitationMatch
    certain: bool

    @property
    def note(self) -> str:
        return "cites this reference" if self.certain else "may name this reference"


def places_for(reference_n: int, matches: Sequence[CitationMatch]) -> tuple[CitationPlace, ...]:
    """Where in the manuscript this reference is cited from, resolved first.

    Only matches whose position is known: locating and resolving are separate questions
    (see `citation_matching`'s module docstring), and a match that resolved without an
    anchor has no passage to show. It is still counted in the figure above, which is why
    "cited 3 times" and three passages are not the same claim and can legitimately differ.
    """
    certain = [
        CitationPlace(match=m, certain=True)
        for m in matches
        if m.status is MatchStatus.RESOLVED and m.reference_n == reference_n and m.anchor
    ]
    possible = [
        CitationPlace(match=m, certain=False)
        for m in matches
        if m.status is MatchStatus.AMBIGUOUS and reference_n in m.candidates and m.anchor
    ]
    return tuple(certain + possible)


def document_summary(
    reference_numbers: Iterable[int],
    matches: Sequence[CitationMatch],
    run_status: str,
) -> DocumentCitations:
    """The manuscript-level view: the counts, the unused list, and one line of prose."""
    numbers = list(reference_numbers)
    by_status = {status: 0 for status in MatchStatus}
    for match in matches:
        by_status[match.status] += 1

    if run_status != CITATIONS_OK:
        note = _RUN_NOTE.get(run_status, _RUN_NOTE[CITATIONS_NOT_RUN])
        return DocumentCitations(run_status=run_status, headline=note.capitalize())

    records = per_reference(numbers, matches, run_status)
    uncited = tuple(n for n in numbers if records[n].uncited)
    return DocumentCitations(
        run_status=run_status,
        resolved=by_status[MatchStatus.RESOLVED],
        ambiguous=by_status[MatchStatus.AMBIGUOUS],
        orphaned=by_status[MatchStatus.ORPHANED],
        unresolved=by_status[MatchStatus.UNRESOLVED],
        uncited_references=uncited,
        headline=_document_headline(
            len(matches), by_status[MatchStatus.ORPHANED], len(uncited)
        ),
    )


def _document_headline(total: int, orphaned: int, uncited: int) -> str:
    """One line, and the findings go first.

    A count of citations read is context; a citation naming a reference that is not in the
    list, and a reference nothing cites, are the two things a reviewer is here for.
    """
    read = f"{total} in-text citation{'' if total == 1 else 's'} read"
    findings = []
    if orphaned:
        findings.append(
            f"{orphaned} naming a reference this list does not carry"
            if orphaned > 1
            else "1 naming a reference this list does not carry"
        )
    if uncited:
        findings.append(
            f"{uncited} references with no citation found"
            if uncited > 1
            else "1 reference with no citation found"
        )
    if not findings:
        return read
    return read + " — " + ", ".join(findings)
