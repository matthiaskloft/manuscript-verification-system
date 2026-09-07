"""Document-level style evidence profile for a bibliography block.

Infrastructure for a future redesign that will arbitrate between the existing
splitting heuristics (tier0.py's SplitGate cascade) using per-style evidence
counts, rather than trying each gate blind and hoping the first one to find
>=2 entries happens to be the right one for the document's actual style. That
redesign is not implemented yet — this module only computes the evidence.

Deliberately not a classifier: no "detected style" label, no confidence score,
no ranking. Just raw counts/densities over one block of text, aggregated once
per document, so a future gate can consult them as evidence rather than
re-deriving its own regex pass over the same text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from openrefcheck.extraction.signals import (
    BARE_YEAR_RE,
    BRACKET_NUMBER_RE,
    DOT_NUMBER_RE,
    JSS_AUTHOR_START_RE,
    YEAR_PAREN_RE,
)

# Elsevier-style "Author, A., 2020." construct. Mirrors title.py's _YEAR_COMMA_RE
# (an author initial or capitalised name word, followed by a comma-year) rather than
# importing that private name — this module counts occurrences across a whole block,
# title.py's version searches for the first one to anchor a title on, and keeping two
# independent read sites for a "private" name felt worse than a short, clearly-linked
# duplicate of an already-proven pattern.
_YEAR_COMMA_RE = re.compile(r"(?:[A-ZÀ-Ý]\.|[A-ZÀ-Ý][\w'-]+),\s*(?:1[5-9]\d{2}|20\d{2})[a-z]?\.\s+")

# IEEE/ACM-style quoted title: A. Author, "Title," in Journal, ... Mirrors title.py's
# _QUOTED_TITLE_RE.
_QUOTED_TITLE_RE = re.compile(r'(?<=,\s)["“]([^"“”]{5,300})["”]')

# German edition marker: "(1. Aufl.)", "(2. Aufl.)", etc.
_GERMAN_EDITION_RE = re.compile(r"\(\d+\.\s*Aufl\.\)")

# German retrieval-date phrasing: "Abgerufen am 3. März 2021 von ...".
_GERMAN_RETRIEVAL_RE = re.compile(r"\bAbgerufen\s+am\b.*?\bvon\b", re.IGNORECASE)


@dataclass(frozen=True)
class StyleProfile:
    """Evidence counts/densities for one bibliography block, aggregated once.

    Each field is a raw signal, not a verdict — several fields can and do fire on
    the same block (a numbered IEEE list has both bracket_numbered_lines and
    quoted_titles). Arbitrating between them is a future gate's job, not this
    module's.
    """

    paren_year_matches: int
    comma_year_matches: int
    """Occurrences, not lines — renamed from `*_lines` on 2026-08-14, which they never were.

    The sibling `*_lines` fields do count lines, and the mismatch is a real one: one APA
    entry carrying both "(2020)" and "(Original work published 1970)" contributes two,
    which is `_MIN_STYLE_EVIDENCE` on its own from what is arguably one entry.

    Counting lines instead was measured and is worse. Five of `fixtures/citation_styles`'
    APA cases are *flattened* — extraction collapsed three entries onto one line — and
    there line-counting drops the evidence from 3 to 1 and takes those blocks from
    author-date to no answer at all, on exactly the documents where extraction has already
    gone wrong once.

    Neither unit is the one wanted, which is entries, and entries are not available here:
    finding their boundaries is what tier0's splitter does *downstream* of this profile.
    So the count is occurrences, the name now says occurrences, and the threshold's "one is
    an accident" reasoning should be read with that in mind.
    """

    bare_year_density: float
    bracket_numbered_lines: int
    dot_numbered_lines: int
    quoted_titles: int
    jss_author_lines: int
    german_markers: int


def _count_bare_years(text: str) -> int:
    """Years that are not already sitting in a parenthesised or comma-year date slot.

    BARE_YEAR_RE alone is a generic year counter — it matches the "2020" inside
    "(2020)" and "A., 2020." just as readily as a genuinely bare "1954;228:1451-5",
    so using it directly would make APA/Elsevier blocks look just as bare-year-dense
    as Vancouver/IEEE and defeat the point of a signal meant to distinguish them.
    A bare-year match is excluded when its span falls entirely inside a paren-year or
    comma-year match's span, rather than trying to fold both exclusions into one
    regex.
    """
    excluded_spans = [m.span() for m in YEAR_PAREN_RE.finditer(text)] + [
        m.span() for m in _YEAR_COMMA_RE.finditer(text)
    ]
    return sum(
        1
        for m in BARE_YEAR_RE.finditer(text)
        if not any(start <= m.start() and m.end() <= end for start, end in excluded_spans)
    )


def compute_style_profile(text: str) -> StyleProfile:
    """Compute a StyleProfile over `text`, the same block split_bibliography_block sees.

    Pure aggregation: a handful of regex counts over one string, no classification.
    """
    lines = [line for line in text.splitlines() if line.strip()]

    return StyleProfile(
        paren_year_matches=len(YEAR_PAREN_RE.findall(text)),
        comma_year_matches=len(_YEAR_COMMA_RE.findall(text)),
        bare_year_density=(_count_bare_years(text) / len(lines) if lines else 0.0),
        bracket_numbered_lines=sum(1 for line in lines if BRACKET_NUMBER_RE.match(line)),
        dot_numbered_lines=sum(1 for line in lines if DOT_NUMBER_RE.match(line)),
        quoted_titles=len(_QUOTED_TITLE_RE.findall(text)),
        jss_author_lines=sum(1 for line in lines if JSS_AUTHOR_START_RE.match(line)),
        german_markers=len(_GERMAN_EDITION_RE.findall(text)) + len(_GERMAN_RETRIEVAL_RE.findall(text)),
    )
