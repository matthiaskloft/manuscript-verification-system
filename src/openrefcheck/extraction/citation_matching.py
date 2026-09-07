"""Resolve detected in-text citation markers to bibliography entries.

Phase 4 of docs/plans/plan-in-text-citation-parsing.md, and the point where the two
detection tiers converge. Tier 0 (`intext_signals`) knows where a marker sits on the
page and has to work out which reference it names; Tier 1 (`extraction.grobid`) is told
which reference and knows nothing about the page. This module takes either one and
produces the same record: a `CitationMatch` naming a `RawReferenceEntry.index` — which
is `ReferenceResult.n` — or explicitly naming none.

**Never a guess.** The plan's requirement, and the reason there are four statuses rather
than a match/no-match boolean. A marker that names a reference this document does not
carry is an authoring error worth reporting (`ORPHANED`); a marker whose text this
project cannot interpret at all is not evidence of anything (`UNRESOLVED`); a marker
that fits two entries equally well is a question for the reviewer, not a coin flip
(`AMBIGUOUS`). Only the first of those is a finding, and conflating it with the other
two is how a reviewer gets told about an error that isn't there.

**Locating and resolving are separate questions.** `anchor` is where the marker sits in
the manuscript and is `None` when that could not be established; `reference_n` is what it
cites. Tier 0 answers the first exactly (its offsets are already into the artifact's
`body_text`) and the second by inference; Tier 1 the other way round. A match can be
resolved but unlocated, and both halves are reported rather than one being allowed to
suppress the other.

Everything here works on `RawReferenceEntry`, not on `ReferenceResult`: matching needs
the entry's raw text, the numbers are the same on both types, and an extraction module
that imported the GUI's result class would be a layering inversion for no gain.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum

from openrefcheck.extraction.document_artifact import DocumentArtifact, SourceAnchor
from openrefcheck.extraction.engine_status import ENGINE_ANCHOR, ENGINE_GROBID
from openrefcheck.extraction.grobid import CitationContext
from openrefcheck.extraction.intext_signals import (
    DetectedCitation,
    MarkerFamily,
    detect_citations,
    expected_families,
    parse_marker,
)
from openrefcheck.extraction.reference_list_audit import NOT_AUDITED, ReferenceListAudit
from openrefcheck.extraction.signals import BARE_YEAR_RE, DATE_SLOT_RE, NO_DATE, NO_DATE_RE
from openrefcheck.extraction.style_profile import StyleProfile
from openrefcheck.extraction.tier0 import RawReferenceEntry

# How similar two surnames have to be before they are treated as the same name.
#
# Not inherited from parsing_match.TITLE_MATCH_THRESHOLD (0.85), which the plan was
# explicit about: that number is about whole title strings, and the same ratio means
# something quite different for a surname — "Wu"/"Xu" scores 0.5 where two 40-character
# titles differing by one word score 0.97.
#
# What the benchmark found (tests/test_citation_matching_recall.py) is that the corpus
# cannot choose the value *at all*: the same 121 citations resolve identically at every
# threshold from 0.0 to 1.0, and only an impossible one above 1.0 changes anything. The
# reason is that names are not what separates this corpus — the year is. Two of its
# references have identical surnames (Ricoeur 1969 and Ricoeur 1970) and two more are
# within 0.833 (Barth, Barthes), so the name-only collision ceiling here is 1.000, not
# some comfortable distance below the threshold. `_year_agreement` drops those pairings
# before the threshold is ever consulted, which is what makes it look inert.
#
# So this number rests on an argument, not on a measurement, and the argument is about
# what the corpus does not contain: no name that extraction damaged, and no pair that
# has to be told apart by name alone. **No test can move it**, which is why the pairs it
# is chosen from are written down here and asserted individually in
# tests/test_citation_matching.py — the suite is green at every value, so the pairs are
# the evidence and the corpus is not.
#
# Raised from 0.80 to 0.90 on 2026-08-13, decided against these measured scores:
#
#   Smith/Smyth      0.800    a typed error in the manuscript
#   Meyer/Meier      0.800    a typed error, or two different people
#   Barth/Barthes    0.833    two different authors, both in the Chicago fixture
#   Fischer/Fisher   0.923    the same name, one of them damaged
#   Mueller/Muller   0.923    the same name, the "ue" digraph lost or added
#   Shannon/Shanon   0.923    the same name, a letter dropped by extraction
#
# The gap between 0.833 and 0.923 is the whole argument: every pair below it is two
# different names, and every pair above it is one name twice. 0.80 sat under both groups
# and so could not tell them apart — it resolved "(Smyth, 2020)" against a bibliography
# carrying only Smith, and it left Barth and Barthes separable only by their years, which
# is a real collision in this project's own fixture rather than a hypothetical one.
#
# What the raise costs, stated rather than hidden: a name damaged by more than roughly one
# character now fails to match, and its reference reads as uncited while the citation reads
# as orphaned — two false findings from one mangled name, where 0.80 produced none. That is
# the deliberate trade, and it is the reverse of the one made at 0.80. It is taken because
# diacritics are already folded before comparison (Levinas/Lévinas scores 1.000, not 0.9),
# which removes the single most common form of extraction damage from the question
# entirely, and because the damage that remains tends to be a dropped letter — inside the
# 0.923 band — rather than the two-or-more-character difference that separates real names.
SURNAME_MATCH_THRESHOLD = 0.90

# What a *missing* year on either side costs. Not a veto: a bibliography whose date this
# project failed to read would otherwise take every marker for that reference with it,
# and an entry with no readable date is a parsing failure far more often than a marker
# citing a work with no date. A disagreement between two years both of which were read is
# a different matter and is handled by _year_agreement returning None, which drops the
# pairing outright.
#
# Deliberately large enough that an exact surname match survives it (0.9 * 1.0 clears
# SURNAME_MATCH_THRESHOLD) and small enough that an approximate one does not: with no
# date to corroborate it, a name that is merely similar is not enough on its own.
#
# Those two properties are the band [0.90, 0.975), and both edges are now asserted in
# tests/test_citation_matching.py. The floor is SURNAME_MATCH_THRESHOLD / 1.0 — an exact
# match scores 1.0 and still has to clear the threshold afterwards. The ceiling is
# SURNAME_MATCH_THRESHOLD / 0.923, where 0.923 is the best-scoring damaged-name pair the
# threshold was chosen to accept *when a year corroborates it*: Fisher against a dateless
# "Fischer" resolves at 0.99 and must not, because there the name is the only evidence
# there is.
#
# Worth knowing that 0.9 sits on the floor exactly, because it explains why this constant
# looked covered and was not. Every downward move breaks the exact-match property at once
# and fails several tests loudly; the whole upper half of the range was silent until the
# ceiling was pinned, which is the asymmetry a "the suite is green" argument cannot see.
_MISSING_YEAR_PENALTY = 0.9

# What a numbered marker resolved against a list numbered only by position is worth (see
# _resolve_numbered). Nothing gates on it — no numbered path compares a confidence to a
# threshold — so its whole job is to rank honestly: deliberately below
# SURNAME_MATCH_THRESHOLD, so that a match resting on "the list is assumed complete" never
# sorts above one that a surname and a year actually corroborated.
_POSITIONAL_NUMBER_CONFIDENCE = 0.5

# How far into an entry to look for its author list and date. Past this we are into the
# title, where a year is as likely to belong to the work being described ("The 1918
# pandemic...") as to the entry itself.
_ENTRY_HEAD = 200

# The longest a surname runs, particles included ("van der Veen"). A chunk of the author
# region with more words than this is title or publisher text that the split could not
# separate, not a name — see _strip_initials.
_MAX_NAME_WORDS = 3

# Surname particles, in the same list intext_signals uses for the marker side. A style
# may print "de Beauvoir" in the bibliography and "Beauvoir (2011)" in text (Chicago
# does), so both forms of every name are compared and the better score wins.
_PARTICLES = frozenset(
    "van von de del della den der des di dos du da la le ten ter zu zur".split()
)

# A numbered bibliography's own printed marker, at the head of an entry.
_MARKER_PREFIX_RE = re.compile(r"^\s*(?:\[\d{1,3}\]|\d{1,3}[.)])\s*")
_PRINTED_NUMBER_RE = re.compile(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})[.)])(?=\s|$)")

# The rule a style prints instead of repeating an author across consecutive entries.
# Chicago writes "———."; PDF extraction routinely delivers some of that, or only the
# period. Deliberately not "any non-letter": see _starts_with_a_rule.
_REPEATED_AUTHOR_RULE_RE = re.compile(r"^[—–\-_.]+(?:\s|$)")

# How far into an entry a bare year can sit and still be its publication date rather than
# a number in its title. Chicago puts it right after the author ("Kuhn, Thomas S. 1962."),
# which is inside this window even for a long author list; a numbered style puts it past
# the title, which is not.
_CERTAIN_DATE_WINDOW = 80

# A numeric range around a year-shaped number, looked at from either side.
_RANGE_AFTER_RE = re.compile(r"\s*[-–—]\s*\d")
_RANGE_BEFORE_RE = re.compile(r"\d\s*[-–—]\s*\Z")

# What separates two authors in a bibliography entry. The sentence-ending period is in
# here because a numbered style has no date to cut the author region at, so the region
# runs into the title and the period is the only boundary left ("Doll R, Hill AB.
# Smoking and carcinoma..."). It costs nothing on the styles that do have a date: an
# initial's period is followed by the next initial or the next name either way.
_AUTHOR_SPLIT_RE = re.compile(r"[,;]|\.\s|\band\b|\bund\b|&")

# What separates two names in a marker's author run, as `intext_signals` reports it —
# it hands over the run as written ("van der Veen and Smith", "Müller u. a."), which is
# the one string both tiers can produce, so splitting it is this module's job.
_NAME_SPLIT_RE = re.compile(r"\s*(?:,\s*(?:and|und|&)?|\s(?:and|und|&)\s)\s*", re.IGNORECASE)
_ETAL_RE = re.compile(r"\b(?:et\s+al\.?|u\.\s?a\.|et\s+alii)\.?\s*$", re.IGNORECASE)

# "No date", asked of the two sides in the two forms they write it. A bibliography puts
# it in the slot the year goes in, parentheses and all, which is the only way to tell an
# undated entry from a work whose title or publisher says "in press" or "no date" — the
# words are ordinary enough to appear in both. A marker writes them bare, inside the
# citation's own parentheses, which is the form `intext_signals` hands over.
_ENTRY_NO_DATE_RE = NO_DATE_RE
_MARKER_NO_DATE_RE = re.compile(NO_DATE, re.IGNORECASE)
_YEAR_SUFFIXED_RE = re.compile(BARE_YEAR_RE.pattern + r"[a-z]?")
_NON_NAME_RE = re.compile(r"[^a-z ]+")

# The canonical form every no-date spelling collapses to, so "n.d." in a marker and
# "in press" in the entry it cites are not compared as two different years.
_NO_DATE_KEY = "n.d."


class MatchStatus(Enum):
    """What resolving one marker against this document's bibliography established."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    ORPHANED = "orphaned"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class CitationMatch:
    """One reference named by one in-text marker, resolved against the bibliography.

    One record per reference, never per marker: a grouped citation is several of these,
    which is what keeps "cited N times" and the unused/orphaned flags correct without
    anything downstream having to reach inside a group. Tier 0's members share a span
    because the detector reports the whole marker; Tier 1's have their own, because
    GROBID emits one element per reference and each one's position is known more
    precisely than the group's.

    `reference_n` is `RawReferenceEntry.index`, i.e. `ReferenceResult.n`, and is None for
    every status but RESOLVED. `candidates` carries the entries an AMBIGUOUS marker could
    equally be — a reviewer resolving it by hand needs the shortlist, and an entry on it
    is not an unused reference.

    `anchor` is where the marker is in the manuscript, or None if that is not known;
    see the module docstring on why an unlocated match is still a match. No passage text
    is carried: raw context is looked up from the artifact when — and only when — a
    reviewer has asked to see it (the plan's context-visibility decision), and a copy
    living here would put one in every structure a match is stored in.
    """

    marker_text: str
    tier: str
    status: MatchStatus
    reference_n: int | None = None
    confidence: float = 0.0
    candidates: tuple[int, ...] = ()
    anchor: SourceAnchor | None = None
    family: MarkerFamily | None = None
    narrative: bool = False


