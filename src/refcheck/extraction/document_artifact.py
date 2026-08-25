"""A position-tracked view of the manuscript text outside the bibliography.

refcheck.extraction.document throws the body away: `extract_references` slices out
the bibliography, hands that to tier0, and lets `full_text` go out of scope. Two
planned modules need what it discarded — in-text citation matching
(docs/plans/plan-in-text-citation-parsing.md) and statistical-reporting consistency
(docs/plans/plan-statistical-reporting-consistency.md) — and both need the
same thing from it: not just the text, but *where in the original document* a given
span of it came from. This module is that shared layer, built here because the
citation plan is the active one; the statistics plan is expected to extend it rather
than grow a second, divergent one.

Two properties matter more than the shape of the types:

**Positions are exact, not reconstructed.** `body_text` is the normalized text, and
every `Paragraph` records a `[start, end)` slice of it that is literally
``body_text[start:end]``. A consumer that finds something at an offset can hand that
offset back and get a paragraph, never a nearest-guess.

**The mapping back to the original survives normalization.** document.py's Markdown
cleanup drops lines (page footers, running headers), merges lines (entries split
across a column or page break), and rewrites lines (Markdown markers stripped), so
normalized line *N* is not raw line *N* — usually not even close, by the end of a
long document. `SourceLine` carries each normalized line's raw-line index through
that chain, so `source_line` indexes `DocumentArtifact.raw_text`'s own lines and the
round trip is checkable rather than assumed.

That mapping is per *span*, not per paragraph, and the distinction is the whole point.
A merge pass folds two raw lines into one normalized line — routinely a section
heading and the prose beneath it — so a paragraph's own origin describes only its
first character. Carrying one origin per line made every citation in every fixture
resolve to its section heading. `SourceLine.segments` records an origin per contiguous
run instead, `from_lines` lifts those into `body_text` coordinates, and
`anchor_for` resolves the span's own line through them.

Paragraph boundaries are approximate, and knowingly so. `body_text` is the output of
document.py's normalization chain, which was tuned to recover *bibliography entries*
split across a column or page break: it joins a blank-line-separated pair whenever the
line before the blank doesn't end like a finished reference. Over body text that also
joins a section heading to the prose beneath it. Detection and matching are unaffected
— they work on offsets into intact text — but a consumer treating `Paragraph` as
document structure should not. Normalizing body text differently was the alternative,
and a second definition of "normalized text" is the divergence signals.py exists to
prevent, so the coarseness is accepted and pinned by a test instead.

Not here yet: page numbers. A reviewer-facing locator ultimately wants "page 7", and
`Paragraph.source_line` is a step short of that — getting there means extracting with
pymupdf4llm's `page_chunks=True` and threading page boundaries alongside the raw-line
indices. That is deliberately not done in the same change that introduces this layer:
the concatenation of page chunks is not guaranteed to be byte-identical to the
single-string `to_markdown()` output the whole bibliography pipeline is tuned against,
so it is its own change with its own regression check. `SourceAnchor` and `Paragraph`
are shaped to take a `page` field without their existing fields moving.

Everything here is session-scoped and in-memory. Raw passage text must not reach a
log, an error message, or a crash report (see the citation plan's Constraints), which
is why no method on these types formats a passage into an exception.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# How much text either side of a match `snippet` returns by default. Small enough to
# be a snippet rather than the paragraph it is the alternative to (the citation plan's
# context viewer offers snippet first, full paragraph on expand).
DEFAULT_SNIPPET_RADIUS = 120

# A sentence boundary: terminal punctuation, optional closing quote or bracket, then
# whitespace, then something that can open a sentence. Deliberately requires the opener,
# because "…psychology (e.g., Epskamp, 2018) and…" is full of periods that end nothing.
_SENTENCE_END_RE = re.compile(r"[.!?][\"'’”)\]]*\s+(?=[\"'“(\[]*[A-Z0-9])")

# Periods that belong to an abbreviation rather than to a sentence. The list is short and
# specific on purpose: every entry here is a string that routinely appears immediately
# before a citation in academic prose, which is exactly where a wrong split would land.
# A single capital letter is included by the pattern's last branch — an initial in
# "Borsboom, D. (2021)" ends no sentence either.
_ABBREVIATION_RE = re.compile(
    r"(?:\b(?:e\.g|i\.e|cf|vs|etc|al|Fig|Eq|No|pp|p|Ch|Sec|Dr|Prof|Mr|Mrs|Ms|St|Jr|Sr|"
    r"Vol|Ed|eds|approx|ca)\.|\b[A-Z]\.)[\"'’”)\]]*\s*$"
)


class SourceLine(str):
    """A normalized line that remembers which raw line it came from.

    A `str` subclass, not a wrapper object, so document.py's normalization passes keep
    working on it unchanged: they call `.strip()`, match regexes against it, compare it
    for equality and use it as a dict key, and all of that is still ordinary `str`
    behavior. Only the handful of places that *build a new string* (a merge, a
    Markdown-marker strip) have to say which line the result descends from, via
    `retag` — and those are exactly the places where provenance is a real decision
    rather than bookkeeping.

    The alternative, threading a parallel `origins` list through every pass, was
    rejected for the reason those passes' own docstrings keep returning to: two
    structures that must stay in step, updated by hand at each of a dozen mutation
    sites, is how a silent misalignment gets in. Here a line and its origin cannot
    drift apart, because they are the same object.

    `origin` is `None` for a string that entered the chain untagged (e.g. a caller
    passing plain text to `normalize_markdown_text`) — unknown provenance, not line 0.

    One origin per line was not enough. document.py's merge passes join two raw lines
    into one normalized line, and a single `origin` can only describe the first of
    them: every character after the join point then claims a provenance it does not
    have. That is not a corner case — the mid-entry merge routinely folds a section
    heading into the prose beneath it, so *every* span in the merged line but the
    heading itself resolved to the heading's raw line. `segments` is therefore a
    sorted `(offset_in_this_line, origin)` list, one entry per contiguous run of
    characters sharing a raw line, and `origin` is kept as the first segment's — the
    whole-line answer, unchanged for every caller that only wants that.
    """

    origin: int | None
    segments: tuple[tuple[int, int | None], ...]

    def __new__(
        cls,
        text: str,
        origin: int | None = None,
        segments: tuple[tuple[int, int | None], ...] | None = None,
    ) -> SourceLine:
        line = super().__new__(cls, text)
        line.segments = _clean_segments(segments if segments is not None else ((0, origin),))
        line.origin = line.segments[0][1]
        return line


def _clean_segments(segments: tuple[tuple[int, int | None], ...]) -> tuple[tuple[int, int | None], ...]:
    """Enforce the invariant every consumer here relies on: offsets start at 0, rise
    strictly, and no two adjacent segments repeat an origin.

    Done at construction rather than asked of each caller, because the callers are the
    merge sites — the places whose whole problem is that provenance bookkeeping done by
    hand at a dozen mutation sites drifts.
    """
    cleaned: list[tuple[int, int | None]] = []
    for offset, origin in sorted(segments, key=lambda segment: segment[0]):
        if cleaned and (offset <= cleaned[-1][0] or origin == cleaned[-1][1]):
            continue
        cleaned.append((offset, origin))
    if not cleaned or cleaned[0][0] != 0:
        cleaned = [(0, cleaned[0][1] if cleaned else None), *cleaned[1:]]
    return tuple(cleaned)


def origin_of(line: str) -> int | None:
    """The raw-line index behind `line`, or None if it was never tagged."""
    return getattr(line, "origin", None)


def segments_of(line: str) -> tuple[tuple[int, int | None], ...]:
    """`line`'s `(offset, origin)` runs — a single whole-line run for a plain `str`."""
    return getattr(line, "segments", None) or ((0, origin_of(line)),)


