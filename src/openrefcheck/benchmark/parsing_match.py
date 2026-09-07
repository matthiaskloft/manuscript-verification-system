"""Score extracted references against gold by title, independent of DOI.

Splits the question score.py can't answer on its own: a low DOI recall could mean the
parser failed to segment/read the reference at all, or it could mean the reference was
read correctly but the source PDF simply never printed a DOI in the text. This module
answers only the first question, using Crossref's `article-title`/`unstructured`
fields (see crossref_gold.py) as ground truth for references that may have no DOI.

Matching is title-only (author/year aren't used as matching criteria): title is the
one field precise enough for a threshold-based fuzzy match without manual review, and
requiring author/year agreement too would silently drop gold entries where Crossref's
own author/year fields are missing or malformed.

Caveat on precision: Crossref only tags article-title/unstructured for a subset of a
document's references (see n_gold_with_title vs. the document's total reference count).
parsing_recall is measured against that same subset, so it's a fair like-for-like
number. parsing_precision is not: its denominator is every extracted reference with a
title, most of which have no titled counterpart in gold to match against at all (not
because the extraction was wrong, but because Crossref never tagged that particular
gold reference's title). Treat parsing_precision as a weak signal and parsing_recall as
the metric that answers "did the parser actually read this reference correctly."
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from openrefcheck.benchmark.crossref_gold import GoldReferenceEntry
from openrefcheck.benchmark.grobid_client import ExtractedReference

TITLE_MATCH_THRESHOLD = 0.85
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Crossref falls back to `unstructured` (the whole raw citation string: authors, year,
# publisher, etc.) when a publisher didn't tag `article-title` separately (see
# crossref_gold.py). A plain SequenceMatcher ratio between a clean extracted title and
# that longer string scores falsely low even for a correct match, so similarity also
# checks whether the shorter string's tokens are (almost) fully contained in the
# longer one — the case where one side is a title and the other a full citation.


@dataclass
class ParsingMatchResult:
    n_gold_with_title: int
    n_extracted_with_title: int
    matched: int
    parsing_recall: float
    parsing_precision: float
    parsing_f1: float


def normalize_title(title: str) -> str:
    return _NON_ALNUM_RE.sub(" ", title.lower()).strip()


def _token_containment(a: str, b: str) -> float:
    a_tokens, b_tokens = set(a.split()), set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    shorter, longer = (a_tokens, b_tokens) if len(a_tokens) <= len(b_tokens) else (b_tokens, a_tokens)
    return len(shorter & longer) / len(shorter)


def title_similarity(a: str, b: str) -> float:
    """Similarity between two already-normalized titles, in [0, 1].

    Exposed (not just used internally) so ensemble.py can dedupe DOI-less references
    across tiers by title instead of dropping them outright.
    """
    return max(SequenceMatcher(None, a, b).ratio(), _token_containment(a, b))


def score_parsing(
    extracted: list[ExtractedReference], gold_entries: list[GoldReferenceEntry]
) -> ParsingMatchResult:
    gold_titled = [g for g in gold_entries if g.title]
    extracted_titled = [e for e in extracted if e.title]

    gold_norm = [normalize_title(g.title) for g in gold_titled]
    extracted_norm = [normalize_title(e.title) for e in extracted_titled]

    # Greedy bipartite matching: each gold entry claims its best remaining extracted
    # match. This avoids one over-eager extracted title double-counting against
    # multiple gold entries, which would inflate both recall and precision.
    used_extracted: set[int] = set()
    matched = 0
    for g_norm in gold_norm:
        best_idx, best_score = None, 0.0
        for idx, e_norm in enumerate(extracted_norm):
            if idx in used_extracted:
                continue
            score = title_similarity(g_norm, e_norm)
            if score > best_score:
                best_score, best_idx = score, idx
        if best_idx is not None and best_score >= TITLE_MATCH_THRESHOLD:
            used_extracted.add(best_idx)
            matched += 1

    recall = matched / len(gold_titled) if gold_titled else float("nan")
    precision = matched / len(extracted_titled) if extracted_titled else float("nan")
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall and (precision + recall) > 0
        else float("nan")
    )

    return ParsingMatchResult(
        n_gold_with_title=len(gold_titled),
        n_extracted_with_title=len(extracted_titled),
        matched=matched,
        parsing_recall=recall,
        parsing_precision=precision,
        parsing_f1=f1,
    )