def match_citations(
    artifact: DocumentArtifact,
    references: Sequence[RawReferenceEntry],
    *,
    grobid_citations: Sequence[CitationContext] = (),
    profile: StyleProfile | None = None,
    audit: ReferenceListAudit = NOT_AUDITED,
) -> tuple[CitationMatch, ...]:
    """Every in-text citation in `artifact`, resolved against `references`.

    Tier 0 always runs. Tier 1 answers for the markers GROBID linked, and Tier 0 answers
    for the rest — the two are separated by *where each marker sits*, not by a decision
    about which tier owns the document.

    That replaces a switch on `len(grobid_citations) >= 1`, which was the wrong shape for
    the argument behind it. Not mixing the tiers is right, and the reason is real: run both
    over the whole body and every marker they agree on is counted twice. But one linked
    context is not evidence that GROBID found them all, and treating it that way meant a
    manuscript where GROBID linked one marker of fifty had forty-nine markers looked for by
    nobody — reported as forty-nine references cited by nothing, which is a finding about
    the manuscript drawn from a gap in this project's own reading. There is no count at
    which that becomes safe, which is why no threshold replaced it.

    Overlap is what tells the tiers apart, and it is available because Tier 1 already has
    to locate its markers in the artifact (`_locate_marker`, Phase 4) to report where they
    are. A Tier 0 detection overlapping a located Tier 1 anchor is the same marker read
    twice and is dropped; one in unclaimed territory is a marker Tier 1 never offered an
    answer for. Measured against a live GROBID over the five synthetic manuscripts, all 121
    contexts located and all 121 anchors landed on a span Tier 0 had independently called a
    marker — so on a document GROBID reads perfectly this adds nothing at all, which is the
    behaviour to want from it.

    `profile` is the bibliography's own style evidence, which narrows Tier 0's marker
    families (see `expected_families`); omitting it searches for all of them. It now
    narrows the supplementary pass on the Tier 1 path too, where it was previously unused.

    `audit` is how `references` compared to the list the document printed, and it is what
    a numbered marker is resolved through when it has one (see `_reference_index`).
    Defaulting to "not checked" means a caller that has no audit gets exactly the previous
    behaviour — resolution through position, hedged as such — rather than a claim resting
    on a comparison nobody made.
    """
    families = expected_families(profile) if profile is not None else None
    detected = detect_citations(artifact.body_text, families=families)
    known = _reference_index(references, audit)

    if grobid_citations:
        return _match_grobid(artifact, references, grobid_citations, known, detected)
    return _match_detected(artifact, known, detected)


