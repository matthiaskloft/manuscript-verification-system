"""Tier 0 reference extraction: regex/heuristic splitting of a bibliography block.

No external parser (GROBID/AnyStyle) — see docs/project-plan.md, "Technischer Stack (MVP)"
for why this is the baseline tier in the benchmark, not the final choice.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

# YEAR_PAREN_RE tells a genuine new-entry line apart from a wrapped continuation line
# that also happens to start with an author-start pattern (a co-author's name) — see
# _entries_from_year_gated_starts. It used to be defined here as r"\(\d{4}[a-z]?\b",
# under the same name as title.py's stricter version: that one matched any
# parenthesised four-digit run, so Vancouver's "1954;2(4682):1451" read as carrying a
# publication year. DATE_SLOT_RE is the same question asked of "(n.d.)" too.
from refcheck.extraction.signals import (
    APA_AUTHOR_START_RE,
    BARE_NUMBER_RE,
    BARE_YEAR_RE,
    BRACKET_NUMBER_RE,
    DATE_SLOT_RE,
    DOT_NUMBER_RE,
    JSS_AUTHOR_START_RE,
    LINK_END,
    YEAR_PAREN_RE,
)

# These five marker regexes are defined in signals.py (shared vocabulary); aliased
# here under their historical private names since every call site below still uses
# those names.
_BRACKET_NUMBER_RE = BRACKET_NUMBER_RE
_DOT_NUMBER_RE = DOT_NUMBER_RE
_BARE_NUMBER_RE = BARE_NUMBER_RE
_APA_AUTHOR_START_RE = APA_AUTHOR_START_RE
_JSS_AUTHOR_START_RE = JSS_AUTHOR_START_RE

_INLINE_DOT_NUMBER_RE = re.compile(r"(?<![\d/])(\d{1,3})[.)]\s+(?=[A-ZÀ-Ý])")

# The trailing "(?![A-ZÀ-Ý]\.\s*:)" rejects a publisher location ("Hillsdale, N.J.:",
# "Washington, D.C.:"), whose second initial runs into a colon — see
# _entries_from_inline_apa_starts. Real initials are followed by a space, a year, or
# the end of the author list, never by a colon.
_APA_AUTHOR_ANYWHERE_RE = re.compile(
    r"(?:^|(?<=\s))((?:[A-Za-zÀ-ÿ]+\s+){0,2}(?P<surname>[A-ZÀ-Ý][\w'-]*),\s*[A-ZÀ-Ý]\.(?![A-ZÀ-Ý]\.\s*:))",
    re.MULTILINE,
)

# Words that introduce a further name *inside* the current entry (an edited-book
# chapter's editors, a co-author after a line wrap) rather than a new entry. Anchored
# to the end of a short window ending at the surname. See _entries_from_inline_apa_starts.
_INLINE_CONNECTOR_BEFORE_RE = re.compile(r"(?:^|\s|\()(?:in|and|with|&|und|mit)[\s:]+$", re.IGNORECASE)
_CONNECTOR_LOOKBACK = 16

# The tail of a DOI or URL, which an APA entry ends on with no closing period. Defined
# in signals.py so this module, document.py's stop-heading check and its paragraph
# merge all agree on what a finished entry can look like.
_LINK_RE = re.compile(LINK_END)
# Enough room for the look-back window to see a whole DOI before a candidate start.
_BOUNDARY_LOOKBACK = 96

# A new entry can only begin where the previous one ended: at the very start of the
# text, on a fresh line, after sentence-terminal punctuation, or after a trailing
# DOI/URL — APA puts no period after those, so requiring punctuation alone would glue
# every DOI-final entry to the one after it, and modern reference lists are full of
# them. Every further name in an author or editor list is separated by a comma
# instead ("Smith, A. B., Jones, C. D., & Brown, E. F."), which is what keeps the
# middle of a three-editor list — where neither the connector nor the year gate
# applies — from reading as an entry start.
_ENTRY_BOUNDARY_BEFORE_RE = re.compile(r"(?:^|\n\s*|[.?!][\"'”)\]]*\s+|" + LINK_END + r"\s+)$")

# Leading "12. "/"12) " marker on an entry recovered by _entries_from_inline_number_starts.
_INLINE_MARKER_PREFIX_RE = re.compile(r"^\d{1,3}[.)]\s*")

# Longest a single wrapped entry is expected to run before its year shows up; past
# this, a matching author-start line is accepted even without a year seen yet (see
# _entries_from_year_gated_starts).
_MAX_ENTRY_LINES = 8

_ENTRY_WORDS_RE = re.compile(r"[A-Za-zÀ-ÿ]{3,}")

# How many ascending inline "N." markers a flattened numbered bibliography must show
# before it's preferred over leaving the text unsplit — see
# _entries_from_inline_number_starts.
_MIN_INLINE_NUMBER_RUN = 3

# How many unparenthesised years one "entry" has to carry before it's read as several
# references stuck together (see _flattening_evidence). Three rather than two, since a
# single entry legitimately shows a second year often enough — a reprint note, a
# "retrieved" date, a year inside a title.
_MIN_YEARS_PER_FLATTENED_ENTRY = 3

# Shortest year-less leading fragment still kept as an entry of its own — below this a
# fragment is a leftover heading, not a reference (see _entries_between).
_MIN_LEADING_FRAGMENT_CHARS = 40


@dataclass
class RawReferenceEntry:
    """One still-unstructured entry from the bibliography, before author/year/title/DOI parsing.

    title is None for the regex-only Tier 0 path (title.py's heuristic runs on
    raw_text later). A structured extractor such as GROBID (see
    refcheck.extraction.grobid) already knows the title and sets it here directly,
    letting callers skip the regex heuristic for entries that have one.

    source_id is the extractor's own identifier for this entry — GROBID's TEI
    `xml:id` ("b12") — and is None for Tier 0, which has none to give. index is this
    entry's 1-based position and is what the rest of the app keys on
    (`ReferenceResult.n`); the two do not coincide and must not be confused, which is
    the whole reason the id is carried rather than inferred. It is what lets an in-text
    `<ref target="#b12">` be resolved to a reference after the fact, by a caller that
    did not build the reference list itself.
    """

    index: int
    raw_text: str
    title: str | None = None
    source_id: str | None = None
    source_text: str | None = None
    """The entry as the document printed it, when the extractor kept it separately.

    None on the Tier 0 path, where `raw_text` already *is* that string. GROBID sets it,
    because there `raw_text` is a reconstruction assembled from the structured parse and
    the two can disagree: a reprint's date slot may be missing from the parse while the
    printed entry carries both years, and an entry whose authors GROBID failed to read
    reconstructs without a name at all. Anything weighing evidence about an entry should
    prefer this (see citation_matching._entry_text); anything displaying one entry to a
    reviewer may reasonably prefer the tidier reconstruction.
    """


def _has_entry_words(text: str) -> bool:
    """Whether what follows a marker reads as an entry rather than a stray number.

    A real numbered entry has words ("15. Wynder EL. Tobacco and health..."); the
    lines a *non*-numbered bibliography leaves looking numbered are wrapped page
    ranges and years ("246.", "2019.") or a bare download link ("10 https://...",
    where the URL's own letters would otherwise pass for words), so links are removed
    before looking.
    """
    return bool(_ENTRY_WORDS_RE.search(_LINK_RE.sub("", text)))


def _entries_from_line_starts(
    lines: list[str], marker_re: re.Pattern[str], require_sequential: bool = False
) -> list[str] | None:
    """Group lines into entries that each start with a line matching marker_re.

    Returns None if fewer than two markers are found (not enough signal to trust
    this heuristic over the others). The marker itself is always stripped: every
    caller passes a numbered pattern, whose "[1]"/"1." carries no content. (A
    strip_marker=False option existed for the author-start fallback, which has since
    moved to _entries_from_year_gated_starts and does its own slicing.)

    require_sequential=True additionally filters candidate markers down to a
    strictly consecutive run starting at 1 — used for the numbered-marker
    heuristics, where the marker regex's group(1) is the reference number. Without
    this, a justified APA/author-year bibliography whose page range happens to wrap
    onto its own line (e.g. "Psychological Bulletin, 107, 238–\n246.") produces a
    bare "246." that false-matches the "1." numbered-marker pattern. Two such
    false hits anywhere in the document are enough to make this heuristic look like
    a genuine numbered bibliography and hijack the split, since it runs before the
    APA/JSS fallbacks and only needs >=2 matches to win — corrupting the split
    silently rather than falling through to the heuristic that would've worked.

    The filter is greedy, not all-or-nothing: it walks the candidates in order and
    only keeps ones that continue the 1, 2, 3, ... run, skipping (not
    aborting on) anything that doesn't fit. A real numbered bibliography can still
    contain an incidental non-sequential digit-line match of its own (an observed
    case: a bare "246." from a wrapped page range *inside* a otherwise-correctly
    numbered list, or a bare "2019." from a wrapped publication year) — an
    all-or-nothing check would reject the whole heuristic over one stray line
    instead of just ignoring that line as ordinary entry content.
    """
    starts = [i for i, line in enumerate(lines) if marker_re.match(line)]
    if len(starts) < 2:
        return None
    if require_sequential:

        def run_from(first: int) -> list[int]:
            expected = first
            filtered: list[int] = []
            for i in starts:
                if int(marker_re.match(lines[i]).group(1)) == expected:
                    filtered.append(i)
                    expected += 1
            return filtered

        # A run starting at 1 is the whole bibliography and needs no further evidence.
        # A run starting anywhere else is either a real list whose first marker was
        # lost upstream (a page-break merge can absorb "1."), or the stray digit lines
        # of a non-numbered bibliography — wrapped years and page ranges ("246.",
        # "2019."). What separates them isn't run length but content: a real entry has
        # words after its marker, a wrapped number has none.
        run = run_from(1)
        if len(run) < 2:
            # Every candidate is tried as the anchor, not just the first one. A stray
            # digit line *ahead* of the real run (the wrapped page range of an entry
            # whose own "1." was absorbed upstream) used to be the only anchor
            # considered: run_from(246) found one wordless line, the words gate
            # rejected it, and the whole block came back unsplit — a numbered
            # bibliography left as a single entry because of one line of page range.
            candidates = (int(marker_re.match(lines[i]).group(1)) for i in starts)
            runs = (run_from(number) for number in sorted(set(candidates)))
            worded = (
                candidate
                for candidate in runs
                if all(_has_entry_words(marker_re.sub("", lines[i], count=1)) for i in candidate)
            )
            run = max(worded, key=len, default=[])
        starts = run
        if len(starts) < 2:
            return None

    entries: list[str] = []
    # Anything before the first marker is either a leftover heading or a real entry
    # whose marker was lost; dropping it unconditionally would delete a reference, so
    # the same distinction _entries_between makes is made here.
    leading = "\n".join(lines[: starts[0]]).strip()
    if leading and not _is_heading_fragment(leading):
        entries.append(leading)
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        chunk = marker_re.sub("", "\n".join(lines[start:end]).strip(), count=1).strip()
        entries.append(chunk)
    return entries


def _entries_from_year_gated_starts(lines: list[str], marker_re: re.Pattern[str]) -> list[str] | None:
    """Author-start variant of _entries_from_line_starts, author-list-wrap aware.

    A plain "line starts with an author-name pattern" test also matches a co-author's
    name on a line where a long author list has wrapped mid-entry (e.g. "Borsboom,
    D., ..., McNally, R. J., ... (2021). Title.", wrapped so "McNally, R. J.," opens
    its own line) — splitting there truncates the real entry and invents a bogus
    second one with no authors of its own. So a candidate start line is only accepted
    once the entry built up so far already contains a "(YYYY)"-style year, i.e. looks
    complete; until then, matching lines are treated as continuations.

    Entries with no parenthesised year at all (e.g. "(n.d.)", "(in press)") would
    otherwise block every later split forever, so a line count cap acts as a
    fallback: past _MAX_ENTRY_LINES since the last accepted start, a matching line
    is accepted regardless, on the assumption a real bibliography entry doesn't run
    that long unbroken.
    """
    starts: list[int] = []
    has_year_since_last_start = True  # allow the very first candidate unconditionally
    lines_since_last_start = 0
    for i, line in enumerate(lines):
        line_has_year = bool(DATE_SLOT_RE.search(line))
        candidate = marker_re.match(line) and (
            has_year_since_last_start or lines_since_last_start >= _MAX_ENTRY_LINES
        )
        if candidate:
            starts.append(i)
            # Carry over whether *this* start line already shows its own year
            # (a single-line entry like "Borsboom, D. (2017). ...") instead of
            # always resetting to False, which would forget that fact and block
            # the next legitimate split until some later line happens to repeat it.
            has_year_since_last_start = line_has_year
            lines_since_last_start = 0
        else:
            if line_has_year:
                has_year_since_last_start = True
            if starts:
                lines_since_last_start += 1

    if len(starts) < 2:
        return None

    entries: list[str] = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        entries.append("\n".join(lines[start:end]).strip())
    return entries


def _entries_from_blank_lines(text: str) -> list[str] | None:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if len(blocks) < 2:
        return None
    return [" ".join(line.strip() for line in block.splitlines()) for block in blocks]


def _entries_from_inline_apa_starts(text: str) -> list[str] | None:
    """Split APA entries even when PDF extraction joins multiple entries on one line.

    Unlike _entries_from_year_gated_starts, a candidate here can sit anywhere in a
    line, which also matches the editors of an edited-book chapter ("... A chapter.
    In Smith, A. B., & Jones, C. D. (Eds.), The handbook ..."). Splitting there
    truncates a real entry *and*, because the fragment that follows carries no year
    of its own, blocks the year gate from accepting the genuinely next entry — one
    inline editor list swallows two references. A candidate whose surname is directly
    preceded by a coordinating word ("In", "&", "and", "with") is therefore never a
    start: those introduce a co-author or editor within the current entry. The check
    has to look at what precedes the *surname*, not the whole match — the pattern's
    optional particle prefix (for "van der Veen, D.") happily absorbs the connector
    itself, so "In Smith, A." arrives with "In" already inside the match.

    A publisher location ("... Hillsdale, N.J.: Lawrence Erlbaum") has the same
    "Surname, I." shape, and unlike the editor case it sits *after* the entry's year,
    so the year gate accepts it. It's told apart by what follows: a second initial
    that runs straight into a colon is a state abbreviation, never an author's.
    """
    starts: list[int] = []
    for match in _APA_AUTHOR_ANYWHERE_RE.finditer(text):
        start, surname = match.start(1), match.start("surname")
        # Bounded look-back: both signals sit immediately before the name, so scanning
        # the whole prefix here would make the pass quadratic in text size.
        before = text[max(0, surname - _CONNECTOR_LOOKBACK) : surname]
        if _INLINE_CONNECTOR_BEFORE_RE.search(before):
            continue
        if not _ENTRY_BOUNDARY_BEFORE_RE.search(text[max(0, start - _BOUNDARY_LOOKBACK) : start]):
            continue
        if not starts:
            starts.append(start)
            continue
        current = text[starts[-1] : start]
        if DATE_SLOT_RE.search(current) or current.count("\n") >= _MAX_ENTRY_LINES:
            starts.append(start)
    if len(starts) < 2:
        return None
    return _entries_between(text, starts)


def _entries_between(text: str, starts: list[int], strip_marker: re.Pattern[str] | None = None) -> list[str]:
    """Slice text at the given start offsets, keeping anything before the first one.

    Text ahead of the first start is usually a reference too — a corporate author
    ("World Health Organization. (2020). ...") opens with no "Surname, I." and no
    number, so it precedes every candidate. Dropping that slice silently loses a
    reference from a *reference-checking* pipeline, which is worse than emitting an
    entry the heuristic couldn't attribute a start to, so it's kept as its own entry.

    A leftover section heading ("References") is the one thing that reliably sits
    there and *isn't* a reference, so a short fragment with no year is dropped rather
    than passed downstream as a phantom entry to check.
    """
    leading = text[: starts[0]].strip()
    bounds = ([0] if leading and not _is_heading_fragment(leading) else []) + starts

    entries: list[str] = []
    for pos, start in enumerate(bounds):
        end = bounds[pos + 1] if pos + 1 < len(bounds) else len(text)
        entry = text[start:end].strip()
        if strip_marker is not None:
            entry = strip_marker.sub("", entry, count=1).strip()
        entries.append(" ".join(line.strip() for line in entry.splitlines() if line.strip()))
    return entries


class Flattening(Enum):
    """Evidence that a conservative split left several references stuck together.

    Named rather than collapsed into one boolean because each reason licenses a
    *different* recovery, and that pairing was previously invisible: the three signals
    sat in one any() and any of them opened the door for both recovery heuristics. A
    removal experiment found the consequence — a bare-year count is dense in numbered
    and comma-year styles and says nothing about APA anchors, so it was licensing
    inline-APA recovery on text where that recovery can only ever be wrong, and
    downstream guards were left to close a gate that should not have opened.
    """

    PAREN_YEARS = "two or more parenthesised years in one entry"
    INLINE_NUMBER_RUN = "a run of ascending N. markers mid-text"
    BARE_YEARS = "several unparenthesised years in one entry"


def _flattening_evidence(entries: list[str]) -> set[Flattening]:
    """Which flattening signals a conservative split shows, if any.

    One entry carrying the publication data of two is the signal that a block holds
    more than one reference, which is when a recovery heuristic should be allowed to
    re-split it. Gating on that (rather than on which heuristic simply yields more
    entries) keeps inline splitting away from a well-formed bibliography, where any
    extra "entries" it finds are over-splits of a single reference, not recoveries.

    Three signals, because only APA-style entries carry a "(YYYY)": Vancouver and IEEE
    write the year as "1954;228:1451-5", and a flattened numbered list of any style
    shows its markers mid-text. Without the latter two, a flattened non-APA
    bibliography that kept even one blank line would look intact and never be
    recovered — the blank line splits it into blocks, and no block has two years.
    """
    evidence: set[Flattening] = set()
    for entry in entries:
        if len(YEAR_PAREN_RE.findall(entry)) >= 2:
            evidence.add(Flattening.PAREN_YEARS)
        if len(_inline_number_starts(entry)) >= _MIN_INLINE_NUMBER_RUN:
            evidence.add(Flattening.INLINE_NUMBER_RUN)
        if len(BARE_YEAR_RE.findall(entry)) >= _MIN_YEARS_PER_FLATTENED_ENTRY:
            evidence.add(Flattening.BARE_YEARS)
    return evidence


def _entries_from_inline_number_starts(text: str) -> list[str] | None:
    """Recover a numbered bibliography flattened into Markdown table-cell text.

    An inline "N." is a far weaker anchor than one at the start of a line: ordinary
    reference text is full of them — German editions ("(1. Aufl.). Springer"), German
    retrieval dates ("Abgerufen am 1. Januar 2021"), APA volume titles ("Handbook of
    child psychology: Vol. 1. Theoretical models"). Two of those in ascending order
    is not evidence of a numbered bibliography, so a longer run is required, and the
    caller only reaches this heuristic once the line-based anchors have all failed.
    """
    starts = _inline_number_starts(text)
    if len(starts) < _MIN_INLINE_NUMBER_RUN:
        return None
    return _entries_between(text, starts, strip_marker=_INLINE_MARKER_PREFIX_RE)


def _inline_number_starts(text: str) -> list[int]:
    """Offsets of an ascending inline "1. 2. 3. ..." run at entry boundaries.

    The boundary requirement is what separates a flattened numbered list from an
    edition or volume number, which sits mid-sentence and usually in brackets:
    "(1. Aufl.). Springer ... (2. Aufl.). Beltz ... (3. Aufl.). Hogrefe" is an
    ascending run of three, and without this it splits a perfectly good German
    bibliography at every edition instead of at its entries.
    """
    starts: list[int] = []
    expected = 1
    for match in _INLINE_DOT_NUMBER_RE.finditer(text):
        start = match.start()
        if int(match.group(1)) != expected:
            continue
        at_boundary = _ENTRY_BOUNDARY_BEFORE_RE.search(text[max(0, start - _BOUNDARY_LOOKBACK) : start])
        # The very first marker may instead follow a leftover section heading, which
        # is the one thing that legitimately sits in front of a bibliography.
        if not at_boundary and not (not starts and _is_heading_fragment(text[:start])):
            continue
        starts.append(start)
        expected += 1
    return starts


def _is_heading_fragment(text: str) -> bool:
    """Whether a fragment is a leftover section heading rather than a reference.

    Short and carrying no year — "References", "Literaturverzeichnis". Used both to
    let a numbered run start after one and to keep it from being emitted as an entry.
    """
    stripped = text.strip()
    return bool(stripped) and len(stripped) < _MIN_LEADING_FRAGMENT_CHARS and BARE_YEAR_RE.search(stripped) is None


@dataclass(frozen=True)
class SplitGate:
    """One heuristic in split_bibliography_block's ordered cascade.

    `recoverable` is what used to be implicit in *where* a heuristic's call sat in
    the function body — whether success there returned immediately or only fed a
    later check:

    - `recoverable=False` ("hard" gate): the three numbered-marker heuristics. The
      first one that finds >=2 sequential markers wins outright and
      split_bibliography_block returns its result immediately — the
      flattening-evidence/recovery step below never runs for that result at all.
    - `recoverable=True` ("soft" gate): blank-line blocks and the APA/JSS
      author-start fallbacks. The first one of these that succeeds becomes the
      "conservative" baseline, but that baseline is still subject to
      _flattening_evidence and may yet be replaced by a recovery heuristic below —
      success here does not short-circuit the rest of the function.

    attempt takes the split candidate's lines (the split unit every heuristic here
    ultimately works from, even _entries_from_blank_lines which re-derives them from
    text) and returns None when its anchor isn't found or found fewer than two times.
    """

    name: str
    attempt: Callable[[list[str]], list[str] | None]
    recoverable: bool


def _numbered_gates() -> list[SplitGate]:
    """The three numbered-marker anchors, tried in order of how unambiguous they are.

    1. "[1] ..." (IEEE/numbered styles) — most unambiguous anchor.
    2. "1. ..." / "1) ..." — same idea, no brackets.
    3. Bare "1 ..." with no punctuation (e.g. some medical/epidemiology journals).
       Riskiest of the three, so it only runs if 1 and 2 found nothing.

    All three additionally require their captured numbers to run sequentially (see
    require_sequential in _entries_from_line_starts) — otherwise a justified
    bibliography whose page ranges wrap onto their own line (leaving a bare "246.")
    can produce >=2 coincidental "marker" hits and hijack the split with a
    nonsensical result, when falling through to blank-line/APA would have worked.
    """
    return [
        SplitGate(
            name,
            lambda lines, marker_re=marker_re: _entries_from_line_starts(
                lines, marker_re, require_sequential=True
            ),
            recoverable=False,
        )
        for name, marker_re in (
            ("bracket-number", _BRACKET_NUMBER_RE),
            ("dot-number", _DOT_NUMBER_RE),
            ("bare-number", _BARE_NUMBER_RE),
        )
    ]


def _conservative_gates(text: str) -> list[SplitGate]:
    """The blank-line and author-start anchors, tried in order of specificity.

    4. Blank-line-separated blocks — common when a numbering scheme isn't used but
       entries are still visually separated (e.g. copy-pasted from a word processor).
    5. APA-style line fallback: a new entry starts where a line opens with "Surname, I."
    6. JSS-style fallback: a new entry starts where a line opens with "Surname II"
       (no comma, all-caps initials with no periods — e.g. Journal of Statistical
       Software's own citation style). Tried last since it's the least specific
       anchor of the three fallbacks.

    text is captured directly rather than threaded through `attempt`'s lines
    parameter because _entries_from_blank_lines works on unsplit text (a blank line
    is precisely the thing splitlines() would already have discarded).
    """
    return [
        SplitGate("blank-lines", lambda lines: _entries_from_blank_lines(text), recoverable=True),
        SplitGate(
            "apa-author-start",
            lambda lines: _entries_from_year_gated_starts(lines, _APA_AUTHOR_START_RE),
            recoverable=True,
        ),
        SplitGate(
            "jss-author-start",
            lambda lines: _entries_from_year_gated_starts(lines, _JSS_AUTHOR_START_RE),
            recoverable=True,
        ),
    ]


def split_bibliography_block(text: str) -> list[RawReferenceEntry]:
    """Split a bibliography section's raw text into individual reference entries.

    Walks a single ordered list of SplitGates — _numbered_gates() then
    _conservative_gates() — and picks the first one that finds at least two entries,
    since a single "entry" almost always means the heuristic didn't match rather than
    a one-reference bibliography. Each gate's own `recoverable` field (not its
    position in one list or the other) decides what a match does next: a hard gate
    (`recoverable=False`, the three numbered-marker heuristics) returns its result
    immediately. A soft gate (`recoverable=True`, blank-line blocks and the APA/JSS
    fallbacks) only produces a "conservative" baseline that the flattening-evidence/
    recovery logic below still gets to examine and possibly replace — see
    _flattening_evidence's docstring for why that check exists at all.

    Two *recovery* heuristics handle text where extraction flattened several entries
    together, which none of the gates above can split because the boundaries they
    anchor on (a line start, a blank line) no longer exist. Both look for markers
    mid-line, so both are much weaker than their line-based counterparts — ordinary
    reference text is full of inline "N." (German editions, "Vol. 1. Theoretical
    models") and inline "Surname, I." (an edited-book chapter's editors, a publisher
    location). They are therefore never allowed to compete with a gate above on entry
    count, which is what an over-split looks like too. They run only when the
    conservative pass above either found nothing at all, or produced an entry that
    visibly holds more than one reference (see _looks_flattened) — and then only if
    they actually split that further. This part stays a fixed sequence rather than
    table-driven, since (unlike the gates above) each recovery is licensed by a
    specific evidence type rather than competing head to head.

    If none of these produce at least two entries, the whole block is returned as a
    single raw entry rather than raising — callers (e.g. the manual-review flow) can
    still decide what to do with an unsplit block.
    """
    lines = text.splitlines()

    conservative: list[str] | None = None
    for gate in _numbered_gates() + _conservative_gates(text):
        found = gate.attempt(lines)
        if found is None:
            continue
        if not gate.recoverable:
            return [RawReferenceEntry(i, entry) for i, entry in enumerate(found, start=1)]
        conservative = found
        break

    evidence = _flattening_evidence(conservative) if conservative is not None else None
    if evidence is not None and not evidence:
        return [RawReferenceEntry(i, entry) for i, entry in enumerate(conservative, start=1)]

    # Each recovery names the evidence that licenses it, so "which gate protects which
    # recovery" is readable rather than something to rediscover by experiment. A
    # bare-year count is dense in numbered and comma-year styles and says nothing
    # about APA anchors, so it licenses only the numbered recovery. `evidence is None`
    # means the conservative pass found nothing at all — there is no split to judge,
    # and every recovery is eligible. Called lazily: the second heuristic's full regex
    # scan used to run even when the first had already won.
    for licensed_by, recover in (
        ({Flattening.INLINE_NUMBER_RUN, Flattening.BARE_YEARS}, _entries_from_inline_number_starts),
        ({Flattening.PAREN_YEARS}, _entries_from_inline_apa_starts),
    ):
        if evidence is not None and not (evidence & licensed_by):
            continue
        recovered = recover(text)
        if recovered is not None and (conservative is None or len(recovered) > len(conservative)):
            return [RawReferenceEntry(i, entry) for i, entry in enumerate(recovered, start=1)]

    if conservative is not None:
        return [RawReferenceEntry(i, entry) for i, entry in enumerate(conservative, start=1)]

    stripped = text.strip()
    return [RawReferenceEntry(1, stripped)] if stripped else []
