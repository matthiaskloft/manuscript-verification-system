"""Tier-0 detection of in-text citation markers in body text.

The regex-only half of citation detection (docs/plans/plan-in-text-citation-parsing.md,
Phase 2). Tier 1 reads GROBID's own `<ref type="bibr">` markup and knows exactly which
bibliography entry each marker points at; this module has nothing but the characters on
the page. It is still the required path rather than a token fallback: DOCX has no GROBID
route at all, and GROBID can be unavailable or switched off for PDFs too.

What it produces is deliberately *detection*, not matching. A `DetectedCitation` says
"a marker sits at these offsets and names this author and this year" — it never says
which reference that is. Resolving a marker to a `ReferenceResult` is the matching
engine's job (Phase 4), and keeping the two apart is what lets an unresolvable marker
stay explicitly unresolved instead of being quietly attached to the nearest entry.

**One record per reference, one span per marker.** "(Doe, 2020; Roe, 2019)" is two
`DetectedCitation`s carrying the same `start`/`end`. The alternative — one record per
marker, carrying a list — pushes the group everywhere downstream: "cited N times" has
to count list elements, and orphaned/unused flags have to reach inside a group to say
which member failed. GROBID's Tier 1 output already splits grouped citations into
separate `<ref>` elements, so this is also the shape both tiers agree on.

**Precision over recall, everywhere the two conflict.** A missed marker costs a check
that isn't run; a spurious one becomes a displayed "orphaned citation", which is a
report of an authoring error that isn't there. So the exclusions below are aggressive,
and a marker whose author component doesn't hold together as a name is dropped rather
than emitted with a guess at what it meant.

Known limits, stated rather than papered over:

- Bare superscript Vancouver numerals ("...evidence.¹²") are not detected. They rarely
  survive PDF-to-text extraction as anything distinguishable from surrounding digits;
  the plan records this as a coverage gap that folds into "not detected".
- `authors` is the author component *as written* ("van der Veen and Smith", "Müller
  u. a."), not a parsed surname list. Splitting that reliably is the same problem the
  matching engine already has to solve with fuzzy comparison, so it is solved once,
  there, rather than half-solved twice.
- A narrative marker is any name-shaped run followed by a parenthesised year, so an
  English work referred to by title ("The Handbook (2020) lists...") reads as one. The
  matching engine sees it as a marker that resolves to nothing, which is the same
  state a genuine orphan is in — the two are distinguished by evidence there, not by
  a dictionary here. The German equivalent is excluded, because German capitalises
  every noun and the article in front of one is a reliable cue; English "the" is not,
  since "the Doe et al. (2020) study" is ordinary prose.
- An in-sentence enumeration in a numbered-style document ("...: (1) that x, (2) that
  y") is written exactly like a Vancouver marker. The colon before the first item is
  detected; the later items are not, and are emitted as citations. Reference numbers
  that resolve to nothing are the visible symptom, and only in documents whose
  bibliography is numbered with no author-date evidence at all.
- An institutional author is not detected in the author-date family. "(World Health
  Organization, 1948)" is missed entirely, and its narrative form is read as an author
  called "Organization". An author run is a sequence of capitalised surnames with
  optional particles, and a multi-word capitalised phrase is what ordinary prose looks
  like at the start of a sentence, so admitting one costs far more precision than the
  case is worth here. A corporate author is a known shape in a bibliography entry, so
  the matching engine can recognise it from the entry side, where the evidence is.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from enum import Enum

from refcheck.extraction.signals import BRACKET_NUMBER_RE, NO_DATE, YEAR
from refcheck.extraction.style_profile import StyleProfile


class MarkerFamily(Enum):
    """Which citation grammar a marker is written in.

    Not a style: APA, Chicago author-date and the German APA variant all write
    "(Surname, Year)" with different punctuation, and one detector covers all three.
    The families differ in what a marker *is* — a name and a date, or an index into a
    numbered list — which is the distinction that changes how it has to be parsed and,
    later, matched.
    """

    AUTHOR_DATE = "author-date"
    NUMBERED = "numbered"


@dataclass(frozen=True)
class DetectedCitation:
    """One reference named by one in-text marker.

    `start`/`end` are offsets into the text passed to `detect_citations` — the body
    text of a `DocumentArtifact`, in the pipeline — so `artifact.anchor_for(start, end)`
    turns a detection into a position a reviewer can be sent to. The text itself is not
    carried beyond `marker_text` (the marker, not its surroundings): raw context is
    looked up from the artifact only when a reviewer has explicitly asked to see it.

    Members of a grouped marker share `marker_text`, `start` and `end`, and differ in
    the reference fields.
    """

    family: MarkerFamily
    marker_text: str
    start: int
    end: int
    authors: str | None = None
    year: str | None = None
    number: int | None = None
    narrative: bool = False


# --------------------------------------------------------------------------------------
# Name and date vocabulary
# --------------------------------------------------------------------------------------

# Surname particles, kept as an explicit list rather than "any lowercase word" because
# the latter turns every sentence into a potential author run. Covers the Dutch/German/
# Romance particles a European reference list actually carries.
#
# Single words only. "van der" is already reachable as "van" then "der" through the
# repetition below, and listing the pair as well makes the same input matchable two ways
# — the ambiguity that turns a failing author run into exponential backtracking, since
# the run is anchored and every alternative has to be tried before the match can fail.
_PARTICLE = r"(?:van|von|de|del|della|den|der|des|di|dos|du|da|la|le|ten|ter|zu|zur)"

# A surname: optional disambiguating initials, optional particles, then a capitalised
# word. Digits are excluded on purpose — "Table 1" and "Study 2" are the shapes this
# must not read as a name. The initials are there because both target styles print them
# in-text when two cited authors share a surname ("(S. Fischer, 2020)"), and because the
# page-locator cue has to be able to tell that "S." from "S. 15".
_SURNAME = rf"(?:[A-ZÀ-Ý]\.\s*){{0,3}}(?:{_PARTICLE}\s+)*[A-ZÀ-Ý][A-Za-zÀ-ÿ'’\-]*"

# "and others", in the forms this project's two target languages print it.
_ETAL = r"(?:et\s+al\.?|u\.\s?a\.|et\s+alii)"

# What may join two surnames in one author run. Plain adjacency is deliberately *not*
# in this list: "Recent Work Doe (2020)" would otherwise read as a three-word author
# name, and requiring a connector or a particle is what keeps Title Case prose out.
_JOINER = r"(?:\s*,\s*(?:and\s+|und\s+|&\s+)?|\s+(?:and|und|&)\s+)"

_AUTHOR_RUN = rf"{_SURNAME}(?:{_JOINER}{_SURNAME}){{0,4}}(?:\s*,?\s*{_ETAL})?"
_AUTHOR_RUN_RE = re.compile(rf"{_AUTHOR_RUN}\Z")

# A date as an in-text marker writes it: bare, inside the citation's own parentheses,
# with the letter suffix that disambiguates two works by the same author in one year.
# YEAR and NO_DATE come from signals.py rather than being restated here — see that
# module's docstring on what two independent definitions of "is this a year" cost.
_DATE_TOKEN = rf"(?:{YEAR}[a-z]?|(?i:{NO_DATE}))"
_DATE_TOKEN_RE = re.compile(rf"(?<![\d.]){_DATE_TOKEN}(?![\d])")

# Sentence connectives that can sit directly before a citation and are capitalised
# because they open a sentence, not because they are names. Without this, "However,
# Doe (2020) found..." reads as an author run of "However, Doe". The list only has to
# cover words that are followed by a comma often enough to slip past _JOINER.
_STOPWORD = (
    r"(?:However|Therefore|Thus|Moreover|Furthermore|Additionally|Similarly|Finally|Indeed|"
    r"Nevertheless|Nonetheless|Hence|Consequently|Accordingly|Recently|Previously|Notably|"
    r"Interestingly|Importantly|Conversely|Specifically|Overall|First|Second|Third|Instead|"
    r"Jedoch|Allerdings|Daher|Somit|Zudem|Außerdem|Ausserdem|Ferner|Schließlich|Schliesslich|"
    r"Deshalb|Folglich|Kürzlich|Bereits|Dabei|Hierbei|Insbesondere|Zunächst|Ebenso|Zwar)"
)

# German capitalises every common noun, so the structural test that keeps English prose
# out — "a capitalised word before a parenthesised year" — passes on "Die Befragung
# (2020)" and "Der Datensatz (2019)" as readily as on a surname. The determiner in front
# is the discriminator: a narrative marker names an author, and an author is not preceded
# by an article. English "the" is deliberately absent, because "the Doe et al. (2020)
# study" is ordinary English and dropping it would cost real markers; the English cost of
# leaving it out is the title-as-author limit the module docstring already states.
#
# The intervening words are the adjectives a noun phrase carries ("Die zweite Welle
# (2021)"). They have to be lowercase-only, which is why this pattern spells its own
# case class instead of taking re.IGNORECASE: a capitalised word between the article and
# the year is a surname, and "der Beitrag von Doe (2020)" must stay a citation.
_DETERMINER = (
    r"(?:[Dd](?:er|ie|as|en|em|es)|[Ee]in(?:e|er|es|em|en)?|[Dd]ies(?:e|er|es|em|en)|"
    r"[Jj]en(?:e|er|es|em|en)|[Jj]ed(?:e|er|es|em|en)|[Ss]olch(?:e|er|es|em|en))"
)
_DETERMINER_BEFORE_RE = re.compile(
    rf"(?:^|[^A-Za-zÀ-ÿ]){_DETERMINER}\s+(?:[a-zà-ÿ][A-Za-zÀ-ÿ'’\-]*\s+){{0,3}}\Z"
)

# A narrative citation: "Doe (2020)", "Doe and Roe (2020a, 2020b)", "Müller u. a. (2019)".
# The trailing [^()]* absorbs a locator ("Doe (2020, p. 15)") without letting the match
# escape the parentheses — but it must not absorb the second half of a year *range*:
# "(1939-1945)", "(2014-2020)" and "(1770-1827)" are a war, a funding period and a
# lifespan, and every one of them sits behind a capitalised word in ordinary prose. The
# lookahead rejects the span outright rather than reading its first year as a date.
_DATE_LIST = rf"{_DATE_TOKEN}(?:\s*[,;]\s*{_DATE_TOKEN})*"
_NARRATIVE_RE = re.compile(
    rf"(?<![A-Za-zÀ-ÿ'’\-])(?!{_STOPWORD}\b)({_AUTHOR_RUN})\s*\(\s*({_DATE_LIST})"
    rf"(?!\s*[-–—]\s*\d)([^()]*)\)"
)

# Balanced-free spans: a marker never contains a nested bracket of its own kind, and
# refusing to match across one is what keeps "(t(28) = 2.1, p = .04)" from being read
# as a single citation-shaped span.
_PAREN_SPAN_RE = re.compile(r"\(([^()]{1,400})\)")
_BRACKET_SPAN_RE = re.compile(r"\[([^\[\]]{1,400})\]")

# Words that introduce a citation inside the parentheses rather than being part of it.
_LEAD_IN_RE = re.compile(
    r"^\s*(?:see\s+also|see|cf\.|e\.\s?g\.,?|i\.\s?e\.,?|compare|reviewed\s+in|as\s+cited\s+in|"
    r"vgl\.\s?(?:auch)?|siehe\s?(?:auch)?|z\.\s?B\.,?|zit\.\s?nach|nach|etwa)\s+",
    re.IGNORECASE,
)

# A page/chapter locator. Everything from here to the end of a chunk is not a date, which
# matters because "(Doe, 2020, pp. 1990-1995)" otherwise contributes three year-shaped
# numbers. The mandatory digit is what keeps "S." usable as a locator cue without
# swallowing the initial in "(S. Fischer, 2020)".
_LOCATOR_RE = re.compile(
    r"[,;]?\s*(?:pp?\.|S\.|ff?\.|Kap\.|Abs\.|Abschn\.|chap\.|ch\.|sec\.|para\.|"
    r"Chapter|Kapitel|Abschnitt|Section|Seite[n]?|page[s]?)\s*\d",
    re.IGNORECASE,
)

# Calendar words: "(Oktober 2021)", "(October 2021)" and "(Fall 2020)" are dates in
# prose, and a bare month or season name satisfies every structural test for a one-word
# surname followed by a year. Seasons are here for the same reason months are — a data
# collection window is written "(Spring 2021)" as often as "(March 2021)".
_MONTH_RE = re.compile(
    r"^(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Januar|Februar|März|Maerz|Mai|Juni|Juli|Oktober|Dezember|Jan|Feb|Mar|Mär|Apr|Jun|Jul|Aug|"
    r"Sep|Sept|Okt|Oct|Nov|Dez|Dec|"
    r"Spring|Summer|Autumn|Fall|Winter|Frühjahr|Fruehjahr|Frühling|Fruehling|Sommer|Herbst)\.?$",
    re.IGNORECASE,
)

# Cross-reference nouns. As an "author" these produce "(Figure 2020)"-shaped nonsense; in
# front of a numeral they produce "see Eq. (1)", which is the collision that actually
# happens in a numbered-style manuscript.
_CROSSREF_WORD = (
    r"(?:Figures?|Fig\.?|Tables?|Tab\.?|Equations?|Eq\.?|Eqn\.?|Sections?|Sect\.?|Appendix|"
    r"Appendices|Chapters?|Steps?|Panels?|Boxes|Box|Notes?|Lines?|"
    r"Abbildung(?:en)?|Abb\.?|Tabelle(?:n)?|Gleichung(?:en)?|Gl\.?|Abschnitt(?:e)?|Anhang|"
    r"Anhänge|Kapitel|Schritt(?:e)?|Zeile(?:n)?|Fußnote(?:n)?|Fussnote(?:n)?)"
)
_CROSSREF_AUTHOR_RE = re.compile(rf"^{_CROSSREF_WORD}\Z", re.IGNORECASE)
_CROSSREF_BEFORE_RE = re.compile(rf"{_CROSSREF_WORD}\s*\Z", re.IGNORECASE)

# Statistical reporting inside parentheses: "(p < .05)", "(M = 3.2, SD = 0.4)",
# "(95% CI [0.2, 0.5])", "(N = 120)". A comparison operator or a percent sign is the
# cheap, near-perfect discriminator — no citation marker contains either.
_STATISTICS_RE = re.compile(r"[=<>≤≥≠%]|\bCI\b|\bKI\b")

# The same cue, read backwards from a bracketed span, for "95% CI [2, 5]" — an interval
# whose bounds happen to be whole numbers is otherwise indistinguishable from "[2, 5]"
# as a grouped numeric citation. "range" and a scale's "from" are the other two ways a
# manuscript writes an integer-bounded interval in brackets. "between" is deliberately
# not a cue: "differences between [3] and [4]" is a real pair of citations.
_INTERVAL_BEFORE_RE = re.compile(
    r"(?:\bCI\b|\bKI\b|interval|Intervall|range[ds]?|ranging|Bereich|"
    r"scale\s+from|Skala\s+von)[^\[\]]{0,20}\Z",
    re.IGNORECASE,
)

# A run of numbers and separators, and nothing else: "[12]", "[1, 2, 3]", "[4-7]",
# "[1; 2]". Anything with a decimal point, a letter or a stray symbol is not a marker.
_NUMERIC_GROUP_RE = re.compile(r"\s*\d{1,3}(?:\s*[-–—,;]\s*\d{1,3})*\s*\Z")
_NUMERIC_RANGE_RE = re.compile(r"(\d{1,3})\s*[-–—]\s*(\d{1,3})")

# A numeric range longer than this is a page span or a measurement, not a citation group.
_MAX_RANGE_LENGTH = 40

# What tells a wrapped citation apart from a display equation's number, when both end
# their line with "(3)": what comes before it on that line. Prose runs to several words
# and ends in one; an equation carries an operator or ends in a digit, and an equation
# number sitting alone on its own line has nothing before it at all.
_PROSE_BEFORE_RE = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-]*\Z")
_MATH_BEFORE_RE = re.compile(r"[=+×·∑∫√≈≤≥<>^_]|\d\s*\Z")
_MIN_PROSE_WORDS = 4

# A colon introduces a list, and an in-sentence enumeration writes its items exactly the
# way Vancouver writes a citation: "three hypotheses: (1) that...". Only the colon
# separates the two, so it is a cue rather than a general solution — an enumeration's
# later items are indistinguishable from markers and are a stated limit.
_ENUMERATION_BEFORE_RE = re.compile(r":\s*\Z")

# How far back a cue pattern is allowed to look, counted in words.
#
# Every pattern below that reads *backwards* from a marker is anchored with \Z, so it can
# only match text immediately preceding it. Searching the whole prefix for one is what
# made this module quadratic: each accepted marker re-scanned every character before it,
# so a manuscript with twice the markers cost four times the time — 78 s on a 114 KB
# numbered review article, inside the check, before verification runs.
#
# Python's search(text, pos, endpos) anchors \Z at endpos and, unlike slicing, refuses to
# match ^ at pos, so a window is exact for the "^ or a non-letter" alternation as long as
# the window can hold the whole match.
#
# **Words, not characters, because that is the unit these grammars are bounded in.** A
# character window was tried first and was not exact, which PR #64's review caught: none of
# these patterns limits how long a word may be. `_DETERMINER_BEFORE_RE` allows three
# intervening words of `[A-Za-zÀ-ÿ'’\-]*`, so "Die" + three 200-character tokens + "Doe
# (2020)" sits outside any fixed window while remaining inside the grammar — and PDF
# extraction produces exactly that when it loses the spaces between words. Nor is the
# whitespace bounded: `_INTERVAL_BEFORE_RE`'s "scale\s+from" tolerates a column break's
# worth of it between the two halves of its own cue. Both were false *positives* — a
# marker the base implementation suppressed and the window let through — which is the
# direction this module treats as worse, because it reaches a reviewer as an authoring
# error that is not there.
#
# A word walk is exact for every one of them at any word length and any whitespace length.
# Twelve is the largest count any pattern can span, and the largest is the interval cue:
# `(?:...|scale\s+from)[^\[\]]{0,20}\Z` is two cue words plus a twenty-character tail, and
# twenty characters hold at most ten words ("a b c d e f g h i j" is nineteen). The others
# need far less — a determiner and at most three words is four, and the two cue-word
# patterns are one each — so the bound is set by the interval and shared.
_CUE_WORDS = 12

# The character class the degrees-of-freedom guard rejects: a marker never touches the
# preceding word. Held as a set because it is now tested one character at a time rather
# than with endswith() over a copy of everything before the marker.
_WORD_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz²")


def _cue_start(text: str, position: int) -> int:
    """Where a backwards cue search may begin, for a marker starting at `position`.

    `_CUE_WORDS` words back, skipping whitespace runs of any length on the way — so the
    window holds any match these grammars admit however long its words are and however far
    a column break pushed them apart. One character further, so a pattern opening on
    "either the start of the text or a non-letter" always has that character to match; at
    the start of the text the walk returns 0, where `^` matches instead.
    """
    cursor = position
    for _ in range(_CUE_WORDS):
        while cursor > 0 and text[cursor - 1].isspace():
            cursor -= 1
        while cursor > 0 and not text[cursor - 1].isspace():
            cursor -= 1
        if cursor == 0:
            return 0
    return cursor - 1

# How a sentence ends, for telling a notes list ("[2] Kahneman argues...") apart from a
# citation that happens to land at the start of a wrapped line ("...as shown in\n[12],
# the effect..."). The cost is a real marker wrapped directly after an abbreviation's
# period, which is the trade this module makes everywhere the two conflict.
_SENTENCE_END = (".", "!", "?", '"', "”", "»", "’", ":")

# How much bibliography evidence counts as evidence at all. Two is the same "one
# occurrence is an accident" threshold tier0.py's split gates already use; it is not
# tuned, and it does not need to be, because a tie or an absence resolves to "expect
# both families" rather than to a wrong single answer.
_MIN_STYLE_EVIDENCE = 2


def expected_families(profile: StyleProfile) -> frozenset[MarkerFamily]:
    """Which marker families the bibliography's own style evidence supports.

    Cross-validation, not classification — the same "evidence, not verdict" stance
    `style_profile.py` takes, for the same reason: a bibliography that is numbered says
    something real about what its in-text markers look like, and a detector that ignores
    it has to guess at exactly the ambiguous cases ("(1)") where guessing is worst.

    Ambiguity resolves *upward*, to both families. A document whose bibliography shows
    neither pattern clearly is a document where narrowing the detector could only remove
    real markers, and the cost of running both detectors on it is a few regex passes.
    """
    numbered = max(profile.bracket_numbered_lines, profile.dot_numbered_lines) >= _MIN_STYLE_EVIDENCE
    author_date = (
        max(profile.paren_year_matches, profile.comma_year_matches, profile.jss_author_lines)
        >= _MIN_STYLE_EVIDENCE
    )

    if numbered == author_date:
        return frozenset(MarkerFamily)
    return frozenset({MarkerFamily.NUMBERED if numbered else MarkerFamily.AUTHOR_DATE})


def detect_citations(
    text: str,
    *,
    families: Collection[MarkerFamily] | None = None,
) -> tuple[DetectedCitation, ...]:
    """Every in-text citation marker in `text`, in document order.

    `families` narrows the search to the marker grammars the bibliography's evidence
    supports (see `expected_families`); `None` searches for all of them. Narrowing is
    what unlocks the one pattern too dangerous to run unconditionally: a parenthesised
    bare numeral, "(1)", which is also how the whole world numbers equations and list
    items. It is detected only when the numbered family is the *only* one expected —
    i.e. the bibliography itself is numbered and shows no author-date evidence.

    Offsets are into `text` exactly as given; no normalization happens here, so a caller
    holding a `DocumentArtifact` can hand `start`/`end` straight to `anchor_for`.
    """
    wanted = frozenset(families) if families is not None else frozenset(MarkerFamily)
    found: list[DetectedCitation] = []

    if MarkerFamily.AUTHOR_DATE in wanted:
        found.extend(_detect_author_date(text))
    if MarkerFamily.NUMBERED in wanted:
        found.extend(_detect_numbered(text, paren_numerals=wanted == frozenset({MarkerFamily.NUMBERED})))

    return tuple(sorted(found, key=lambda citation: (citation.start, citation.end)))


def parse_marker(marker_text: str) -> tuple[DetectedCitation, ...]:
    """What one marker names, for a caller that already knows it is a marker.

    `detect_citations` answers two questions at once: is this span a citation, and which
    references does it name. Tier 1 arrives with the first one already answered — GROBID
    marked the span as `<ref type="bibr">` — and only the second outstanding, for a marker
    it could not link to a bibliography entry itself. Running the full detector on that
    text answers the settled question wrongly: every exclusion here reads the marker's
    *surroundings*, and a marker handed over on its own has none. A bare "[3]" is
    line-initial with nothing above it, which is exactly the shape of a notes-list entry,
    so the detector correctly refuses it and a reference cited only through markers GROBID
    failed to link would be reported unused.

    So this is the parse without the adjudication. Offsets are into `marker_text` itself,
    which is not a position in any document; the caller that has one keeps it.
    """
    text = marker_text.strip()
    if not text:
        return ()

    inner = text[1:-1] if (text[0], text[-1]) in {("[", "]"), ("(", ")")} else text
    group_text = inner[: locator.start()] if (locator := _LOCATOR_RE.search(inner)) else inner
    if _NUMERIC_GROUP_RE.match(group_text):
        return tuple(
            DetectedCitation(
                family=MarkerFamily.NUMBERED,
                marker_text=text,
                start=0,
                end=len(text),
                number=number,
            )
            for number in _expand_numbers(group_text)
        )

    narrative = _NARRATIVE_RE.match(text)
    if narrative is not None and _is_plausible_author(narrative.group(1).strip()):
        return tuple(
            DetectedCitation(
                family=MarkerFamily.AUTHOR_DATE,
                marker_text=text,
                start=0,
                end=len(text),
                authors=narrative.group(1).strip(),
                year=year,
                narrative=True,
            )
            for year in _dates_in(narrative.group(2))
        )

    return tuple(_parenthetical_citations(inner, 0, len(text), text))


# --------------------------------------------------------------------------------------
# Author-date family
# --------------------------------------------------------------------------------------


def _detect_author_date(text: str) -> list[DetectedCitation]:
    found: list[DetectedCitation] = []

    for match in _PAREN_SPAN_RE.finditer(text):
        found.extend(_parenthetical_citations(match.group(1), match.start(), match.end(), match.group(0)))

    for match in _NARRATIVE_RE.finditer(text):
        authors = match.group(1).strip()
        if not _is_plausible_author(authors):
            continue
        if _DETERMINER_BEFORE_RE.search(text, _cue_start(text, match.start()), match.start()):
            continue
        marker = match.group(0)
        found.extend(
            DetectedCitation(
                family=MarkerFamily.AUTHOR_DATE,
                marker_text=marker,
                start=match.start(),
                end=match.end(),
                authors=authors,
                year=year,
                narrative=True,
            )
            for year in _dates_in(match.group(2))
        )

    return found


def _parenthetical_citations(
    content: str, start: int, end: int, marker: str
) -> list[DetectedCitation]:
    """Parse "(Doe, 2020; Roe & Fry, 2019)" into one record per reference.

    Returns nothing at all when any part of the span looks like something else — a
    statistic, a cross-reference, a calendar date. A partially-recognised span is not
    salvaged into "the bit I understood": the parenthesis is one authored construct, and
    reading half of it as a citation is how a statistic's confidence bounds become a
    citation to reference 2.
    """
    if _STATISTICS_RE.search(content):
        return []

    found: list[DetectedCitation] = []
    for chunk in content.split(";"):
        parsed = _parse_chunk(chunk)
        if parsed is None:
            continue
        authors, years = parsed
        found.extend(
            DetectedCitation(
                family=MarkerFamily.AUTHOR_DATE,
                marker_text=marker,
                start=start,
                end=end,
                authors=authors,
                year=year,
            )
            for year in years
        )
    return found


def _parse_chunk(chunk: str) -> tuple[str, list[str]] | None:
    """One semicolon-separated part of a parenthetical marker, or None if it isn't one.

    A chunk carries one author component and one or more dates: "(Doe, 2020a, 2020b)" is
    one author cited twice, not two authors. Dates after a page locator are not dates —
    "pp. 1990-1995" is a page range whose endpoints are year-shaped, which is the reason
    the locator is cut off before the search rather than filtered out after it.
    """
    locator = _LOCATOR_RE.search(chunk)
    body = chunk[: locator.start()] if locator else chunk

    first = _DATE_TOKEN_RE.search(body)
    if first is None:
        return None

    authors = _LEAD_IN_RE.sub("", body[: first.start()]).strip().strip(",").strip()
    if not _is_plausible_author(authors):
        return None

    return authors, _dates_in(body[first.start() :])


def _dates_in(text: str) -> list[str]:
    return [match.group(0) for match in _DATE_TOKEN_RE.finditer(text)]


def _is_plausible_author(authors: str) -> bool:
    """Whether an author component holds together as a name rather than as prose.

    Three ways to fail, all of them observed shapes rather than hypotheticals: nothing
    at all (a bare "(2020)", which names no one and so can be matched to no one), a
    calendar month, and a cross-reference noun.
    """
    if not authors or _AUTHOR_RUN_RE.match(authors) is None:
        return False
    return _MONTH_RE.match(authors) is None and _CROSSREF_AUTHOR_RE.match(authors) is None


# --------------------------------------------------------------------------------------
# Numbered family
# --------------------------------------------------------------------------------------


def _detect_numbered(text: str, *, paren_numerals: bool) -> list[DetectedCitation]:
    found: list[DetectedCitation] = []

    for match in _BRACKET_SPAN_RE.finditer(text):
        found.extend(_numeric_citations(text, match, match.group(1)))

    if paren_numerals:
        for match in _PAREN_SPAN_RE.finditer(text):
            found.extend(_numeric_citations(text, match, match.group(1)))

    return found


def _numeric_citations(text: str, match: re.Match[str], content: str) -> list[DetectedCitation]:
    # A numbered marker carries its locator inside the brackets — "[3, p. 14]",
    # "[15, Sec. 3]" — where the author-date family puts it inside the parentheses. Only
    # what precedes the locator is the reference group; the locator itself is dropped for
    # the same reason it is there, since a page number is not a reference index. Without
    # this the whole marker fails the digits-and-separators test and is not detected at
    # all, which is how a manuscript loses every citation it gave a page number to.
    group_text = content[: locator.start()] if (locator := _LOCATOR_RE.search(content)) else content
    if _NUMERIC_GROUP_RE.match(group_text) is None:
        return []

    start = match.start()
    cue_from = _cue_start(text, start)
    if _CROSSREF_BEFORE_RE.search(text, cue_from, start) or _INTERVAL_BEFORE_RE.search(
        text, cue_from, start
    ):
        return []
    # "t(28)", "F(1, 28)", "χ2(2)": a test statistic's degrees of freedom, glued to the
    # statistic's name with no space. A citation marker never touches the preceding word.
    if start > 0 and text[start - 1] in _WORD_CHARS:
        return []
    if _opens_a_note(text, start, match.end()):
        return []
    if match.group(0).startswith("("):
        if _ENUMERATION_BEFORE_RE.search(text, cue_from, start):
            return []
        # A numeral alone at the end of a line is usually a display equation's number —
        # the one place "(1)" appears in a numbered manuscript that is not a citation and
        # has no cue word in front of it. But extraction wraps lines, so a real marker
        # ends its line too; what differs is the line it ends.
        line_end = text.find("\n", match.end())
        rest_of_line = text[match.end() : line_end if line_end != -1 else len(text)]
        if not rest_of_line.strip() and not _reads_as_prose(
            text[text.rfind("\n", 0, start) + 1 : start]
        ):
            return []

    numbers = _expand_numbers(group_text)
    if not numbers:
        return []

    return [
        DetectedCitation(
            family=MarkerFamily.NUMBERED,
            marker_text=match.group(0),
            start=match.start(),
            end=match.end(),
            number=number,
        )
        for number in numbers
    ]


def _reads_as_prose(line_prefix: str) -> bool:
    """Whether what precedes a marker on its own line is a sentence rather than a formula."""
    prefix = line_prefix.rstrip()
    if len(prefix.split()) < _MIN_PROSE_WORDS or _MATH_BEFORE_RE.search(prefix):
        return False
    return _PROSE_BEFORE_RE.search(prefix) is not None


def _opens_a_note(text: str, position: int, end: int) -> bool:
    """Whether a numeric marker is the first thing in its paragraph.

    An endnotes or notes section sits *after* the bibliography, so it survives into the
    body text the artifact keeps (dropping everything after the reference list would
    lose appendix citations, which is the worse trade). Every note in it opens with the
    marker shape this detector is looking for, and counting those as citations would
    invent a second occurrence of every genuinely cited reference.

    Line-initial is not enough on its own: a real citation can land at the start of a
    wrapped line ("...as shown in\\n[12], the effect..."), and refusing those would cost
    real markers in exactly the numbered styles this branch exists for. What separates
    the two is the line *above*. A notes list follows a finished note, so that line ends
    a sentence — or the block has not started yet and the line is blank. A wrapped line
    breaks mid-sentence and ends in the middle of one.

    Checking the line above rather than the paragraph above is what makes this hold for
    the whole list instead of only its first entry: notes are consecutive lines, so a
    paragraph-initial test suppresses "[1]" and then emits every note after it as a
    citation, which is the failure mode this exists to prevent.
    """
    line_start = text.rfind("\n", 0, position) + 1
    if text[line_start:position].strip():
        return False
    # One character past the marker, and no further: BRACKET_NUMBER_RE ends in a
    # lookahead for whitespace-or-end, so the window has to carry the character after the
    # closing bracket — and must not stop *on* it, or a marker glued to the next word
    # would read as ending the line. Slicing to the end of the document instead would copy
    # it once per line-initial marker, which is the cost this module just stopped paying.
    if BRACKET_NUMBER_RE.match(text[line_start : end + 1]) is None:
        return False
    if line_start == 0:
        return True
    previous = text[text.rfind("\n", 0, line_start - 1) + 1 : line_start - 1].strip()
    return not previous or previous.endswith(_SENTENCE_END)


def _expand_numbers(content: str) -> list[int]:
    """The reference numbers a group names: "[1, 4-6]" is 1, 4, 5, 6.

    Duplicates are dropped (a group naming the same reference twice is a typo, not two
    citations) and order is preserved, because the order a group lists its references in
    is the order a reviewer reads them in.
    """
    expanded: list[int] = []
    for part in re.split(r"[,;]", content):
        part = part.strip()
        if not part:
            continue
        span = _NUMERIC_RANGE_RE.fullmatch(part)
        if span is not None:
            low, high = int(span.group(1)), int(span.group(2))
            if not 0 < high - low <= _MAX_RANGE_LENGTH:
                return []
            expanded.extend(range(low, high + 1))
        elif part.isdigit():
            expanded.append(int(part))
        else:
            return []

    if any(number == 0 for number in expanded):
        return []
    return list(dict.fromkeys(expanded))