def unused_reference_numbers(
    reference_numbers: Iterable[int], matches: Sequence[CitationMatch]
) -> tuple[int, ...]:
    """The entries no marker was found to cite — the plan's unused-reference flag.

    An AMBIGUOUS marker's candidates count as citing every entry on their shortlist. The
    flag is a claim that a reviewer should look at a reference nothing points to, and an
    entry that a marker might be citing is not that. Erring the other way would report an
    unused reference on the strength of the one status that exists to say "don't know".

    This says nothing about whether citation detection worked. A document whose markers
    were never detected has every reference unused by this measure, which is why the
    caller carries a run status alongside (see the plan's Success Criteria: "no citations
    found" and "the search did not run" are different states) and must not render this
    list without it.

    Takes reference *numbers* rather than entries so that both sides of the pipeline can
    ask: extraction holds `RawReferenceEntry.index` and the UI holds `ReferenceResult.n`,
    which are the same number on two types that have no reason to know about each other.
    """
    cited = {match.reference_n for match in matches if match.reference_n is not None}
    cited.update(number for match in matches for number in match.candidates)
    return tuple(number for number in reference_numbers if number not in cited)


def citation_counts(matches: Sequence[CitationMatch]) -> dict[int, int]:
    """How many times each reference is cited — the "cited N times" figure, per `n`.

    Resolved matches only. An ambiguous marker is counted for no one: adding it to every
    candidate would inflate several counts for one citation, and picking one of them is
    the guess this module does not make.
    """
    counts: dict[int, int] = {}
    for match in matches:
        if match.status is MatchStatus.RESOLVED and match.reference_n is not None:
            counts[match.reference_n] = counts.get(match.reference_n, 0) + 1
    return counts


# --------------------------------------------------------------------------------------
# Tier 1: GROBID already resolved the target
# --------------------------------------------------------------------------------------


def _match_grobid(
    artifact: DocumentArtifact,
    references: Sequence[RawReferenceEntry],
    contexts: Sequence[CitationContext],
    known: _ReferenceIndex,
    detected: Sequence[DetectedCitation],
) -> tuple[CitationMatch, ...]:
    """Tier 1 matches: GROBID's own marker→entry link, a Tier 0 reading where it has none,
    and a Tier 0 pass over the manuscript GROBID said nothing about at all.

    A context whose `reference_index` is set is resolved and done — GROBID linked the
    marker to a `<biblStruct>` and `extraction.grobid` mapped that TEI id to a position,
    explicitly rather than by assuming ids and positions coincide.

    A context with no link is *not* an orphan on that evidence. GROBID resolves a marker
    against the bibliography it extracted itself, so a marker it could not link is far
    more often one it failed to link than one this manuscript has no entry for — and
    reporting the difference as an authoring error is precisely the false accusation this
    feature must not make. The marker's own text is read with the Tier 0 parser instead,
    which is the same evidence the regex tier would have had, and only when *that* names a
    reference the bibliography lacks is the marker called orphaned. Text the parser cannot
    interpret at all stays UNRESOLVED.

    A link naming an entry this reference list does not contain is treated as no link at
    all. `extraction.grobid` builds both halves from one response, so the two cannot
    disagree in the pipeline — but this function takes them as separate arguments, and
    `reference_index` is the one number here that would otherwise be believed without
    evidence, in a module whose whole argument is that nothing is.

    **A marker GROBID never mentioned is read by Tier 0**, provided every context could be
    located. The proviso is the whole safety argument: an unlocated context has claimed no
    span, so nothing can tell whether a Tier 0 detection is that same marker read a second
    time, and counting one citation twice is a wrong number rather than a missing one. When
    that happens the supplement is skipped altogether and this returns exactly what it
    returned before — GROBID's reading alone. Deliberately not a per-context exclusion by
    marker text: the contexts that fail to locate are the ones GROBID handed over truncated
    ("[15, p. 87"), whose text is precisely what does not match what Tier 0 read.

    **What a claimed span excludes is a reference, not a region** — see `_already_answered`.
    A grouped marker's Tier 0 members all carry the *group's* span ("[1, 2]" is two
    detections over the same six characters), so a rule that dropped every detection
    overlapping a claim let one linked member suppress the rest of its own group. That is
    the same defect this function exists to fix, one marker further in.

    The supplement carries `ENGINE_ANCHOR` as its tier, because that is which tier found
    it, and the two are not equally strong: Tier 1's link is GROBID's own resolution
    against the bibliography, while a Tier 0 supplement is an inference from the marker's
    text. Labelling them alike would hide that from anything downstream that sorts or
    displays by tier.
    """
    numbers = {entry.index for entry in references}
    matches: list[tuple[int, CitationMatch]] = []  # (document position, match)
    claimed: list[tuple[int, int, int | None]] = []  # (start, end, reference answered)
    unreadable: list[int] = []  # indices into `matches` of contexts Tier 1 handed over broken
    unlocated = False
    cursor = 0

    def add(position: int, match: CitationMatch, anchor: SourceAnchor | None) -> None:
        matches.append((position, match))
        if anchor is not None:
            claimed.append((anchor.start, anchor.end, match.reference_n))

    for context in contexts:
        anchor, cursor = _locate_marker(artifact, context.marker_text, cursor)
        if anchor is None:
            unlocated = True
        # An unlocated context sorts with the last one that placed, so it stays where
        # GROBID put it rather than being swept to the front of the document.
        position = anchor.start if anchor is not None else cursor

        if context.reference_index in numbers:
            add(
                position,
                CitationMatch(
                    marker_text=context.marker_text,
                    tier=ENGINE_GROBID,
                    status=MatchStatus.RESOLVED,
                    reference_n=context.reference_index,
                    confidence=1.0,
                    anchor=anchor,
                ),
                anchor,
            )
            continue

        parsed = parse_marker(context.marker_text)
        if not parsed:
            unreadable.append(len(matches))
            add(
                position,
                CitationMatch(
                    marker_text=context.marker_text,
                    tier=ENGINE_GROBID,
                    status=MatchStatus.UNRESOLVED,
                    anchor=anchor,
                ),
                anchor,
            )
            continue
        for citation in parsed:
            add(position, _resolve(citation, known, tier=ENGINE_GROBID, anchor=anchor), anchor)

    if not unlocated:
        read_by_tier0: list[tuple[int, int]] = []
        for citation in detected:
            supplement = _resolve(
                citation,
                known,
                tier=ENGINE_ANCHOR,
                anchor=artifact.anchor_for(citation.start, citation.end),
            )
            if not _already_answered(citation, supplement, claimed):
                matches.append((citation.start, supplement))
                read_by_tier0.append((citation.start, citation.end))

        # A context Tier 1 handed over unreadable is dropped where Tier 0 read the same
        # characters. GROBID truncates a grouped marker — "[8, 9]" arrives as a linked
        # "[8," plus an unlinked "9]" — and the second is a marker this project *can* read;
        # `parse_marker` only failed on GROBID's fragment of it. Keeping the record put two
        # entries on one citation, so two markers reported as three read, and the surplus
        # landed in the unresolved count, where it read as the tool declining on something
        # it had in fact answered one line above.
        #
        # Only where Tier 0 actually covered it. An unreadable context nothing else reached
        # keeps its record: there the decline is true, and it is the only trace that GROBID
        # saw a marker at all. Note this whole branch is skipped when any context failed to
        # locate, so a document in that state keeps every record either way.
        if read_by_tier0:
            matches = [
                pair
                for index, pair in enumerate(matches)
                if index not in unreadable or not _covers(pair[1].anchor, read_by_tier0)
            ]

    # Stable, so a group of matches sharing one position keeps the order it was built in.
    matches.sort(key=lambda pair: pair[0])
    return tuple(match for _, match in matches)


