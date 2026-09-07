"""Shared vocabulary for the questions every extraction layer asks.

"Is this a publication year?" and "has this entry finished?" were answered
independently in tier0.py, document.py and title.py, and the answers disagreed. That
is not a tidiness problem — it is where the bugs came from:

- document.py's paragraph merge treated only sentence-terminal punctuation as the end
  of an entry, while its own stop-heading check treated a trailing DOI as an ending
  too. A DOI-final entry was merged into the corporate-author entry after it, and a
  reference disappeared.
- tier0.py and title.py each defined `_YEAR_PAREN_RE`, with the same name and
  different meanings: tier0's matched any parenthesised four-digit run, so it read the
  issue number in Vancouver's "1954;2(4682):1451" as a publication year.

Both were found by review rather than by tests, because a disagreement between two
modules is invisible from inside either one. Definitions live here so there is one
place to change and nowhere to diverge.
"""

from __future__ import annotations

import re

# Plausible publication years only (1500-2099). A bare \d{4} also matches issue
# numbers, page numbers and street addresses.
YEAR = r"(?:1[5-9]\d{2}|20\d{2})"

# A parenthesised publication year: "(2021)", "(2024a)", "(2021, October 19)". The
# lookbehind rejects a volume(issue) pair — "2(4682)" is not a year — and the closing
# delimiter must be a paren, comma or letter suffix, so "(4682)" alone cannot match
# through the year range either.
YEAR_PAREN_RE = re.compile(rf"(?<!\d)\({YEAR}[a-z]?\b")

# An unparenthesised year, for counting how many appear in one block of text.
BARE_YEAR_RE = re.compile(rf"(?<!\d){YEAR}(?!\d)")

# A no-date marker fills exactly the slot a parenthesised year fills: APA prints
# "(n.d.)" where the year would go, and the reference is otherwise unremarkable.
# Treating only a literal year as "this entry has reached its date" left every
# undated bibliography — web resources, standards, grey literature, whole reference
# lists in some fields — with no signal at all to split on. English and German forms,
# since the project targets a German deployment.
#
# The vocabulary and its parenthesised form are separate names because the parens are
# a property of where a bibliography writes the date, not of the vocabulary itself: an
# in-text marker writes the same words bare, inside the citation's own parens
# ("(Doe, n.d.)"). intext_signals.py needs the words without the wrapper, and having it
# re-list them would be the third independent definition of a shared concept this
# module exists to prevent.
NO_DATE = r"(?:n\.\s?d\.|no date|in press|forthcoming|o\.\s?J\.|im Druck)"
NO_DATE_RE = re.compile(rf"\({NO_DATE}\)", re.IGNORECASE)

# "This entry has reached its date", however that date is written.
DATE_SLOT_RE = re.compile(rf"{YEAR_PAREN_RE.pattern}|{NO_DATE_RE.pattern}", re.IGNORECASE)

# A trailing DOI or URL. APA puts no period after one, so this is the second way a
# reference legitimately ends.
LINK_END = r"(?:https?://|doi:|doi\.org/|10\.\d{4,9}/)\S+"
LINK_END_RE = re.compile(LINK_END + r"\s*$")

# Sentence-terminal punctuation, optionally followed by a closing quote or bracket.
SENTENCE_END_RE = re.compile(r"[.?!][\"'”)\]]*\s*$")

# A volume(issue), page-range citation locator — the shape a reference's trailing
# journal/page info takes, e.g. "34(2), 1-22" or "2(4), 201-218". This is positive
# evidence that a fragment is a journal-name-and-locator continuation of the entry
# before it, as opposed to a wholly new bulleted entry that merely happens to lack its
# own author/year marker (an undated corporate-author or title-first entry looks
# exactly like that from marker/year absence alone).
LOCATOR_CONTINUATION_RE = re.compile(r"\d+\s*\(\s*\d+\s*\)\s*,\s*\d")

# A dangling hyphen/en-dash at the end of a line: a word wrapped across a page break,
# the other positive continuation signal alongside LOCATOR_CONTINUATION_RE.
DANGLING_HYPHEN_RE = re.compile(r"[-‐‑–]\s*$")

