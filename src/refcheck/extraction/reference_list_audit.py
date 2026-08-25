"""Whether the extracted reference list is the list the document actually printed.

Every count this project shows a reviewer — "30 references", "2 uncited", "cited 3
times" — is a claim about the manuscript that is only true if extraction returned one
entry per printed entry. Tier 1 does not guarantee that. The live measurement
(tests/test_tier1_grobid_live.py, 2026-08-11) found GROBID folding a Chicago
bibliography's repeated-author entry into its predecessor and splitting an APA entry in
two, so the same five-document corpus came back 29, 30, 30, 30 and 31 entries against a
manifest that says 30, 30, 30, 30 and 1. Nothing downstream could tell.

The document itself is the evidence. `document.py` already isolates the bibliography
text for the Tier 0 path, so on any check that reads the body the printed list is in
hand alongside the extracted one, and the two can be compared. This module does that
comparison and answers two questions:

*What number does each entry print for itself?* A numbered bibliography states outright
which entry each "[12]" means. GROBID strips that marker — from its reconstruction and
from the printed string it returns alongside it, measured 0 of 30 IEEE entries keeping
one — so a numbered marker had no choice but to resolve through the entry's *position*
in the extracted list, which is the right answer only while nothing has been dropped.
`by_printed_number` removes that condition: an entry dropped before this point shifts
nothing after it, because every surviving entry is still found under the number the page
gave it.

The map is built by walking the *printed* list rather than the extracted one, and that is
what makes it safe to use whole. Every printed number is either mapped or reported in
`missing`, so it has no holes; an extracted entry appearing under no number is not a gap
in it but a finding in `unmatched`. `citation_matching._reference_index` says why the
distinction matters — the map it builds from an entry's own leading marker *can* have
holes, and has to be abandoned on the first one.

*Does the extracted list have the shape of the printed one?* Anything left over after
the alignment is a discrepancy worth telling the reviewer about: an entry covering two
printed entries has absorbed one (its citation counts are two references' worth), an
entry covering none is a fragment, and a printed entry nothing covers is missing from
every figure on screen.

What it deliberately does not do is decide which extractor is right. The printed reading
is Tier 0's splitter over the same text, and Tier 0 is fallible in both directions — on
that same Chicago bibliography it returns 31 for 30. So the *numbers* it produces are
only reported where the list numbers itself and they can be read rather than counted;
everywhere else the finding is structural ("this entry covers more than one printed
entry"), which is what the alignment actually shows.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from refcheck.extraction.tier0 import RawReferenceEntry, split_bibliography_block

# A printed entry's own number, at the head of a line: "[12] ", "12. ", "12) ". The same
# three shapes citation_matching._PRINTED_NUMBER_RE reads off an entry, asked of the
# bibliography text instead, and capped at three digits for the same reason: an unbounded
# run reads the year opening a Chicago entry ("1974. The Conflict of Interpretations")
# as a reference number.
_PRINTED_MARKER_RE = re.compile(r"(?m)^[ \t]*(?:\[(\d{1,3})\]|(\d{1,3})[.)])[ \t]+(?=\S)")

# How much of the shorter of the two readings has to turn up in the other before one is
# taken to cover the other. High, because the two are the *same* string on any entry
# extraction got right — this is not fuzzy record linkage across sources but a reading of
# one list against another reading of it, and the only differences are extraction
# artifacts. Measured against the five-document synthetic corpus with GROBID 0.8.1: every
# true pairing scores 0.94 or better, and the best wrong pairing scores 0.60.
_COVERAGE_THRESHOLD = 0.85

# Below this many tokens neither reading carries enough wording to be placed. On the
# printed side that is a heading fragment or a wrapped page range the splitter kept; on
# the extracted side it is a fragment of an entry rather than an entry. Either would be
# matched by coincidence rather than by content, and the extracted one has to fail to
# match so that the split which produced it is reported.
_MIN_TOKENS_TO_PLACE = 4

# Shortest printed token worth looking for inside the extracted entry's letters when the
# word itself is absent. The two readings disagree about characters no reference list
# should turn on: the corpus's "Röntgen" reaches GROBID intact and comes out of the PDF
# text layer as a bare diaeresis followed by the rest of the word, so the printed reading
# has "r" and "ontgen" where the extracted one has "rontgen". Four such tokens in one
# entry were enough for a word-set comparison alone to call a correctly extracted entry
# missing. Short tokens are excluded because a three-letter run occurs inside an unrelated
# entry constantly.
#
# Only this direction is rescued, and that is a real limit rather than an oversight: a
# word broken on the *extracted* side is not found by searching for the printed one. It is
# the PDF text layer that breaks words this way, which is the printed side, so the rescue
# is pointed where the damage was measured. A future extractor that damages the other side
# would need the mirrored lookup, not a lower threshold.
_MIN_TOKEN_TO_RESCUE = 4

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ReferenceListAudit:
    """How the extracted reference list compares to the one the document printed.

    `read` is False when the printed list could not be re-read at all — a document with
    no locatable bibliography section, or one whose section holds no entries the splitter
    recognises. Every other field is then empty, and the correct thing to say about the
    reference list is nothing: this module has no evidence, which is not the same as
    evidence that the list is whole. `complete` is False in that case too, so a caller
    that only asks "is it complete?" is never told yes on no evidence.

    `printed_count` is populated only for a list that numbers itself, where it is read
    off the page rather than counted. On an unnumbered list the count would be the Tier 0
    splitter's opinion, which is wrong by one on this project's own Chicago fixture, and
    a wrong total is worse than none — the discrepancies below stand on the alignment
    instead, which is the part the splitter's miscount does not change.

    `by_printed_number` maps a printed reference number to the `RawReferenceEntry.index`
    of the entry carrying it. An entry that absorbed its neighbour appears under both
    numbers, deliberately: it does contain the work each marker names, and answering
    "that one" is better than answering nothing while the merge itself is reported
    separately.

    `merged`, `unmatched` and `missing` are the three shapes a discrepancy takes, and
    each is a different sentence to a reviewer:
      - `merged` — entry indexes covering more than one printed entry. Their citation
        counts are several references' worth and the list is short by the difference.
      - `unmatched` — entry indexes covering no printed entry at all. Usually the second
        half of a printed entry that extraction split, i.e. a reference that is not one.
      - `missing` — printed entries no extracted entry covers, given as their printed
        numbers on a numbered list and as 1-based positions in the printed reading
        otherwise. These appear in no figure on screen.
    """

    read: bool = False
    numbered: bool = False
    printed_count: int | None = None
    by_printed_number: Mapping[int, int] = field(default_factory=dict)
    merged: tuple[int, ...] = ()
    unmatched: tuple[int, ...] = ()
    missing: tuple[int, ...] = ()

    @property
    def complete(self) -> bool:
        """Whether the extracted list was checked against the printed one and matched it.

        False on no evidence as well as on bad evidence. The two are told apart by
        `read`, and any caller phrasing this for a reviewer has to tell them apart —
        "this list is missing entries" and "this list could not be checked" are different
        statements and only one of them is about the manuscript.
        """
        return self.read and not (self.merged or self.unmatched or self.missing)


NOT_AUDITED = ReferenceListAudit()
"""The audit of a reference list nothing compared against anything.

