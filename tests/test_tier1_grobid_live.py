"""Tier 1 against a GROBID that is actually running.

Every other Tier-1 test in this suite feeds the parser TEI that this project wrote, which
can only show that the code agrees with the fixtures' author. This module is the one place
the Tier-1 path meets output GROBID produced itself, over the five synthetic manuscripts
whose biblatex manifest recorded which key each marker stands for before the PDF existed.

It skips when no GROBID is reachable, which includes CI. That is a real limitation and the
reason the assertions here are about *this project's* behaviour rather than GROBID's: how
many references GROBID finds is GROBID's business and varies by version, but every context
it returns must end up located in the manuscript, and no match may name a reference the
manuscript never cites. Those hold whatever GROBID does.

Measured 2026-08-11 against grobid/grobid:0.8.1 (which reports 0.8.2-SNAPSHOT), the tag
docs/demo-deployment-decision.md pins for the Cloud Run demo:

    121 citation contexts, 121 located (100%), all 121 overlapping a marker Tier 0 found
    independently; 116 resolved, every one of them placed in the manifest, 0 naming a
    reference the manuscript does not cite and 0 attributed to the wrong author;
    5 unresolved, 0 orphaned.

The first run of this module resolved 111 and reported 5 orphans, all of them false
accusations -- a manuscript told it cited nothing when it had cited correctly. Four were
one cause: GROBID's reconstructed entry carries exactly one year, and for a reprint or a
translation it is the original work's rather than the entry's own date, so the year veto
dropped a pairing the printed entry would have matched. The fifth was an entry
reconstructed as a bare "(1961)" with its author lost. Matching now reads
`RawReferenceEntry.source_text` -- the string the document printed, which GROBID returns
alongside its parse when asked -- and all five resolve, correctly.

The 5 that remained unresolved are markers GROBID handed over truncated at a page locator
("[15, p. 87", "9]"), with no link to an entry either -- "cannot tell", which was the right
answer for them while Tier 1 was the only tier reading this path.

Re-measured 2026-08-12, after Tier 0 stopped being switched off whenever GROBID returned
anything (see docs/plans/plan-in-text-citation-parsing.md):

    126 matches over the same 121 contexts, all located; 121 resolved, 0 orphaned,
    0 unresolved-with-nothing-else-to-say.

The 5 new matches are Tier 0 supplements, and they are exactly those 5 truncated markers:
Tier 0 reads the full marker off the page, resolves each at confidence 1.0, and the
manuscript stops being told it cited nothing there. Such a marker then produced two records
-- Tier 1's "cannot tell" and Tier 0's answer -- which is why the assertions below became
about which tier answered for which reference rather than about one match per context.

Re-measured 2026-08-14, after the surplus record was dropped (whole-feature review,
finding 5):

    121 matches over the same 121 contexts, all located; 121 resolved, 0 orphaned,
    0 unresolved.

Two records for one physical marker was a wrong number, not a harmless one: 126 read is
what a reviewer was shown for 121 citations, and the surplus sat in the unresolved column,
where it reads as this project declining on a marker it had answered in the same pass. A
Tier 1 context this project cannot read is now dropped where a Tier 0 supplement covered
the same characters -- and only there, so an unreadable context nothing else reached keeps
its record. One match per context is therefore an identity again on this corpus, which is
why the assertions below could go back to counting.

Of the 116 resolved, 114 place to exactly one manifest entry and 2 place to a merged one:
GROBID folded the Chicago bibliography's repeated-author entry into its predecessor, so
one reference carries both Ricoeur 1969 and Ricoeur 1970 and both markers resolve to it.
Neither match is wrong — the entry does contain the work each marker names — but the
document's citation counts are, and its reference list is one entry short. That is
GROBID's segmentation rather than this project's matching, and nothing downstream can
currently tell it happened.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

from refcheck.extraction.citation_matching import (
    MatchStatus,
    match_citations,
    unused_reference_numbers,
)
from refcheck.extraction.document import (
    extract_document,
    find_bibliography_section,
    normalize_markdown_text,
)
from refcheck.extraction.engine_status import ENGINE_ANCHOR, ENGINE_GROBID
from refcheck.extraction.grobid import grobid_url, is_grobid_available
from refcheck.extraction.intext_signals import detect_citations, expected_families
from refcheck.extraction.style_profile import compute_style_profile

pytestmark = pytest.mark.skipif(
    not is_grobid_available(),
    reason=f"no GROBID at {grobid_url()} — see README for `docker run -p 8070:8070 grobid/grobid:0.8.1`",
)

_MARKER_LOCATOR_RE = re.compile(r"\bpp?\b\.?|\bch\b\.?|\bsec\b\.?")

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
MANIFEST = json.loads((SYNTHETIC / "manifest.json").read_text(encoding="utf-8"))


def _ids(doc):
    return doc["style"] + "-" + doc["broad_field"]


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", stripped.casefold()).strip()


@pytest.fixture(scope="module")
def documents():
    """One extraction per manuscript, shared across this module's tests — the GROBID calls
    take seconds each and nothing here mutates what they return.

    Through `extract_document` rather than by assembling the pieces here, so what this
    module measures is the path a check actually takes: the reference-list audit runs, its
    printed numbers reach the entries, and a marker resolves the way it will for a
    reviewer. The fixture used to call GROBID and build the artifact separately and match
    against the result, which left the audit — the one step that decides what a numbered
    marker means — outside everything asserted below.
    """
    loaded = {}
    for doc in MANIFEST["documents"]:
        path = SYNTHETIC / doc["pdf"]
        extracted = extract_document(path, engine=ENGINE_GROBID)
        matches = match_citations(
            extracted.artifact, extracted.references, grobid_citations=extracted.citations
        )
        keys_of = {
            reference.index: _manifest_keys(reference, doc["entries"])
            for reference in extracted.references
        }
        loaded[doc["pdf"]] = (extracted, matches, keys_of)
    return loaded


def _manifest_keys(reference, entries) -> frozenset[str]:
    """Every manifest entry the works described by this reference could be.

    A set rather than one key, because GROBID does not always return one entry per entry.
    In the Chicago document it merges a repeated-author entry into its predecessor, so a
    single reference carries both "Ricoeur, Paul. 1969. The Symbolism of Evil." and
    ". 1970. Freud and Philosophy", and two different markers legitimately resolve to it.
    Insisting on a single key there would report a wrong match where the truth is a merged
    entry — and, worse, the first version of this harness returned None for that case and
    silently excluded both matches from the check that no match names an uncited
    reference. An unverifiable match dropped from a correctness assertion is exactly the
    match that most needs to be in it.

    Matched on the printed string as well as the reconstruction, since the entries whose
    title GROBID mangled are exactly the ones worth checking and the reconstruction is
    where that damage shows. There is deliberately no looser fallback behind this: on this
    corpus every one of the 121 references places by title, and an entry that stopped
    placing should fail the assertion in test_no_match_names_an_uncited_reference rather
    than be quietly matched by something weaker.
    """
    text = _fold(f"{reference.source_text or ''} {reference.raw_text}")
    return frozenset(entry["key"] for entry in entries if _fold(entry["title"])[:40] in text)


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_every_citation_context_is_located_in_the_manuscript(doc, documents):
    """The gap this module was written to close. A `CitationContext` carries TEI offsets,
    which share no coordinate system with a DocumentArtifact, so Tier 1 has to find the
    marker in the manuscript by searching for its text — and until this ran, that search
    had only ever been given marker text this project invented."""
    extracted, matches, _ = documents[doc["pdf"]]

    # Every context is accounted for by *a* match, whichever tier ended up answering. This
    # counted Tier 1's matches alone until 2026-08-14, which stopped being the right
    # measure when a context GROBID handed over truncated began yielding Tier 0's record
    # instead of both — the count then read 29 against 30 contexts and looked like a
    # context that had gone missing, when the marker was answered better. A context may
    # still produce more than one match (a grouped marker parses into one per reference),
    # so the bound stays one-sided.
    assert len(matches) >= len(extracted.citations)

    unlocated = [m.marker_text for m in matches if m.anchor is None]
    assert not unlocated


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_located_anchors_agree_with_the_markers_tier_0_found(doc, documents):
    """Corroboration from the one source that is independent of both GROBID and the
    locator: Tier 0 reads the same manuscript with regexes that never see TEI. Where the
    two tiers both place a marker they must place it in the same span, or one of them is
    pointing a reviewer at the wrong part of the page."""
    extracted, matches, _ = documents[doc["pdf"]]
    artifact = extracted.artifact
    profile = compute_style_profile(
        find_bibliography_section(normalize_markdown_text(artifact.raw_text))
    )
    spans = [(c.start, c.end) for c in detect_citations(artifact.body_text, families=expected_families(profile))]

    stranded = [
        m.marker_text
        for m in matches
        if m.anchor is not None
        and not any(s < m.anchor.end and m.anchor.start < e for s, e in spans)
    ]
    assert not stranded


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_no_citation_is_reported_as_an_orphan(doc, documents):
    """Every marker in this corpus cites an entry the same manifest generated, so an
    orphan here is never a finding — it is this project telling a manuscript it cited
    nothing when it cited correctly.

    Unlike the counts in the module docstring, this one is worth asserting even though it
    depends on GROBID: whatever a future version does to the parse, an orphan reported on
    this corpus is a false accusation, and finding out is the point.
    """
    _, matches, _ = documents[doc["pdf"]]

    assert [m.marker_text for m in matches if m.status is MatchStatus.ORPHANED] == []


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_no_match_names_an_uncited_reference(doc, documents):
    """A resolved Tier-1 match must name an entry the manuscript actually cites.

    This is the direction that matters most: a wrong match is a reviewer sent to the wrong
    reference with nothing on screen to suggest it. Note what it does *not* assert — that
    every marker resolves. Five do not, because GROBID truncated their text at a page
    locator and linked them to nothing, and "cannot tell" is the right answer for those.
    Those counts are GROBID's behaviour and would move with its version, so they are
    recorded in the module docstring rather than asserted here.

    The check is total over resolved matches: a reference this harness cannot place in the
    manifest fails the first assertion rather than being skipped by the second. Excluding
    it would have meant the entries GROBID damaged most — the only ones whose identity is
    ever in doubt — were the entries never checked, which is the reverse of what a
    correctness assertion is for.
    """
    _, matches, keys_of = documents[doc["pdf"]]
    cited = {c["key"] for c in doc["cited"]}
    resolved = [m for m in matches if m.status is MatchStatus.RESOLVED]

    unplaceable = [m.marker_text for m in resolved if not keys_of[m.reference_n]]
    assert not unplaceable

    wrong = [m.marker_text for m in resolved if not (keys_of[m.reference_n] & cited)]
    assert not wrong


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_a_numbered_list_is_counted_off_the_page_rather_than_off_the_extraction(doc, documents):
    """How many entries the printed list has is a fact about the document, not about GROBID.

    Asserted for the numbered styles because those are the ones that state it: the page
    prints "[30]" and the manifest generated thirty entries, so an audit reading anything
    else has misread the page — and that total is what the reviewer-facing note compares
    the extraction against. This is the one number in this module that should not move with
    a GROBID version, since GROBID does not participate in producing it.
    """
    extracted, _, _ = documents[doc["pdf"]]
    if not extracted.audit.numbered:
        pytest.skip(f"{doc['style']} prints no reference numbers")

    assert extracted.audit.printed_count == len(doc["entries"])


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_the_audit_agrees_with_the_manifest_about_whether_the_list_came_out_whole(doc, documents):
    """Both directions, because the audit is capable of failing in both and only one of
    them is visible from the screen.

    A false alarm tells a reviewer their reference list is damaged when it is not — the
    same false accusation the rest of this module is written against, arriving through a
    banner rather than through a match. A miss is quieter and worse: the list *is* short,
    and every count on the screen goes on looking authoritative.

    "Whole" is read off the manifest rather than off a count, since a count agrees by
    coincidence — GROBID returning 30 entries for 30 printed ones with two merged and one
    split is not a whole list. Each reference must carry exactly one manifest entry, no two
    may carry the same, and nothing may be left over.
    """
    extracted, _, keys_of = documents[doc["pdf"]]
    claimed = [keys for keys in keys_of.values() if len(keys) == 1]
    one_to_one = (
        len(claimed) == len(keys_of)
        and len({next(iter(keys)) for keys in claimed}) == len(keys_of)
        and len(keys_of) == len(doc["entries"])
    )

    assert extracted.audit.read
    assert extracted.audit.complete == one_to_one


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_an_author_date_marker_resolves_to_the_author_it_names(doc, documents):
    """Membership in the cited set is not identity, and this is the difference.

    The assertion above would still pass if every marker resolved to the same cited
    entry — it checks that a match names *a* reference the manuscript cites, not *the*
    one the marker means. Where the marker prints a surname, that gap can be closed
    cheaply: the entry it resolved to must be by the author it names.

    Numbered styles are skipped rather than faked, because "[12]" names no author and the
    identity claim for those is GROBID's link, which `_match_grobid` uses directly.
    Marker→entry identity across both families is pinned on this same corpus by
    test_citation_matching_recall.py, on the Tier-0 path.
    """
    _, matches, keys_of = documents[doc["pdf"]]
    # Chicago prints "de Beauvoir" in the bibliography and "(Beauvoir 2011)" in text, so
    # the particle is optional on the marker side — the same allowance citation_matching
    # makes with _PARTICLES, made here independently rather than by importing its rule.
    families = {
        entry["key"]: _fold(entry["authors"][0]["family"]).split()[-1]
        for entry in doc["entries"]
        if entry["authors"] and _fold(entry["authors"][0]["family"])
    }

    misattributed = []
    for match in matches:
        # A name, not the "p." of a page locator — "[3, p. 14]" is a numbered marker with
        # a letter in it and has no author to check against.
        names_someone = re.search(r"[A-Za-zÀ-ÿ]{3,}", _MARKER_LOCATOR_RE.sub("", match.marker_text))
        if match.status is not MatchStatus.RESOLVED or not names_someone:
            continue
        marker = _fold(match.marker_text)
        if not any(
            families[key] in marker for key in keys_of[match.reference_n] if key in families
        ):
            misattributed.append(match.marker_text)
    assert not misattributed


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_no_marker_is_counted_twice_where_the_two_tiers_meet(doc, documents):
    """The safety half of dropping the `len(grobid_citations) >= 1` switch.

    Tier 0 now runs on the Tier 1 path as well, and the risk that replaces the old rule is
    double-counting: one marker read by both tiers becomes two matches, one citation
    counted twice, and a "cited N times" figure that is simply wrong.

    What is asserted is the invariant rather than a count, because the count moved and the
    invariant did not. An earlier draft of this test asserted the supplement added *nothing*
    to these five documents, which was true of the rule it was written against — one that
    excluded a Tier 0 detection whenever it overlapped a claimed span at all. That rule was
    wrong, per PR #59's review: a grouped marker's Tier 0 members share the group's span, so
    a single linked member suppressed the rest of its own group. Excluding by *reference*
    instead also lets Tier 0 recover the markers GROBID hands over truncated ("[15, p. 87"),
    which it returns linked to nothing — so a supplement on a clean document is now expected
    rather than a symptom.

    Two matches may legitimately share a span; what they may not do is name the same
    reference from it, which is precisely what would inflate a count.
    """
    _, matches, _ = documents[doc["pdf"]]
    placed = [match for match in matches if match.anchor is not None]

    doubled = [
        (one.marker_text, other.marker_text)
        for index, one in enumerate(placed)
        for other in placed[index + 1 :]
        if one.reference_n is not None
        and one.reference_n == other.reference_n
        and one.anchor.start < other.anchor.end
        and other.anchor.start < one.anchor.end
    ]
    assert not doubled


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_a_manuscript_grobid_barely_links_is_not_reported_as_barely_citing(doc, documents):
    """The defect half, which this corpus cannot exhibit on its own.

    GROBID links every marker in all five of these manuscripts, so the case the fix is for
    — a partial link set — has to be constructed by withholding what GROBID returned. One
    context is kept and the rest are dropped, which is what the old switch could not tell
    apart from a document with one citation in it.

    Before: 1 match, and 28-30 of ~30 references reported cited by nothing. That is a
    finding about the manuscript manufactured out of a gap in this project's own reading,
    which is the failure the whole feature exists to avoid. After: Tier 0 covers the
    markers Tier 1 was not given, and the false uncited count across these four documents
    goes from 116 to 1.
    """
    extracted, _, _ = documents[doc["pdf"]]
    if len(extracted.citations) < 2:
        pytest.skip("single-citation manuscript: nothing to withhold")

    numbers = [reference.index for reference in extracted.references]
    partial = match_citations(
        extracted.artifact,
        extracted.references,
        grobid_citations=extracted.citations[:1],
        profile=extracted.profile,
        audit=extracted.audit,
    )

    assert len(partial) > 1
    # Not zero: the one reference this bound leaves is a real limit of Tier 0 on the APA
    # document, not of the supplement. The claim is that withholding GROBID's links no
    # longer empties the citation reading.
    assert len(unused_reference_numbers(numbers, partial)) <= 1


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=_ids)
def test_a_marker_grobid_truncated_is_recovered_rather_than_left_unreadable(doc, documents):
    """What the per-reference exclusion bought on real output, measured 2026-08-12.

    GROBID hands over some markers cut off at a page locator — "[15, p. 87", "9]",
    "(Bultmann 1958, p. 87" — and links them to nothing. Tier 1 can only report "cannot
    tell" for those. They were this corpus's 5 unresolved markers, and they are now the
    corpus's 5 supplements: Tier 0 reads the full marker off the page and resolves every
    one at confidence 1.0, taking resolved from 116 to 121 with orphans still at 0.

    The Vancouver document supplies the case PR #59's review was about, occurring for real
    rather than constructed: "[8, 9]" with GROBID's context truncated to "9]". Both Tier 0
    members carry the group's span, so the region-based exclusion this replaced would have
    dropped reference 9 — the reviewer's scenario, in GROBID's own output.

    Asserted per-supplement rather than as a total, so a GROBID whose truncation habits
    change fails on the claim that matters (a supplement is a resolution Tier 1 did not
    have) rather than on an arithmetic coincidence.

    Recovery now means *replacement*. Until 2026-08-14 the truncated context kept its
    "cannot tell" record beside Tier 0's answer, and this test read the residue as its own
    evidence — it looked for a Tier 1 UNRESOLVED span under every supplement. That was
    asserting the duplicate the count was wrong about. What is asserted instead is the
    thing the duplicate was standing in for: the supplement answers, and nothing is left
    behind saying the marker could not be read.
    """
    _, matches, _ = documents[doc["pdf"]]
    supplements = [match for match in matches if match.tier == ENGINE_ANCHOR]

    # Every supplement resolves — an unresolved one would be noise on a marker Tier 1 has
    # already reported, which is what `_already_answered` exists to drop.
    assert all(match.status is MatchStatus.RESOLVED for match in supplements)

    # Nothing anywhere in the document still says a marker could not be read. Every one of
    # these five manuscripts is answered end to end by one tier or the other, and a
    # truncated context that left its record behind would show up here.
    assert [m.marker_text for m in matches if m.status is MatchStatus.UNRESOLVED] == []

    # And no supplement is a second opinion: Tier 1 named no such reference over that span.
    for match in supplements:
        assert not [
            other
            for other in matches
            if other.tier == ENGINE_GROBID
            and other.reference_n == match.reference_n
            and other.anchor
            and match.anchor.start < other.anchor.end
            and other.anchor.start < match.anchor.end
        ], match.marker_text