def origin_at(line: str, offset: int) -> int | None:
    """The raw-line index behind the character at `offset` within `line`."""
    found: int | None = None
    for segment_offset, origin in segments_of(line):
        if segment_offset > offset:
            break
        found = origin
    return found


def retag(text: str, like: str) -> SourceLine:
    """`text`, carrying whatever origin `like` had — for a newly built string.

    Collapses `like` to its *first* origin, so this is only right for a string wholly
    descended from one raw line. A string built from two of them wants `concat_tag`.
    """
    return SourceLine(text, origin_of(like))


def concat_tag(text: str, left: str, right: str, right_start: int, right_dropped: int = 0) -> SourceLine:
    """`text`, where `text[:right_start]` descends from `left` and the rest from `right`.

    The merge sites' tagging call. Both sides keep their own segment structure, so a
    line merged twice — the mid-entry pass will happily fold a third fragment onto an
    already-merged pair — accumulates origins rather than flattening to the first.

    `right_dropped` is how many characters the caller stripped off the front of `right`
    before joining. Without it every segment in a fragment that was `lstrip`ped would
    sit that many characters too far along, which for a one-segment fragment is
    invisible and for a merged one silently misattributes the join.
    """
    kept = [segment for segment in segments_of(left) if segment[0] < right_start]
    moved = [
        (right_start + max(offset - right_dropped, 0), origin) for offset, origin in segments_of(right)
    ]
    return SourceLine(text, None, tuple(kept + moved))