Shared rather than reconstructed, which is safe because the type is frozen and nothing
writes to `by_printed_number`. It carries no count of the extracted entries on purpose:
this object says only that the comparison did not happen, and a caller wanting to know
how many references there are is holding them.
"""


def audit_reference_list(
    references: Sequence[RawReferenceEntry], bibliography_text: str | None
) -> ReferenceListAudit:
    """Compare an extracted reference list against the bibliography text it came from.

    `bibliography_text` is the section `document.find_bibliography_section` isolates —
    the printed list, before any splitting. None (or empty) is the no-evidence case:
    a DOCX whose heading was not found, a PDF whose body could not be read. It returns an
    unread audit rather than raising, because the reference list is the check's product
    and nothing here may endanger it.

    Passing the same text the extracted list was split from is the ordinary Tier 0 case
    and stays meaningful: the audit then compares the splitter's output against a second
    reading of the same text and agrees with itself, which is the correct answer — Tier 0
    entries are the printed entries, whatever their quality. The comparison earns its
    keep on the Tier 1 path, where the two readings are genuinely independent.
    """
    if not references or not bibliography_text or not bibliography_text.strip():
        return NOT_AUDITED

    printed = _printed_entries(bibliography_text)
    if not printed:
        return NOT_AUDITED

    owners = _owners(references, printed)

    covered_by: dict[int, list[int]] = {}
    missing: list[int] = []
    for position, (entry, owner) in enumerate(zip(printed, owners, strict=True), start=1):
        label = entry.number if entry.number is not None else position
        if owner is None:
            missing.append(label)
        else:
            covered_by.setdefault(owner, []).append(label)

    numbered = all(entry.number is not None for entry in printed)
    by_printed_number: dict[int, int] = {}
    if numbered:
        for owner, labels in covered_by.items():
            for label in labels:
                by_printed_number[label] = owner

    return ReferenceListAudit(
        read=True,
        numbered=numbered,
        printed_count=len(printed) if numbered else None,
        by_printed_number=by_printed_number,
        merged=tuple(sorted(owner for owner, labels in covered_by.items() if len(labels) > 1)),
        unmatched=tuple(entry.index for entry in references if entry.index not in covered_by),
        missing=tuple(missing),
    )


# --------------------------------------------------------------------------------------
# Reading the printed list
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _PrintedEntry:
    number: int | None
    tokens: frozenset[str] = field(repr=False)


def _printed_entries(bibliography_text: str) -> tuple[_PrintedEntry, ...]:
    """The bibliography as the page prints it: one element per entry, numbered if it says.

    Two readings, and the numbered one wins wherever it applies. A list that numbers
    itself has told us both how many entries it has and which is which, and neither
    answer depends on a splitting heuristic being right. Only when there is no such
    numbering does this fall back to the Tier 0 splitter, whose output is a reading of
    the same text rather than a statement by it — which is why an unnumbered audit
    reports no counts.
    """
    numbered = _numbered_entries(bibliography_text)
    if numbered:
        return numbered
    return tuple(
        _PrintedEntry(number=None, tokens=_tokens(entry.raw_text))
        for entry in split_bibliography_block(bibliography_text)
    )


def _numbered_entries(bibliography_text: str) -> tuple[_PrintedEntry, ...]:
    """Entries read off a self-numbering bibliography, or empty if it is not one.

    Only a strictly consecutive run from 1 counts, and a marker that does not continue
    the run is skipped rather than aborting it — the same rule, and for the same reason,
    as `tier0._entries_from_line_starts`: an author-date bibliography whose page range
    wraps onto its own line leaves a bare "246." that looks exactly like a marker, and
    one of those must not decide that the whole list is numbered, nor a real numbered
    list be abandoned because it contains one.

    A run of one is not a numbered list. A single "1." at the head of a section is as
    likely to be an enumerated note as a bibliography, and one entry cannot corroborate
    itself.
    """
    run: list[tuple[int, int, int]] = []
    expected = 1
    for match in _PRINTED_MARKER_RE.finditer(bibliography_text):
        number = int(match.group(1) or match.group(2))
        if number == expected:
            run.append((number, match.start(), match.end()))
            expected += 1
    if len(run) < 2:
        return ()

    entries: list[_PrintedEntry] = []
    for position, (number, _, text_start) in enumerate(run):
        text_end = run[position + 1][1] if position + 1 < len(run) else len(bibliography_text)
        entries.append(
            _PrintedEntry(number=number, tokens=_tokens(bibliography_text[text_start:text_end]))
        )
    return tuple(entries)


# --------------------------------------------------------------------------------------
# Aligning the two readings
# --------------------------------------------------------------------------------------


def _owners(
    references: Sequence[RawReferenceEntry], printed: Sequence[_PrintedEntry]
) -> list[int | None]:
    """For each printed entry, the index of the extracted entry covering it, or None.

    Ties go to the earlier entry, and that is the whole handling of a split: where
    extraction cut one printed entry in two, its first half and the printed entry it came
    from are the same string, so the half scores as well as the whole and both halves tie.
    Taking the earlier leaves the *later* half owning nothing, which is the fragment and
    the thing worth reporting; taking the later would report the complete half instead.
    """
    entries = [
        (entry.index, _tokens(text), _letters(text))
        for entry, text in ((entry, _extracted_text(entry)) for entry in references)
    ]

    owners: list[int | None] = []
    for candidate in printed:
        best_index, best_score = None, 0.0
        for index, tokens, letters in entries:
            score = _coverage(candidate.tokens, tokens, letters)
            if score > best_score:
                best_index, best_score = index, score
        owners.append(best_index if best_score >= _COVERAGE_THRESHOLD else None)
    return owners


def _coverage(printed: frozenset[str], extracted: frozenset[str], letters: str) -> float:
    """How much of the shorter reading of an entry is accounted for by the other, in [0, 1].

    Over the shorter side rather than over the printed one, because the two readings are
    damaged in opposite directions and a one-sided measure misses whichever damage it is
    not looking for. GROBID returns the printed string trimmed — the corpus's "Aquinas,
    Thomas. 1981. Summa Theologica." arrives without the publisher the page prints after
    it — so the printed entry is not contained in the extracted one; a merged entry is
    longer than either entry it absorbed, so the extracted entry is not contained in the
    printed one. Dividing by the shorter recognises both, and the merge is still reported,
    because it is found by *two* printed entries choosing the same owner rather than by
    either of them scoring badly.

    A printed word missing from the extracted word set is looked for once more inside that
    entry's letters, which is what makes a word the two readings broke differently (see
    `_MIN_TOKEN_TO_RESCUE`) count as present. It cannot manufacture a match: the letters
    searched are that same entry's own.
    """
    if len(printed) < _MIN_TOKENS_TO_PLACE or len(extracted) < _MIN_TOKENS_TO_PLACE:
        return 0.0
    shared = len(printed & extracted)
    shared += sum(
        1 for token in printed - extracted if len(token) >= _MIN_TOKEN_TO_RESCUE and token in letters
    )
    return min(1.0, shared / min(len(printed), len(extracted)))


def _extracted_text(entry: RawReferenceEntry) -> str:
    """The widest reading of an extracted entry, for coverage only.

    Both strings rather than `citation_matching._entry_text`'s choice of one: the printed
    string is what a printed entry should be found in, but GROBID does not always supply
    it, and the reconstruction carries fields (an expanded author list, a DOI) the printed
    string sometimes wraps out of reach. Taking the union costs nothing here — the measure
    is containment of the *printed* entry, so extra words on this side cannot manufacture
    coverage that is not there, only fail to miss it.
    """
    return f"{entry.source_text or ''} {entry.raw_text}"


def _tokens(text: str) -> frozenset[str]:
    """Case- and accent-folded word set.

    A set, not a sequence: word order carries no information here that coverage needs, and
    the printed and extracted readings of one entry routinely differ in order where GROBID
    rebuilds an author list.
    """
    return frozenset(_fold(text).split())


def _letters(text: str) -> str:
    """The same folding with the spaces taken out too — one run of letters and digits.

    What `_coverage` searches when a word is present in one reading and broken in the
    other. Keeping it as its own string rather than re-deriving it per lookup matters:
    a bibliography asks this question once per entry pair.
    """
    return _fold(text).replace(" ", "")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_ALNUM_RE.sub(" ", stripped.casefold()).strip()
