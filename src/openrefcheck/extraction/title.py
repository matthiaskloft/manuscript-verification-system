"""Tier 0 title extraction: pull an isolated title out of a raw citation string.

Same "no external parser" philosophy as tier0.py — a handful of regex heuristics
covering the citation styles this project actually renders (see synth/latex_builder.py
STYLE_PREAMBLES: APA7, Chicago author-date, Vancouver, IEEE), not a general-purpose
citation parser. Feeds real_pipeline.py's verify_reference() call, which is documented
as title-only matching; giving it the isolated title instead of the full raw_text
measurably improves match confidence (see real_pipeline.py's former "Known gaps" note).
"""

from __future__ import annotations

import re

from openrefcheck.extraction.signals import YEAR_PAREN_RE

# IEEE/ACM style quotes the title directly: A. Author, "Title," in Journal, ...
# Curly quotes appear when PDF text extraction preserves typographer's quotes from the
# typeset PDF rather than straight ASCII ones. The "(?<=,\s)" lookbehind requires the
# opening quote to immediately follow a comma — without it, an APA/Chicago title that
# merely quotes a term inside itself (e.g. `The "Hawthorne effect" revisited.`) would
# false-match here and never reach the more appropriate year-parenthetical heuristic
# below. That lookbehind is necessary but not sufficient: a quoted term *after* a comma
# inside a title clears it, which is why extract_title also requires that no
# year-parenthetical precede the quote.
_QUOTED_TITLE_RE = re.compile(r'(?<=,\s)["“]([^"“”]{5,300})["”]')

# APA / Chicago author-date: "...(1970a).  Title. Journal, ..." — the year-parenthetical
# is the one unambiguous anchor across both styles. signals.YEAR_PAREN_RE carries the
# plausible-year range and the non-digit lookbehind that keep a volume(issue) pair like
# "2(4682)" out; the closing paren and trailing space are this module's own, since it
# needs to know where the year *ends* to take the title after it.
_YEAR_PAREN_RE = re.compile(YEAR_PAREN_RE.pattern + r"\)\.?\s*")
# Elsevier-style "Author, A., 2020. Title." — the year has to follow an author initial
# or a capitalised name word (for a corporate author: "World Health Organization,
# 2020."), which is what makes the construct an author-year block rather than a year
# that merely ends a title ("Global burden of 369 diseases, 2019. Lancet 396,
# 1204-1222."), where a lowercase word precedes it and everything after is journal
# metadata rather than a title.
_YEAR_COMMA_RE = re.compile(r"(?:[A-ZÀ-Ý]\.|[A-ZÀ-Ý][\w'-]+),\s*(?:1[5-9]\d{2}|20\d{2})[a-z]?\.\s+")

# A period+space followed by an initial ("M. J.", "S.") isn't a sentence boundary; a
# real one is followed by an actual word (capital letter, then a lowercase letter).
# The negative lookbehind for a directly-preceding "letter." (no space) additionally
# rules out a multi-letter abbreviation like "U.S." or "U.S.A." immediately before a
# capitalised word ("U.S. Department of Health, 2020. Public health report.") — its
# final period isn't a sentence boundary either, even though the word after it
# ("Department") passes the forward check alone. A genuine author-initial break
# ("Hapfelmeier, A. Publication...") isn't caught by this: "A." there is preceded by
# ", " (comma-space), not another bare "letter." pair.
_REAL_SENTENCE_BREAK_RE = re.compile(r"(?<!\.[A-ZÀ-Ý])\.\s+(?=[A-ZÀ-Ý][a-zà-ÿ])")

# Vancouver author list: "Doll R, Hill AB." — comma-separated "Surname INITIALS" groups
# ending the sentence, optionally truncated with "et al." for long author lists. Used
# to recognize the first "sentence" of a Vancouver-style entry as authors (to skip),
# not to extract anything itself.
_VANCOUVER_NAME = r"(?:[a-zà-ÿ]+\s+){0,3}[A-ZÀ-Ý][\w'-]*\s+[A-Z]{1,4}"
_VANCOUVER_AUTHORS_RE = re.compile(rf"^{_VANCOUVER_NAME}(,\s*{_VANCOUVER_NAME})*(,?\s*et al\.?)?\.$")


def _split_sentences(text: str) -> list[str]:
    """Split on '. ' (period + space), the closest thing to a sentence boundary a
    bare-text citation has. Deliberately naive — doesn't try to avoid splitting on
    abbreviations like "et al." — since callers only use the first couple of parts.
    """
    return [part.strip() for part in re.split(r"\.\s+", text) if part.strip()]


def extract_title(raw_text: str) -> str | None:
    """Best-effort isolation of a reference's title from its raw citation text.

    Tries, in order of reliability:
    1. A quoted title (IEEE/ACM style) — most unambiguous signal available.
    2. Text immediately after a "(YYYY)." year-parenthetical (APA / Chicago
       author-date) — take the next sentence, since the title is always the segment
       right after the year in these styles.
    3. Vancouver-style: no quotes, no year-parenthetical, but the first sentence looks
       like an "Author AB, Author CD." list — the title is the sentence after it.
    4. Comma-year style: "Author, A., 2020. Title. Journal, ..." — common in Elsevier
       reference lists.

    Returns None if none of these patterns match, so callers can fall back to the raw
    text rather than silently extracting garbage.
    """
    year_match = _YEAR_PAREN_RE.search(raw_text)

    # A quoted title follows the author list directly; nothing stands between them in
    # IEEE/ACM. So a year-parenthetical *before* the quote means the quote is inside
    # the title rather than around it, and rule 2 owns this reference. Without this,
    # an APA title that quotes a term after a comma ("Rethinking replication,
    # "researcher degrees of freedom" and beyond") matched rule 1 — which runs first —
    # and the lookup query became the quoted fragment instead of the title.
    quoted = _QUOTED_TITLE_RE.search(raw_text)
    if quoted and not (year_match and year_match.end() <= quoted.start()):
        return quoted.group(1).strip().rstrip(",")

    if year_match:
        remainder = raw_text[year_match.end() :].strip()
        sentences = _split_sentences(remainder)
        if sentences:
            return sentences[0].strip()

    sentences = _split_sentences(raw_text)
    if len(sentences) >= 2 and _VANCOUVER_AUTHORS_RE.match(sentences[0] + "."):
        return sentences[1].strip()

    comma_year = _YEAR_COMMA_RE.search(raw_text)
    # The author-year block this rule targets is the very start of the citation, so a
    # genuine match can't have a real sentence break ahead of it. Without this guard, a
    # capitalised article-id or publisher token deeper in the citation ("...CIN.S30747,
    # 2015." or "...Wiley and Sons, 2018.") coincidentally matches the same "Word, YYYY."
    # shape and the "title" becomes whatever trails it — the DOI or an ISBN line — even
    # though the real title already came and went earlier as its own sentence.
    # _REAL_SENTENCE_BREAK_RE (not the naive ". " split _split_sentences uses) requires
    # the word after the period to start with an actual word ([A-Z][a-z]...), so it
    # doesn't mistake an author initial like "M. J." or "S." for a sentence end.
    if (
        comma_year
        and comma_year.start() < 300
        and not _REAL_SENTENCE_BREAK_RE.search(raw_text[: comma_year.start()])
    ):
        remainder = raw_text[comma_year.end() :].strip()
        sentences = _split_sentences(remainder)
        if sentences:
            return sentences[0].strip()

    return None