def _covers(anchor: SourceAnchor | None, spans: Sequence[tuple[int, int]]) -> bool:
    """Whether a kept Tier 0 detection sits on the same characters as this anchor.

    An unlocated anchor is covered by nothing — there is no span to compare, and a record
    with no position is the one least able to spare its own evidence.
    """
    if anchor is None:
        return False
    return any(anchor.start < end and start < anchor.end for start, end in spans)


def _already_answered(
    citation: DetectedCitation,
    supplement: CitationMatch,
    claimed: Sequence[tuple[int, int, int | None]],
) -> bool:
    """Whether Tier 1 has already spoken for what this Tier 0 detection says.

    Overlap alone is not the question, because a grouped marker's members share one span:
    `detect_citations` reports "[1, 2]" as two detections over the same six characters, so
    excluding by region would let GROBID's link for "[1" bury the manuscript's citation of
    reference 2 — reported as a reference cited by nothing, which is the exact false finding
    the supplement exists to prevent.

    So a detection survives only when it names a reference no Tier 1 match named in the span
    it overlaps. Everything else is dropped, and the asymmetry is deliberate: a detection
    Tier 0 could not resolve, or resolved to a reference Tier 1 already reported there, has
    nothing to add to a marker that has been answered — while keeping it would put a second
    record on one citation, and a duplicate is a wrong number where a drop is a silent one.

    A Tier 0 reading that *disagrees* with Tier 1 about the same span is likewise dropped
    rather than reported alongside it. Tier 1's answer is GROBID's own resolution against
    the bibliography and this module does not have the evidence to overturn it; surfacing
    both would make a reviewer arbitrate a conflict neither number is labelled for.
    """
    overlapping = [
        answered
        for start, end, answered in claimed
        if citation.start < end and start < citation.end
    ]
    if not overlapping:
        return False
    return supplement.status is not MatchStatus.RESOLVED or supplement.reference_n in overlapping


def _locate_marker(
    artifact: DocumentArtifact, marker_text: str, cursor: int
) -> tuple[SourceAnchor | None, int]:
    """Find a Tier 1 marker's text in the artifact, at or after `cursor`.

    TEI offsets are into GROBID's own rendering of the document and share no coordinates
    with a `DocumentArtifact` built from pymupdf4llm's, so the only thing the two have in
    common is the marker's characters. Searching forward from the last marker found is
    what keeps a repeated marker ("[3]" cited eight times) landing on eight different
    positions instead of eight copies of the first; both sequences are in document order,
    so the cursor is a real constraint rather than a tie-break.

    Best-effort by construction, and separate from resolving on purpose. A marker that
    cannot be found — because extraction rendered it differently, or because GROBID read a
    ligature the PDF text layer does not have — is reported unlocated, with its reference
    still resolved. Falling back to a search from the start of the document was considered
    and rejected: it would answer with an earlier occurrence that has already been claimed
    by another marker, which is a wrong position rather than a missing one.

    The separators a grouped citation leaves on its second element (", [3]") are stripped
    before searching, since the manuscript does not print them as part of the marker.

    An occurrence only counts when it is not glued to a word or a number. A superscript
    numbering style gives GROBID a marker whose whole text is "1", and "1" occurs inside
    "2019" — which anchored a citation to the middle of a year four words away from the
    marker it claimed to be. A wrong position is worse than none, because it is the one
    thing a reviewer cannot check without re-reading the page themselves.
    """
    needle = marker_text.strip().strip(",;&").strip()
    if not needle:
        return None, cursor
    position = artifact.body_text.find(needle, cursor)
    while position != -1 and not _is_free_standing(artifact.body_text, position, len(needle)):
        position = artifact.body_text.find(needle, position + 1)
    if position == -1:
        return None, cursor
    return artifact.anchor_for(position, position + len(needle)), position + len(needle)


def _is_free_standing(text: str, start: int, length: int) -> bool:
    """Whether `text[start:start + length]` is bounded rather than part of a longer run.

    Alphanumeric on either side means the "marker" is a fragment of a word or a number.
    Punctuation is fine on both sides — a marker is routinely followed by a comma or a
    full stop and preceded by a bracket.
    """
    before = text[start - 1] if start else ""
    after = text[start + length : start + length + 1]
    return not (before.isalnum() or after.isalnum())


