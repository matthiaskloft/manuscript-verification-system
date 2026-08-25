"""What the matching engine gets right on manuscripts it had no hand in writing.

`test_citation_matching.py` states what a marker looks like and checks that the matcher
agrees, which cannot falsify a shared misunderstanding. This module runs the same engine
over the five synthetic manuscripts in fixtures/synthetic, where biblatex rendered both
the markers and the bibliography from the same maintained style packages, and the
manifest recorded which key each marker stands for before the PDF existed. Nothing here
is compared against anything this project wrote.

It is also where the plan's threshold decision is settled (Phase 4, step 4), and the
answer is that **the corpus cannot choose the threshold at all**: the same 121 citations
resolve identically at every value from 0.0 to 1.0.

The first version of this module reported that as a wide, comfortable margin — true-pair
scores of 1.000 against a wrong-pair ceiling of 0.333 — and drew the wrong conclusion
from it. That 0.333 is measured *after* `_year_agreement` has already dropped every
pairing whose year disagrees, so it describes the year gate, not the names. Measured on
names alone the corpus collides at 1.000: it contains two Ricoeur entries with identical
surnames and different years, and Barth against Barthes at 0.833. Both are at or above
the chosen threshold, and both are separated entirely by their dates.

So what this corpus establishes is that year agreement carries the discrimination here
and names contribute none of it, which is a fact about these five documents rather than
about citation matching. The threshold's value rests on an argument about what the corpus
lacks — damaged names, and pairs that must be told apart by name alone — and that
argument lives with the constant, in SURNAME_MATCH_THRESHOLD's own comment.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

from refcheck.extraction import citation_matching, document
from refcheck.extraction.citation_matching import (
    SURNAME_MATCH_THRESHOLD,
    MatchStatus,
    citation_counts,
    match_citations,
    unused_reference_numbers,
)
from refcheck.extraction.citation_matching import (
    _inherit_repeated_authors,
    _marker_surnames,
    _name_similarity,
    _year_agreement,
    _year_key,
)
from refcheck.extraction.document import (
    build_document_artifact,
    extract_references,
    find_bibliography_section,
    normalize_markdown_text,
)
from refcheck.extraction.intext_signals import MarkerFamily, detect_citations, expected_families
from refcheck.extraction.style_profile import compute_style_profile

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
MANIFEST = json.loads((SYNTHETIC / "manifest.json").read_text(encoding="utf-8"))

# The score bands measured over this corpus, and what they are worth. Pinned as numbers
# rather than described in prose so a change to name comparison has to move them.
#
# The two ceilings are different questions. The post-gate one is what the matcher
# actually weighs, once years have ruled pairings out; the name-only one is what the
# threshold would face if they had not, and it is the number that says this corpus
# cannot justify a threshold.
OBSERVED_TRUE_PAIR_FLOOR = 1.0
OBSERVED_WRONG_PAIR_CEILING_AFTER_THE_YEAR_GATE = 1 / 3
OBSERVED_WRONG_PAIR_CEILING_ON_NAMES_ALONE = 1.0


def _ids(doc):
    return doc["style"] + "-" + doc["broad_field"]


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", stripped.casefold()).strip()


def _extract_without_grobid(path: Path):
    """Tier-0 extraction, pinned so the result does not depend on a running GROBID."""
    original = document.is_grobid_available
    document.is_grobid_available = lambda: False
    try:
        return extract_references(path)
    finally:
        document.is_grobid_available = original


@pytest.fixture(scope="module")
def documents():
    """Each manuscript's artifact, extracted references, style profile, and the ground
    truth linking an extracted reference back to the manifest key it was built from."""
    loaded = {}
    for doc in MANIFEST["documents"]:
        path = SYNTHETIC / doc["pdf"]
        artifact = build_document_artifact(path)
        profile = compute_style_profile(
            find_bibliography_section(normalize_markdown_text(artifact.raw_text))
        )
        references = _extract_without_grobid(path)
        titles = {entry["key"]: entry["title"] for entry in doc["entries"]}
        key_of: dict[int, str | None] = {}
        for reference in references:
            hits = [
                key for key, title in titles.items() if _fold(title)[:40] in _fold(reference.raw_text)
            ]
            key_of[reference.index] = hits[0] if len(hits) == 1 else None
        loaded[doc["pdf"]] = (artifact, references, profile, key_of)
    return loaded


def _matches(doc, documents):
    artifact, references, profile, key_of = documents[doc["pdf"]]
    return match_citations(artifact, references, profile=profile), references, key_of


def _planned_groups(doc) -> list[set[str]]:
    """The keys each `\\cite` names, in document order — one set per rendered marker."""
    markers = dict.fromkeys(citation["marker"] for citation in doc["cited"])
    return [{c["key"] for c in doc["cited"] if c["marker"] == marker} for marker in markers]


def _found_groups(matches, key_of) -> list[set[str | None]]:
    groups: dict[tuple[int, int] | None, set[str | None]] = {}
    for match in matches:
        span = (match.anchor.start, match.anchor.end) if match.anchor else None
        groups.setdefault(span, set()).add(key_of.get(match.reference_n))
    return list(groups.values())


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_every_marker_resolves_to_the_reference_the_manifest_says_it_names(doc, documents):
    """The end-to-end claim, over both marker families and four style packages.

    Compared per marker rather than per citation, because a style may reorder the
    references inside a group — APA renders `\\parencite{milgram1963,festinger1957}` as
    "(Festinger, 1957; Milgram, 1963)". Which references a marker names is ground truth;
    the order it names them in is the style's business.
    """
    matches, _, key_of = _matches(doc, documents)

    assert _found_groups(matches, key_of) == _planned_groups(doc)


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_nothing_is_left_unresolved_ambiguous_or_orphaned(doc, documents):
    """Stated separately from the mapping above because the failure modes differ: a
    mismatch there is a wrong answer, and one here is a right answer withheld."""
    matches, _, _ = _matches(doc, documents)

    assert [match.status for match in matches] == [MatchStatus.RESOLVED] * len(doc["cited"])


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_no_real_reference_is_reported_as_uncited(doc, documents):
    """The safety property this whole feature turns on.

    Every entry in these bibliographies is cited exactly once (the builder dropped
    `\\nocite{*}` precisely so that an uncited entry would leave the list entirely), so
    every unused-reference report here is a false accusation unless the "reference" is
    something reference extraction invented. One is: the Chicago list's repeated-author
    entry breaks across a line and its tail survives as a fragment of its own. That is a
    Tier 0 extraction artifact, visible as a spurious row in the reference table long
    before this feature existed, and it is allowed through here rather than papered over.
    """
    matches, references, key_of = _matches(doc, documents)

    unused = unused_reference_numbers([r.index for r in references], matches)
    real = [number for number in unused if key_of.get(number) is not None]

    assert real == [], [
        reference.raw_text for reference in references if reference.index in real
    ]


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_each_reference_is_counted_as_cited_once(doc, documents):
    """The "cited N times in this manuscript" figure Phase 5 surfaces, against a corpus
    whose plan cites every entry exactly once."""
    matches, _, key_of = _matches(doc, documents)

    counts = citation_counts(matches)
    per_key = {key_of.get(number): count for number, count in counts.items()}

    assert set(per_key) == {entry["key"] for entry in doc["entries"]}
    assert set(per_key.values()) == {1}


def test_a_repeated_author_rule_is_still_matchable():
    """Chicago prints a rule instead of repeating an author across consecutive entries,
    and the rule is all that survives extraction: the entry reads ". 1970. Freud and
    Philosophy...". Read in isolation it matches nothing, and "(Ricoeur 1970; White 1973)"
    was reported as an orphaned citation — a manuscript accused of citing a work its own
    bibliography lists. Found by this measurement, not by the hand-written tests, because
    no fixture written alongside the matcher would have thought to omit the author.
    """
    doc = next(d for d in MANIFEST["documents"] if d["style"] == "chicago-authordate")
    references = _extract_without_grobid(SYNTHETIC / doc["pdf"])

    ruled = [entry for entry in references if entry.raw_text.lstrip().startswith(".")]
    assert ruled, "the fixture no longer contains a repeated-author entry"

    keys = _inherit_repeated_authors(references)
    for entry in ruled:
        assert keys[entry.index - 1].first_surname == keys[entry.index - 2].first_surname


@pytest.mark.parametrize("threshold", [0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0])
def test_the_threshold_does_not_decide_anything_on_this_corpus(threshold, documents, monkeypatch):
    """The benchmark the plan asked for, and its actual result.

    A threshold is only worth tuning if some pairing sits near it. None does here: run the
    whole corpus at every value from 0.0 to 1.0 — the entire range, not a plausible band —
    and the resolutions are identical. Nothing in these five documents is decided by a
    name comparison at all.

    That is the real answer, and it says the corpus cannot choose the number, which is why
    SURNAME_MATCH_THRESHOLD's comment argues for its value from what the corpus *lacks*
    rather than pointing at a curve. It also makes the flatness a checked property: a
    change that made the threshold load-bearing would fail here rather than silently start
    depending on it.
    """
    monkeypatch.setattr(citation_matching, "SURNAME_MATCH_THRESHOLD", threshold)

    for doc in MANIFEST["documents"]:
        matches, _, key_of = _matches(doc, documents)
        assert _found_groups(matches, key_of) == _planned_groups(doc), doc["pdf"]


def test_the_year_gate_is_what_separates_this_corpus_and_not_the_names(documents):
    """Which half of the score does the discriminating here — measured, because reading
    the wrong half as the answer is how the threshold got justified by a number that was
    about something else.

    Two ceilings, over every author-date marker in the corpus. The first is the best score
    against a reference the marker does not cite *after* `_year_agreement` has had its
    say, which is what the threshold actually sees, and it is comfortably low. The second
    is the best name similarity against any other reference at all, with no year involved,
    and it is 1.000 — the two Ricoeur entries. The gap between those two numbers is
    entirely the year's doing.
    """
    true_floor, wrong_ceiling, name_ceiling = 1.0, 0.0, 0.0
    compared = 0

    for doc in MANIFEST["documents"]:
        artifact, references, profile, _ = documents[doc["pdf"]]
        matches = match_citations(artifact, references, profile=profile)
        detected = detect_citations(artifact.body_text, families=expected_families(profile))
        keys = _inherit_repeated_authors(references)

        # One match per detection, in detection order — the shape that lets a grouped
        # marker's members be told apart at all. Every member of "(Doe, 2020; Roe, 2019)"
        # shares a span, so a span is not enough to say which reference a given record
        # stands for, and the manifest records a group's keys as an unordered set.
        for citation, match in zip(detected, matches, strict=True):
            if match.family is not MarkerFamily.AUTHOR_DATE:
                continue
            # The reference this marker resolved to is the true pair, taken from the match
            # rather than from the manifest — sound because the test above has already
            # checked those resolutions against the manifest.
            surnames = _marker_surnames(citation.authors)
            year = _year_key(citation.year)
            compared += 1
            for key in keys:
                agreement = _year_agreement(year, key.years, key.dated)
                names_only = _name_similarity(surnames[0], key.first_surname)
                score = 0.0 if agreement is None else names_only * agreement
                if key.index == match.reference_n:
                    true_floor = min(true_floor, score)
                else:
                    wrong_ceiling = max(wrong_ceiling, score)
                    name_ceiling = max(name_ceiling, names_only)

    assert compared > 50, "the author-date documents stopped contributing markers"
    assert true_floor == OBSERVED_TRUE_PAIR_FLOOR
    assert wrong_ceiling == pytest.approx(OBSERVED_WRONG_PAIR_CEILING_AFTER_THE_YEAR_GATE, abs=0.01)
    assert name_ceiling == pytest.approx(OBSERVED_WRONG_PAIR_CEILING_ON_NAMES_ALONE, abs=0.01)
    # The point of the two numbers together: the threshold clears the first and is under
    # the second, so it is the year and not the name that keeps the wrong pairs out.
    assert wrong_ceiling < SURNAME_MATCH_THRESHOLD <= name_ceiling