@dataclass(frozen=True)
class Paragraph:
    """A blank-line-delimited run of body text, and where it came from.

    `text` is exactly ``artifact.body_text[start:end]``; it is stored rather than
    sliced on demand only so a consumer holding a paragraph doesn't have to hold the
    artifact too. It is kept out of the generated repr for the reason given on
    `DocumentArtifact`.
    """

    index: int
    text: str = field(repr=False)
    start: int
    end: int
    source_line: int | None


@dataclass(frozen=True)
class SourceAnchor:
    """Where a span of `body_text` sits, in every coordinate system available.

    Deliberately not carrying the passage text itself: the citation plan hides raw
    context behind an explicit reviewer opt-in, and an anchor that quoted its own text
    would put a copy of that passage in every structure an anchor is stored in. The
    text is looked up from the artifact when — and only when — something is allowed to
    show it.

    `source_line` is the raw line the span *itself* starts on, resolved through the
    artifact's segment map — not the line its paragraph starts on. The two differ
    whenever normalization merged raw lines into one normalized line, which on real
    documents is the common case rather than the exception. `paragraph_source_line`
    keeps the paragraph-level answer for a consumer that wants the passage's opening.
    """

    start: int
    end: int
    paragraph_index: int
    source_line: int | None
    paragraph_source_line: int | None = None