# --------------------------------------------------------------------------------------
# Tier 0: resolve a marker by what it says
# --------------------------------------------------------------------------------------


def _match_detected(
    artifact: DocumentArtifact,
    known: _ReferenceIndex,
    detected: Sequence[DetectedCitation],
) -> tuple[CitationMatch, ...]:
    return tuple(
        _resolve(citation, known, tier=ENGINE_ANCHOR, anchor=artifact.anchor_for(citation.start, citation.end))
        for citation in detected
    )


def _resolve(
    citation: DetectedCitation, known: _ReferenceIndex, *, tier: str, anchor: SourceAnchor | None
) -> CitationMatch:
    """Which reference a marker names, or explicitly none.

    A list with no entries in it answers nothing, and that has to be said here rather than
    left to fall out of the scoring. `_resolve_author_date` reaches ORPHANED by scoring
    every entry and finding none good enough, which over an empty list is vacuously true —
    so a manuscript whose bibliography extraction came back with nothing had every
    author-date marker reported as citing a reference the document does not carry, a page
    of findings generated entirely by this project's own miss. It is the same rule
    `exhaustive` states on the numbered side: a list can only be said to lack an entry if
    it was read.
    """
    if not known.entries:
        return CitationMatch(
            marker_text=citation.marker_text,
            tier=tier,
            status=MatchStatus.UNRESOLVED,
            anchor=anchor,
            family=citation.family,
            narrative=citation.narrative,
        )
    if citation.family is MarkerFamily.NUMBERED:
        return _resolve_numbered(citation, known, tier=tier, anchor=anchor)
    return _resolve_author_date(citation, known, tier=tier, anchor=anchor)


def _resolve_numbered(
    citation: DetectedCitation, known: _ReferenceIndex, *, tier: str, anchor: SourceAnchor | None
) -> CitationMatch:
    """A numbered marker names its reference outright — the question is only whether the
    document carries an entry by that number.

    Which is not the same as the entry's position in the extracted list. A numbered
    bibliography prints its own numbers, and when they can be read they are what the marker
    means; falling back to position assumes extraction dropped nothing, which is exactly
    what a document with a hard-to-parse reference list violates. `_ReferenceIndex` prefers
    the printed numbers — from the reference-list audit, or from the entries' own markers —
    and falls back to position, so a dropped entry shifts nothing when they are there.

    When they are not, every answer here is conditional on an extraction that lost nothing,
    and both of this function's answers have to be weakened to say so. Against a list
    numbered only by position:

    - a hit is still returned, because position is exact whenever the list is whole and
      refusing to answer would abandon numbered citations on a path that was, before the
      audit, every numbered PDF GROBID handled. It carries
      `_POSITIONAL_NUMBER_CONFIDENCE` rather than certainty.
    - a miss becomes UNRESOLVED rather than ORPHANED. A number past the end of the list is
      equally consistent with a citation to nothing and with a list that came up short
      because an entry was dropped, and only one of those is the manuscript's fault. The
      plan's rule that a finding needs evidence applies here: this is not evidence.

    A miss is also UNRESOLVED where the numbers *were* read but the audit reports that
    number missing — `known.exhaustive`. That is the same rule with better evidence behind
    it: the page prints an entry under that number and extraction did not produce one, so
    the marker cites a reference the document does list. Calling it orphaned would accuse
    the manuscript of this project's own miss, which is the reverse of what the status is
    for.
    """
    reference_n = known.by_number.get(citation.number) if citation.number is not None else None
    if reference_n is None:
        return CitationMatch(
            marker_text=citation.marker_text,
            tier=tier,
            status=MatchStatus.ORPHANED if known.numbered and known.exhaustive else MatchStatus.UNRESOLVED,
            anchor=anchor,
            family=citation.family,
            narrative=citation.narrative,
        )
    return CitationMatch(
        marker_text=citation.marker_text,
        tier=tier,
        status=MatchStatus.RESOLVED,
        reference_n=reference_n,
        confidence=1.0 if known.numbered else _POSITIONAL_NUMBER_CONFIDENCE,
        anchor=anchor,
        family=citation.family,
        narrative=citation.narrative,
    )


def _resolve_author_date(
    citation: DetectedCitation, known: _ReferenceIndex, *, tier: str, anchor: SourceAnchor | None
) -> CitationMatch:
    """Score every entry against the marker's first surname and year, and take a winner
    only if there is one.

    First surname against first surname, because that is the one an author-date marker
    always prints and the one its bibliography is alphabetised by — "Doe et al." names
    Doe. The rest of the marker's names are a tie-break rather than part of the score:
    "(Doe & Roe, 2020)" and "(Doe, 2020)" score identically on the head alone, and the
    second name is what separates them when a document carries both.
    """
    surnames = _marker_surnames(citation.authors)
    if not surnames:
        return CitationMatch(
            marker_text=citation.marker_text,
            tier=tier,
            status=MatchStatus.UNRESOLVED,
            anchor=anchor,
            family=citation.family,
            narrative=citation.narrative,
        )

    year = _year_key(citation.year)
    scored: list[tuple[float, int, int]] = []  # (score, corroborating names, index)
    for entry in known.entries:
        agreement = _year_agreement(year, entry.years, entry.dated)
        if agreement is None:
            continue
        score = _name_similarity(surnames[0], entry.first_surname) * agreement
        if score < SURNAME_MATCH_THRESHOLD:
            continue
        scored.append((score, _corroborating(surnames[1:], entry), entry.index))

    if not scored:
        return CitationMatch(
            marker_text=citation.marker_text,
            tier=tier,
            status=MatchStatus.ORPHANED,
            anchor=anchor,
            family=citation.family,
            narrative=citation.narrative,
        )

    best = max(scored, key=lambda candidate: (round(candidate[0], 6), candidate[1]))
    tied = [
        candidate
        for candidate in scored
        if (round(candidate[0], 6), candidate[1]) == (round(best[0], 6), best[1])
    ]
    if len(tied) > 1:
        return CitationMatch(
            marker_text=citation.marker_text,
            tier=tier,
            status=MatchStatus.AMBIGUOUS,
            confidence=best[0],
            candidates=tuple(sorted(candidate[2] for candidate in tied)),
            anchor=anchor,
            family=citation.family,
            narrative=citation.narrative,
        )
    return CitationMatch(
        marker_text=citation.marker_text,
        tier=tier,
        status=MatchStatus.RESOLVED,
        reference_n=best[2],
        confidence=best[0],
        anchor=anchor,
        family=citation.family,
        narrative=citation.narrative,
    )