# Numbered styles (IEEE "[1] ..." or plain "1. ..."), anchored at line start.
# The lookahead (?=\s|$) — not a bare \s+ — because PDF text extraction commonly puts
# the marker alone on its own line ("1.\nDoll R and Hill AB...") when the source PDF
# wraps right after the marker, so a mandatory trailing whitespace character can't be
# assumed. It still has to be whitespace-or-end though, not just "anything": a bare
# \s* would also match "10.1136/bmj..." (a DOI fragment) as a false "marker 10.",
# hijacking priority away from more accurate heuristics on non-numbered bibliographies.
BRACKET_NUMBER_RE = re.compile(r"^\s*\[(\d+)\](?=\s|$)")
DOT_NUMBER_RE = re.compile(r"^\s*(\d+)[.)](?=\s|$)")

# Bare-number style, no punctuation after the marker (e.g. some medical/epidemiology
# journals: "1 Hogan JW, Laird NM. Intention-to-treat..."). Capped at 3 digits so a
# line starting with a 4-digit year isn't mistaken for a marker. This is the
# riskiest of the three numbered patterns — no bracket or punctuation to anchor on
# — so it's only ever tried with require_sequential=True (see
# _entries_from_line_starts), never on its own.
BARE_NUMBER_RE = re.compile(r"^\s*(\d{1,3})(?=\s)")

# APA-style fallback anchor: a line starting a new entry typically opens with
# "Surname, I." or "Surname, I., & Surname2, ..." followed eventually by a
# parenthesised year. We only use the "Surname, Initial." opening as the anchor
# because the year can appear much later in multi-author entries. An optional
# one-or-two-word particle covers multi-word surnames — both lowercase ("van der
# Veen, D.", "de Vries, A.") and capitalized ("De Mario, T. J.", commonly a
# style/sentence-position choice rather than a different name) — without it, those
# entries never register as a start (no single capitalized word directly before the
# comma) and silently merge into whichever entry precedes them.
#
# The particle allowance also has to exclude the literal conjunction "and"/"&": a
# many-author list wrapped across a page break can leave its last author
# ("...and Koller, M. Comparing...") starting the continuation fragment, and that
# shape is otherwise indistinguishable from a genuine particle-prefixed surname like
# "van der Veen, D." — "and Koller, M." matches the same optional-particle grammar.
# Unlike a name particle, "and"/"&" never legitimately opens a bibliography entry, so
# excluding it is safe everywhere this marker is used (splitting and merge-recovery
# alike) and not just a merge-recovery special case.
APA_AUTHOR_START_RE = re.compile(r"^(?!(?:and|&)\s)(?:[A-Za-zÀ-ÿ]+\s+){0,2}[A-ZÀ-Ý][\w'-]*,\s*[A-ZÀ-Ý]\.")

# Journal-of-Statistical-Software-style anchor: "Surname II (YYYY)." or "Surname II,
# Surname2 JJ (YYYY)." — no comma and no periods between surname and initials, unlike
# the APA fallback above (which requires "Surname, I."). The initials block must be
# ALL CAPS immediately followed by a word boundary (space/comma/paren) — not just any
# capitalized word — so this doesn't fire on ordinary Title Case prose ("Biomarker
# Discovery in..." doesn't match: "Discovery" isn't all-uppercase). Excludes a leading
# "and"/"&" for the same reason as APA_AUTHOR_START_RE above.
JSS_AUTHOR_START_RE = re.compile(r"^(?!(?:and|&)\s)(?:[a-zà-ý]+\s+){0,2}[A-ZÀ-Ý][\w'-]*\s+[A-Z]{1,4}\b")


def entry_is_complete(text: str) -> bool:
    """Whether `text` ends the way a finished reference ends.

    The two endings are not alternatives to choose between per call site — they are
    both real, and every layer that asks this question has to accept both. Asking it
    through one function is what keeps a third caller from re-deriving half of it.
    """
    return bool(SENTENCE_END_RE.search(text) or LINK_END_RE.search(text))