@dataclass(frozen=True)
class DocumentArtifact:
    """Normalized body text plus the position information to anchor spans in it.

    `body_text` excludes the bibliography section (its heading and entries alike) but
    keeps anything after it — an appendix cites references too, and dropping it would
    turn every appendix-only citation into a false "unused reference".

    Both texts are kept out of the generated repr. This object *is* the manuscript, and
    the citation plan's requirement is that a raw passage never reach a log, an error
    message or a crash report — a repr is how it gets there without anyone deciding to
    put it there. Nothing in `src/` prints one today; what changed is that the artifact is
    now carried inside the pipeline's result bundle and the session's `AppState`, the two
    objects most likely to end up in a debug print or a captured traceback.
    """

    body_text: str = field(repr=False)
    paragraphs: tuple[Paragraph, ...]
    raw_text: str = field(repr=False)
    parser: str
    segments: tuple[tuple[int, int | None], ...] = ()

    @classmethod
    def from_lines(cls, lines: list[str], *, raw_text: str, parser: str) -> DocumentArtifact:
        """Build an artifact from already-normalized lines, joined with "\\n".

        Each paragraph takes the origin of its *first* line. A paragraph whose lines
        came from different raw lines (the normal case — a wrapped sentence) therefore
        anchors to where it starts, which is what a "jump to this passage" locator
        wants; a span wanting its own line has `segments` and `source_line_at`.

        `segments` lifts each line's `(offset, origin)` runs into `body_text`
        coordinates, so one lookup resolves any offset in the document without walking
        back through the line structure that produced it.
        """
        body_text = "\n".join(lines)
        segments: list[tuple[int, int | None]] = []
        paragraphs: list[Paragraph] = []
        cursor = 0
        run_start: int | None = None
        run_origin: int | None = None

        def close_run(end: int) -> None:
            nonlocal run_start, run_origin
            if run_start is None:
                return
            paragraphs.append(
                Paragraph(
                    index=len(paragraphs),
                    text=body_text[run_start:end],
                    start=run_start,
                    end=end,
                    source_line=run_origin,
                )
            )
            run_start = None
            run_origin = None

        for line in lines:
            end = cursor + len(line)
            for offset, origin in segments_of(line):
                if not segments or segments[-1][1] != origin:
                    segments.append((cursor + offset, origin))
            if line.strip():
                if run_start is None:
                    run_start = cursor
                    run_origin = origin_of(line)
            else:
                close_run(cursor - 1 if cursor else 0)
            cursor = end + 1  # the "\n" the join inserts
        close_run(len(body_text))

        return cls(
            body_text=body_text,
            paragraphs=tuple(paragraphs),
            raw_text=raw_text,
            parser=parser,
            segments=tuple(segments),
        )

    def source_line_at(self, offset: int) -> int | None:
        """The raw line the character at `offset` came from.

        Falls back to the containing paragraph's own origin when there is no segment
        map — an artifact built directly by a caller rather than through `from_lines`
        still answers, at the coarser granularity it actually has.
        """
        if not self.segments:
            paragraph = self.paragraph_at(offset)
            return paragraph.source_line if paragraph else None
        found: int | None = None
        for segment_offset, origin in self.segments:
            if segment_offset > offset:
                break
            found = origin
        return found

    def paragraph_at(self, offset: int) -> Paragraph | None:
        """The paragraph containing `offset`, or None if it falls on a blank line."""
        for paragraph in self.paragraphs:
            if paragraph.start <= offset < paragraph.end:
                return paragraph
        return None

    def anchor_for(self, start: int, end: int) -> SourceAnchor | None:
        """Anchor the span ``body_text[start:end]``, or None if it isn't in a paragraph.

        A span that starts on a blank line but reaches into the paragraph after it
        still anchors — the overlap, not the start offset, decides — so a consumer
        whose match happens to include leading whitespace isn't told its own text
        doesn't exist. A span with no paragraph overlap at all returns None rather than
        the nearest paragraph: an unlocatable match must stay explicitly unlocated.

        `source_line` is resolved from the first character of the span that is actually
        *in* the paragraph, not from `start`. For a span with leading whitespace those
        differ, and resolving from `start` reads the separator's origin — the raw line
        before the passage, i.e. the one piece of text the span demonstrably is not.
        """
        if start < 0 or end > len(self.body_text) or start >= end:
            return None
        for paragraph in self.paragraphs:
            if start < paragraph.end and end > paragraph.start:
                return SourceAnchor(
                    start=start,
                    end=end,
                    paragraph_index=paragraph.index,
                    source_line=self.source_line_at(max(start, paragraph.start)),
                    paragraph_source_line=paragraph.source_line,
                )
        return None

    def find_occurrences(self, needle: str) -> tuple[SourceAnchor, ...]:
        """Every non-overlapping occurrence of `needle` in the body, in order.

        Returns all of them rather than the first, because the caller is the only one
        who can decide what several means: for citation matching a repeated marker is
        several genuine citations, and for the statistics plan's adapter — which gets
        raw matched text back from its engine with no offsets — it is an ambiguity to
        surface rather than resolve. Neither is served by silently picking one.

        Exact substring matching, on the normalized text. Whitespace- or
        casing-tolerant lookup is a matching-engine concern and belongs with the
        matching engine, where its threshold can be benchmarked.
        """
        if not needle:
            return ()
        anchors: list[SourceAnchor] = []
        position = self.body_text.find(needle)
        while position != -1:
            anchor = self.anchor_for(position, position + len(needle))
            if anchor is not None:
                anchors.append(anchor)
            position = self.body_text.find(needle, position + len(needle))
        return tuple(anchors)

    def context_bounds(self, anchor: SourceAnchor) -> tuple[int, int]:
        """The stretch of `body_text` an anchor's context may be drawn from.

        Its own paragraph, in the ordinary case — but widened to cover every paragraph the
        anchor overlaps, and never narrower than the anchor itself. That is what makes the
        clipping in `snippet`, `sentence_bounds` and `paragraph_text` safe to state as an
        invariant: **the context always contains the span it is the context for.**

        Without it a span straddling a block boundary lost the half of itself that fell in
        the next paragraph. `anchor_for` resolves such a span to the first paragraph it
        overlaps, which is right — there is no single paragraph that contains it, so no
        other choice is better — but the clip then cut the anchor in two, and every consumer
        clipped to the same wrong side. A grouped parenthetical split across a block
        boundary is the reachable case: "(Doe, 2020;" ends one paragraph and "Roe, 2019)"
        begins the next, so a reviewer checking the citation to Roe was shown a passage
        ending at "(Doe, 2020;" — the one thing it needed to contain was the one thing
        missing.

        Widening is not a loosening of the rule the clip enforces. That rule is about a
        neighbouring paragraph *the anchor has nothing to do with*; a paragraph the marker
        itself runs into is not one, and quoting less than the marker is the worse
        disclosure error, because it shows a reviewer text that does not say what they were
        told it says.
        """
        paragraph = self.paragraphs[anchor.paragraph_index]
        low, high = paragraph.start, paragraph.end
        for other in self.paragraphs:
            if anchor.start < other.end and other.start < anchor.end:
                low = min(low, other.start)
                high = max(high, other.end)
        return min(low, anchor.start), max(high, anchor.end)

    def paragraph_text(self, anchor: SourceAnchor) -> str:
        """The full paragraph an anchor sits in — the context viewer's "expand".

        Every paragraph it sits in, for a span that straddles a boundary: the expand view
        is where a reviewer goes when the collapsed one looked wrong, so it is the last
        place that may show a marker with half of it cut off.
        """
        start, end = self.context_bounds(anchor)
        return self.body_text[start:end]

    def sentence_bounds(self, anchor: SourceAnchor) -> tuple[int, int]:
        """The sentence containing an anchor, as `body_text` offsets.

        The context viewer's collapsed depth. A fixed character window was tried first and
        is what this replaces: it cut mid-word at both ends ("… he network perspective has
        inspired…"), so a reviewer read a fragment and could not tell whether the sentence
        actually supported the citation — which is the only question the collapsed view
        exists to answer.

        Offsets rather than text, because the caller needs to know where the marker sits
        inside the result in order to highlight it.

        Clipped to `context_bounds`, like `snippet`: a sentence must never run into a
        neighbouring paragraph, both as context and as disclosure. A paragraph with no
        internal boundary yields the whole paragraph, which is correct — that is the
        sentence. Where the anchor straddles a boundary the bounds cover both paragraphs,
        because a sentence that excluded half its own citation is not the sentence either.
        """
        low, high = self.context_bounds(anchor)
        text = self.body_text

        # The search runs past the marker and the results are filtered, rather than the
        # search being stopped at it. `_SENTENCE_END_RE` ends in a lookahead for the next
        # sentence's opening character, and `finditer`'s `endpos` bounds the lookahead too
        # — so stopping at `anchor.start` hides the one character the boundary immediately
        # before the marker needs to match on, and that character is the marker itself
        # whenever a citation opens a sentence. "Doe (2020) argued…" is among the commonest
        # positions a narrative citation takes, and every one of them collapsed to the
        # previous sentence plus its own: more of the manuscript than the collapsed view
        # says it is showing.
        start = low
        for match in _SENTENCE_END_RE.finditer(text, low, high):
            if match.end() > anchor.start:
                break
            if not _ABBREVIATION_RE.search(text, low, match.end()):
                start = match.end()

        end = high
        for match in _SENTENCE_END_RE.finditer(text, anchor.end, high):
            if _ABBREVIATION_RE.search(text, low, match.end()):
                continue
            end = match.end()
            break
        return start, min(end, high)

    def sentence(self, anchor: SourceAnchor) -> str:
        """The sentence containing an anchor — the context viewer's collapsed depth."""
        start, end = self.sentence_bounds(anchor)
        return self.body_text[start:end].strip()

    def snippet(self, anchor: SourceAnchor, radius: int = DEFAULT_SNIPPET_RADIUS) -> str:
        """`radius` characters of context either side of an anchor, clipped to its
        paragraph.

        Clipped rather than free-running so a snippet can never quote text from a
        neighbouring paragraph the anchor has nothing to do with, which would be both
        misleading as context and a wider disclosure than the paragraph the reviewer
        asked to see. Clipped to `context_bounds` rather than to one paragraph, so the
        result always contains the span it is a snippet of — see there.
        """
        low, high = self.context_bounds(anchor)
        start = max(low, anchor.start - radius)
        end = min(high, anchor.end + radius)
        return self.body_text[start:end]

    def raw_line_text(self, source_line: int | None) -> str | None:
        """The original, pre-normalization line behind a `source_line` index.

        The other half of the original-to-normalized mapping: given an anchor, get back
        the text as the document actually had it, Markdown markers and all.
        """
        if source_line is None:
            return None
        lines = self.raw_text.splitlines()
        if 0 <= source_line < len(lines):
            return lines[source_line]
        return None