def _corroborating(surnames: Sequence[str], entry: _ReferenceKey) -> int:
    """How many of a marker's remaining names the entry also carries."""
    return sum(
        1
        for surname in surnames
        if any(_name_similarity(surname, other) >= SURNAME_MATCH_THRESHOLD for other in entry.surnames)
    )


# --------------------------------------------------------------------------------------
# The bibliography side
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _ReferenceKey:
    """What one bibliography entry offers a marker to be matched against.

    `dated` is whether the year was read from somewhere that is a date, rather than from
    a number that merely looks like one. Only a certain date may contradict a marker; see
    `_year_agreement`.
    """

    index: int
    first_surname: str
    surnames: tuple[str, ...]
    years: frozenset[str]
    dated: bool = False


@dataclass(frozen=True)
class _ReferenceIndex:
    entries: tuple[_ReferenceKey, ...]
    by_number: dict[int, int]
    numbered: bool = False
    """True when `by_number` was read from printed numbers, wherever they were read from.

    False means it is the positional fallback, which is a different claim entirely: not
    "the list says this is number 3" but "this is the third entry we managed to extract".
    """

    exhaustive: bool = True
    """Whether a number absent from `by_number` proves the bibliography has no such entry.

    Separate from `numbered` because the two were one flag and should not have been. A hit
    and a miss ask different questions of the same map — "is this the right entry" and "is
    there no such entry" — and the reference-list audit is the first source able to answer
    yes to the first and no to the second: it reads the printed numbers off the page *and*
    reports which of them extraction failed to produce an entry for. A marker citing one of
    those names a reference the document really does list, so calling it ORPHANED accuses
    the manuscript of this project's own miss.

    The entry-marker reading answers it too, less completely, from the shape of the
    numbers it read: see `_reference_index`.
    """


def _reference_index(
    references: Sequence[RawReferenceEntry], audit: ReferenceListAudit = NOT_AUDITED
) -> _ReferenceIndex:
    """Parse the bibliography once into the two shapes matching needs.

    `by_number` maps a printed reference number to an entry's `index`, from whichever of
    two readings has one. The audit's is preferred and is why a GROBID-extracted list is no
    longer stuck with position: GROBID strips the printed marker from both of its strings,
    so before the audit existed every numbered Tier-1 bibliography fell through to position
    and one dropped entry shifted every marker after it onto the wrong reference. Failing
    that, an entry's own leading marker is read — which works for a bibliography whose
    entries kept theirs, and is the path a caller with no audit takes.

    **The audit's map is used whole; the entry-marker reading is all-or-nothing.** They
    look like the same map and are built under opposite rules, which is worth being
    explicit about, because treating the audit's like the other one is a defect this had
    and PR #58's review caught. The entry-marker reading has to abandon the map on the
    first unreadable entry: a hole in it is a number this project failed to read, so an
    entry whose "[3]" did not survive extraction would leave "[3]" absent from the map and
    its marker an orphaned citation — a manuscript accused of citing a reference sitting
    in its own list. The audit's map has no such holes to leave. It is built by walking
    the *printed* list, so every printed number is either mapped or reported in
    `missing`, and an extracted entry that appears under no number is not a gap but a
    finding: a fragment matching nothing the page printed. Dropping the map because such a
    row exists is what reintroduced the positional shift — for printed `[1] A`, `[2] B`,
    `[3] C` extracted as `A`, `B-first-half`, `B-fragment`, `C`, the whole map was
    discarded and `[3]` resolved to the fragment in position 3 instead of to `C`.

    Whenever nothing was lost is an assumption, not a fact, so the fallback is flagged
    rather than silently substituted: `numbered` tells `_resolve_numbered` which reading it
    got. `exhaustive` tells it what a *miss* against that reading is worth.

    **A dropped entry and an unreadable one are not the same failure**, which is what the
    all-or-nothing rule above misses on its own. The loop below can only fail on an entry
    it was handed; an entry extraction never produced is not there to fail on. Printed
    "[1]" "[2]" "[3]" "[4]" arriving as three entries reading "[1]" "[2]" "[4]" is a map
    every one of whose entries was read perfectly, and "[3]" is orphaned against it — the
    same false finding by the other route. The numbers themselves carry the evidence: a
    complete reading of a numbered list is `1..n`, so a gap, or a run that does not start
    at 1, is proof an entry was lost and `exhaustive` is False. What that costs is a list
    genuinely numbered from somewhere other than 1 — a per-chapter bibliography — whose
    misses become UNRESOLVED rather than ORPHANED. That is the direction to err in: a
    finding withheld, not a finding invented.

    It stays a partial answer, and the part it cannot reach is the tail. A list of ten
    extracted as `1..9` is a whole run by this test, so a marker citing "[10]" is still
    called orphaned. Nothing on this path distinguishes that from a list that really has
    nine entries; the audit, which reads the printed list rather than the extracted one,
    is what closes it.
    """
    entries = _inherit_repeated_authors(references)

    if audit.numbered and audit.by_printed_number:
        return _ReferenceIndex(
            entries=entries,
            by_number=dict(audit.by_printed_number),
            numbered=True,
            # An entry the audit could not place on the page leaves a number in `missing`,
            # and a marker citing that number is this project's miss rather than the
            # manuscript's error.
            exhaustive=not audit.missing,
        )

    printed: dict[int, int] = {}
    for entry in references:
        number = _printed_number(_entry_text(entry))
        if number is None or number in printed:
            printed = {}
            break
        printed[number] = entry.index

    if not printed:
        return _ReferenceIndex(
            entries=entries,
            by_number={entry.index: entry.index for entry in references},
            numbered=False,
        )
    return _ReferenceIndex(
        entries=entries,
        by_number=printed,
        numbered=True,
        exhaustive=sorted(printed) == list(range(1, len(printed) + 1)),
    )


def _inherit_repeated_authors(references: Sequence[RawReferenceEntry]) -> tuple[_ReferenceKey, ...]:
    """Parse each entry, giving a repeated-author entry the names of the one above it.

    Several styles print a rule instead of repeating an author across consecutive entries
    — Chicago's "———. 1970. Freud and Philosophy..." is the case this was found on, in the
    project's own Chicago fixture, where the rule survives PDF extraction as a bare ". "
    and the entry has no author in it at all. Read in isolation that entry matches
    nothing, so "(Ricoeur 1970)" was reported as an orphaned citation: a manuscript
    accused of citing a work it lists, because the list said "same as above".

    Inheritance is gated on the entry opening with the rule itself — a run of dashes,
    underscores or periods — and nothing else. "Starts with a non-letter" was the first
    version of that gate and it was wrong in the direction that matters: a title-first
    entry opens with a quotation mark, so an anonymous work or an editorial listed under
    an author-first entry inherited that author's surname, and "(Kuhn 1970)" resolved to
    the editorial at full confidence. A missed match is a cost; a confident wrong one is a
    false report about the manuscript.
    """
    keys: list[_ReferenceKey] = []
    for entry in references:
        key = _reference_key(entry)
        if not key.surnames and keys and _starts_with_a_rule(_entry_text(entry)):
            previous = keys[-1]
            key = _ReferenceKey(
                index=key.index,
                first_surname=previous.first_surname,
                surnames=previous.surnames,
                years=key.years,
                dated=key.dated,
            )
        keys.append(key)
    return tuple(keys)


def _starts_with_a_rule(raw_text: str) -> bool:
    """Whether an entry opens with the rule a style prints for a repeated author.

    Written as a run of rule characters rather than as "not a letter" so that a
    title-first entry — which opens with a quotation mark, a bracket or a digit — is not
    read as one. The single "." is not a typo: it is what the Chicago fixture's "———."
    actually survives PDF extraction as.
    """
    text = _MARKER_PREFIX_RE.sub("", raw_text).strip()
    return _REPEATED_AUTHOR_RULE_RE.match(text) is not None


def _printed_number(raw_text: str) -> int | None:
    """The reference number an entry prints for itself, if it prints one.

    Capped at three digits, matching `_MARKER_PREFIX_RE`: `DOT_NUMBER_RE`'s unbounded
    `\\d+` reads the year opening a Chicago entry whose author was replaced by a rule
    ("1974. The Conflict of Interpretations...") as reference number 1974, and two of
    those are enough to replace the positional map for a whole document.
    """
    match = _PRINTED_NUMBER_RE.match(raw_text)
    return int(match.group(1) or match.group(2)) if match else None


def _entry_text(entry: RawReferenceEntry) -> str:
    """The text to weigh evidence about an entry from: what the document printed, when
    the extractor kept it, and otherwise whatever we have.

    The two differ only on the GROBID path, where `raw_text` is reassembled from the
    structured parse and therefore inherits every field that parse got wrong. The live
    Tier-1 measurement (2026-08-11) found that costing five citations: a reconstruction
    carries exactly one year, and for a reprint it is the original work's rather than the
    entry's own date, so "Weber, M. (1930). ... [Original work published 1905]" came back
    as 1905 alone and a manuscript citing (Weber, 1930) was reported as citing nothing.
    The printed string holds both years, and `_entry_years` takes them all.

    It is not a strictly better string for every purpose — it is unnormalised, it can
    carry a trailing fragment of the next entry, and it is missing where GROBID never
    supplied one — which is why the reconstruction stays as `raw_text` for display and
    verification rather than being replaced.
    """
    return entry.source_text or entry.raw_text


def _reference_key(entry: RawReferenceEntry) -> _ReferenceKey:
    text = _entry_text(entry)
    head, authors = _entry_regions(text)
    surnames = _entry_surnames(authors)
    years, dated = _entry_years(text, head)
    return _ReferenceKey(
        index=entry.index,
        first_surname=surnames[0] if surnames else "",
        surnames=surnames,
        years=years,
        dated=dated,
    )


def _entry_regions(raw_text: str) -> tuple[str, str]:
    """An entry's date region and its author region: up to the date, and up to before it.

    Both are cut at the date because the title is where a year stops meaning "when this
    was published" and a capitalised word stops meaning "a name" — "Doe, J. (2020).
    Rereading Milgram in the 1960s." carries two more year-shaped numbers and a surname
    that is not an author of it. A bare year counts as the date as well as a parenthesised
    one, since two of the four styles this project targets print it that way ("Kuhn,
    Thomas S. 1962."). An entry with no readable date is cut at a fixed length instead,
    which is coarser and is why a date is looked for first.

    The two differ by the date itself, which the year read needs and the author read must
    not see: an unterminated "(2020" left on the end of the author region parses as one
    more name, and being first in the list it would be the entry's *first* surname.
    """
    text = raw_text[:_ENTRY_HEAD]
    date = DATE_SLOT_RE.search(text) or _YEAR_SUFFIXED_RE.search(text)
    if date is None:
        return text, text
    return text[: date.end()], text[: date.start()]


def _entry_surnames(authors: str) -> tuple[str, ...]:
    """The surnames an entry's author list opens with, in order.

    Every style this project targets prints the first author surname-first in the
    bibliography, whatever it does in text, because that is what the list is ordered by.
    What differs is where the initials go — "Doe, J.", "Doll R", "C. E. Shannon" — so
    they are stripped from either end of each name rather than assumed to sit on one.

    The first comma is a separator in "Doe, J., & Roe, A." and part of nothing in "Doll R,
    Hill AB", which is why the split is on commas *and* the initials strip runs afterwards:
    both readings produce the same surnames once the initials are gone.

    A numbered list's own printed marker ("[1] C. E. Shannon") needs no special handling:
    it carries no letters, and `_strip_initials` keeps only words that do.
    """
    names: list[str] = []
    for chunk in _AUTHOR_SPLIT_RE.split(authors):
        name = _strip_initials(chunk)
        if name:
            names.append(name)
    return tuple(names)


def _strip_initials(chunk: str) -> str:
    """A name chunk reduced to its surname, or "" if there is no name in it.

    Initials go from either end (styles disagree about which end they belong on), and so
    do the run-together capitals a numbered style prints instead ("Doll R", "Hill AB").
    A chunk left with more words than a name has is discarded rather than kept: past the
    author list an entry is prose, and the whole point of a surname set is that a word in
    it stands for a person.

    The capitals rule cannot tell a two-letter initial run from a two-letter surname, and
    "WU, Q." or "NG, K." is an ordinary house style, not a corner case — so it may not be
    the rule that empties a chunk. When dropping the capitals would leave nothing, they
    are the name: "Doll R" still gives "Doll", and "WU" gives "Wu" rather than an entry
    with no author at all, which was reported as an orphaned citation and an uncited
    reference at once.
    """
    chunk = _ETAL_RE.sub("", chunk.strip()).strip(" .")
    kept = [word for word in chunk.split() if re.search(r"[A-Za-zÀ-ÿ]", word)]
    words = [
        word
        for word in kept
        if not re.fullmatch(r"[A-Za-zÀ-ÿ]\.?", word) and not re.fullmatch(r"[A-ZÀ-Ý]{1,4}", word)
    ]
    if not words:
        words = [word for word in kept if re.fullmatch(r"[A-ZÀ-Ý]{2,4}", word)]
    if not words or len(words) > _MAX_NAME_WORDS:
        return ""
    return " ".join(words)


def _inside_a_range(text: str, match: re.Match[str]) -> bool:
    """Whether a year-shaped number is one end of a numeric range ("1990-1995")."""
    return bool(
        _RANGE_AFTER_RE.match(text, match.end()) or _RANGE_BEFORE_RE.search(text[: match.start()])
    )


def _entry_years(raw_text: str, head: str) -> tuple[frozenset[str], bool]:
    """The years an entry could be cited by, and whether any of them is certainly a date.

    Certain means the year was read from somewhere a date goes: a parenthesised slot or
    "n.d." (APA), or a bare year close enough to the front to still be in the author-date
    region (Chicago's "Kuhn, Thomas S. 1962."). Only a certain date is allowed to
    contradict a marker — see `_year_agreement`.

    The distinction is not bookkeeping. A numbered style prints its year at the very end,
    past the title and the journal, so anything read from an entry's tail competes with
    volume numbers and page ranges: "Journal of Tests, 12(3), 1990-1995." yields 1990, and
    treating that as the publication date reported "(Doe, 2020)" as an orphaned citation
    *and* the entry as never cited — two false findings from one page range. Continuous
    pagination puts four-digit page numbers in the 1500-2099 band routinely, so this is a
    common shape rather than a contrived one.

    A year inside a numeric range is never the date, wherever it sits: "1990-1995" is a
    page span in a journal with continuous pagination, and both of its endpoints are
    year-shaped. That one shape is worth naming separately from the window, because a
    reference list full of them would otherwise put a wrong date on every entry it has.

    Uncertain years are still returned, because agreeing with one is real evidence. They
    just cannot be used to reject.

    What this still gets wrong: a lone four-digit page number in the same band, with no
    range around it and close enough to the front ("...Journal of Tests, 12(3), 1990."),
    reads as a date. Rarer than a range and it fails the same way — one entry, one missed
    match — rather than in a new one.
    """
    if _ENTRY_NO_DATE_RE.search(head):
        return frozenset({_NO_DATE_KEY}), True

    certain = frozenset(
        match.group(0).lower()
        for match in _YEAR_SUFFIXED_RE.finditer(head)
        # Looked up in the whole entry, not in `head`: the head is cut at the first
        # year-shaped number, so the "-1995" that proves "1990" is a page range sits just
        # past its end.
        if match.start() < _CERTAIN_DATE_WINDOW and not _inside_a_range(raw_text, match)
    )
    if certain:
        return certain, True
    return frozenset(match.group(0).lower() for match in _YEAR_SUFFIXED_RE.finditer(raw_text)), False


# --------------------------------------------------------------------------------------
# Comparing names and years
# --------------------------------------------------------------------------------------


def _marker_surnames(authors: str | None) -> tuple[str, ...]:
    """The names in a marker's author run, which `intext_signals` reports as written.

    "et al." and its German form need no handling here: whichever chunk they land in,
    `_strip_initials` removes them.
    """
    if not authors:
        return ()
    names = [_strip_initials(part) for part in _NAME_SPLIT_RE.split(authors.strip())]
    return tuple(name for name in names if name)


def _year_key(year: str | None) -> str | None:
    """A marker's date as it will be compared: a lowercase year, "n.d.", or None."""
    if not year:
        return None
    if _MARKER_NO_DATE_RE.fullmatch(year.strip()):
        return _NO_DATE_KEY
    return year.strip().lower()


def _year_agreement(year: str | None, entry_years: frozenset[str], dated: bool = True) -> float | None:
    """How much a marker's year and an entry's agree: 1.0, a penalty, or None for no.

    None means the pairing is dropped outright, and it is returned for exactly one case:
    both sides carry a date, the entry's is certainly a date rather than a number that
    looks like one, and they are different years. That is the strongest signal in
    author-date matching — it is what tells two works by the same author apart, and what
    the styles' own "2020a"/"2020b" disambiguation is *for* — so a surname agreeing across
    it is not evidence of a match.

    `dated` is what keeps that veto from firing on a guess. A year scraped from an entry's
    tail can be a page range (see `_entry_years`), and a wrong veto is expensive in both
    directions at once: the citation is reported orphaned and the reference is reported
    uncited. An uncertain year that happens to agree still scores full marks; it just
    cannot reject.

    A letter suffix present on one side and absent on the other is not a disagreement: a
    marker prints "2020a" whenever the document cites two works from that year, and
    whether this project read the suffix off the bibliography entry depends on where the
    style puts it. Two *different* suffixes are a disagreement, since that is the
    distinction they exist to make.

    A missing date on either side is scored down rather than dropped, because the common
    reason for one is that extraction did not find it, and dropping every pairing on that
    basis would report the reference as uncited.
    """
    if year is None or not entry_years:
        return _MISSING_YEAR_PENALTY
    if year in entry_years:
        return 1.0
    base = year.rstrip("abcdefghijklmnopqrstuvwxyz")
    for other in entry_years:
        other_base = other.rstrip("abcdefghijklmnopqrstuvwxyz")
        if base != other_base:
            continue
        if base == year or other_base == other:
            return 1.0
    return None if dated else _MISSING_YEAR_PENALTY


def _fold_name(name: str) -> str:
    """Casefolded, unaccented, letters and spaces only.

    Diacritics go because PDF extraction loses and displaces them ("Müller" arrives as
    "Muller" often enough that a matcher requiring the mark would drop real citations),
    and the same fold is applied to both sides so neither is privileged.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_NAME_RE.sub(" ", stripped.casefold()).strip()


def _name_variants(name: str) -> tuple[str, ...]:
    """A folded name, with and without its particles.

    Both are compared because a style may drop the particle in text while keeping it in
    the bibliography — Chicago renders "de Beauvoir" as "Beauvoir (2011)" — and the German
    corpus pins the opposite case, a narrative marker keeping its "von". Neither side can
    be normalised to one form without deciding which style wrote it.
    """
    folded = _fold_name(name)
    if not folded:
        return ()
    words = folded.split()
    bare = [word for word in words if word not in _PARTICLES]
    variants = ["".join(words)]
    if bare and bare != words:
        variants.append("".join(bare))
    return tuple(variants)


def _name_similarity(a: str, b: str) -> float:
    """Similarity between two surnames, in [0, 1].

    `SequenceMatcher` over the folded, de-spaced name, taking the best score across the
    particle variants of both sides. Modeled on `parsing_match.title_similarity` but
    deliberately without its token-containment branch: that exists because Crossref
    sometimes returns a whole citation string where a title was asked for, and applied to
    names it would score "Doe" against "Doe, Roe & Fry" as a perfect match — the exact
    over-eagerness a two-word surname needs protection from.
    """
    left, right = _name_variants(a), _name_variants(b)
    if not left or not right:
        return 0.0
    return max(SequenceMatcher(None, x, y).ratio() for x in left for y in right)
