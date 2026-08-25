from pathlib import Path

import pytest

from refcheck.extraction.document import ExtractedDocument, NoBibliographySectionError
from refcheck.extraction.document_artifact import DocumentArtifact
from refcheck.extraction.tier0 import RawReferenceEntry
from refcheck.gui import real_pipeline as pipe
from refcheck.gui.file_info import LoadedFile
from refcheck.verification.openalex_crossref import VerificationCandidate, VerificationResult

_LOADED = LoadedFile(path=Path("manuscript.pdf"), name="manuscript.pdf", size_label="1 KB", pages_label="1", origin="Local file")


def _entries(*raws: str) -> list[RawReferenceEntry]:
    return [RawReferenceEntry(i, raw) for i, raw in enumerate(raws, start=1)]


def _extracted(*raws: str, body: str = "Body text with no citation markers in it.") -> ExtractedDocument:
    """What extract_document returns for a Tier 0 read of a document with a body.

    These tests are about verification and the shape of the result, so the body is
    deliberately marker-free: what citation matching does with a real one is measured in
    tests/test_citation_matching_recall.py, against manuscripts rather than against
    strings written here.
    """
    lines = body.splitlines()
    return ExtractedDocument(
        references=_entries(*raws),
        artifact=DocumentArtifact.from_lines(lines, raw_text=body, parser="test"),
    )


def _results(*args, **kwargs):
    """run_real_pipeline's reference list, for the assertions that predate the bundle."""
    return pipe.run_real_pipeline(*args, **kwargs).references


def test_verified_reference_gets_verified_status(monkeypatch):
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted("Doe, J. (2020). A title."))
    monkeypatch.setattr(
        pipe,
        "verify_reference",
        lambda title, raw_text="": VerificationResult(
            matched=True,
            confidence=0.95,
            candidate_doi="10.1/x",
            source="Crossref",
            candidate_outlet="Journal of Tests",
        ),
    )

    results = _results(_LOADED)

    assert len(results) == 1
    assert results[0].status == "verified"
    assert results[0].doi == "10.1/x"
    assert results[0].source == "Crossref"
    assert results[0].outlet == "Journal of Tests"


def test_unmatched_low_confidence_is_hallucination(monkeypatch):
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted("Made up, X. (2099). Fake."))
    monkeypatch.setattr(pipe, "verify_reference", lambda title, raw_text="": VerificationResult(matched=False, confidence=0.1))

    results = _results(_LOADED)

    assert results[0].status == "halluc"
    assert results[0].doi == "no match"


def test_unmatched_mid_confidence_needs_review(monkeypatch):
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted("Somewhat close, Y. (2020). Title."))
    monkeypatch.setattr(pipe, "verify_reference", lambda title, raw_text="": VerificationResult(matched=False, confidence=0.5))

    results = _results(_LOADED)

    assert results[0].status == "review"


def test_lookup_error_is_unchecked_not_hallucination(monkeypatch):
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted("Anything, Z. (2020). Title."))
    monkeypatch.setattr(
        pipe, "verify_reference", lambda title, raw_text="": VerificationResult(matched=False, confidence=0.0, error="outage")
    )

    results = _results(_LOADED)

    assert results[0].status == "unchecked"
    assert results[0].doi == "not checked (lookup failed)"
    assert results[0].queried == ""


def test_duplicate_dois_flagged_as_dup(monkeypatch):
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted("First, A. (2020). Title.", "Second, B. (2020). Same Title."))

    def fake_verify(title, raw_text=""):
        return VerificationResult(matched=True, confidence=0.95, candidate_doi="10.1/SAME", source="Crossref")

    monkeypatch.setattr(pipe, "verify_reference", fake_verify)

    results = _results(_LOADED)

    assert results[0].status == "verified"
    assert results[1].status == "dup"


def test_duplicate_doi_check_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted("First, A. (2020). Title.", "Second, B. (2020). Title."))
    calls = iter(["10.1/Same", "10.1/SAME"])
    monkeypatch.setattr(
        pipe, "verify_reference", lambda title, raw_text="": VerificationResult(matched=True, confidence=0.95, candidate_doi=next(calls))
    )

    results = _results(_LOADED)

    assert results[1].status == "dup"


def test_review_status_carries_candidates_for_manual_review(monkeypatch):
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted("Somewhat close, Y. (2020). Title."))
    monkeypatch.setattr(
        pipe,
        "verify_reference",
        lambda title, raw_text="": VerificationResult(
            matched=False,
            confidence=0.5,
            candidates=(VerificationCandidate(title="A close title", doi="10.1/close", similarity=0.6),),
        ),
    )

    results = _results(_LOADED)

    assert results[0].status == "review"
    assert len(results[0].candidates) == 1
    assert results[0].candidates[0].doi == "10.1/close"


def test_verified_status_does_not_carry_candidates(monkeypatch):
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted("Doe, J. (2020). A title."))
    monkeypatch.setattr(
        pipe,
        "verify_reference",
        lambda title, raw_text="": VerificationResult(
            matched=True,
            confidence=0.95,
            candidate_doi="10.1/x",
            source="Crossref",
            candidates=(VerificationCandidate(title="Runner up", doi="10.1/runner-up", similarity=0.87),),
        ),
    )

    results = _results(_LOADED)

    assert results[0].status == "verified"
    assert results[0].candidates == ()


def test_no_bibliography_section_raises_domain_error(monkeypatch):
    def raise_not_found(path, **_):
        raise NoBibliographySectionError("no heading found")

    monkeypatch.setattr(pipe, "extract_document", raise_not_found)

    with pytest.raises(pipe.BibliographyNotFoundError):
        pipe.run_real_pipeline(_LOADED)


def test_progress_callback_fires_once_per_reference(monkeypatch):
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted("A. (2020). One.", "B. (2020). Two."))
    monkeypatch.setattr(pipe, "verify_reference", lambda title, raw_text="": VerificationResult(matched=False, confidence=0.0))

    calls = []
    _results(_LOADED, on_progress=lambda done, total: calls.append((done, total)))

    assert calls == [(1, 2), (2, 2)]


def test_cancellation_stops_before_remaining_references_are_verified(monkeypatch):
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted("A. (2020). One.", "B. (2020). Two.", "C. (2020). Three."))
    verify_calls = []

    def fake_verify(title, raw_text=""):
        verify_calls.append(title)
        return VerificationResult(matched=False, confidence=0.0)

    monkeypatch.setattr(pipe, "verify_reference", fake_verify)

    results = _results(_LOADED, is_cancelled=lambda: len(verify_calls) >= 1)

    # Cancellation is polled at the top of the loop, so exactly one reference (the one
    # already in flight when cancellation was requested) gets verified before returning.
    assert len(results) == 1
    assert len(verify_calls) == 1


# --------------------------------------------------------------------------------------
# The result bundle (docs/plans/plan-in-text-citation-parsing.md, Phase 4 steps 5-6)
# --------------------------------------------------------------------------------------


def _cited(monkeypatch, body: str, *raws: str) -> None:
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted(*raws, body=body))
    monkeypatch.setattr(
        pipe, "verify_reference", lambda title, raw_text="": VerificationResult(matched=False, confidence=0.0)
    )


def test_the_bundle_carries_the_citations_alongside_the_references(monkeypatch):
    _cited(monkeypatch, "The effect replicates (Doe, 2020).", "Doe, J. (2020). A title.")

    result = pipe.run_real_pipeline(_LOADED)

    assert [r.n for r in result.references] == [1]
    assert [(m.status.value, m.reference_n) for m in result.citation_matches] == [("resolved", 1)]
    assert result.citation_run_status == pipe.CITATIONS_OK


def test_the_artifact_comes_back_so_a_passage_can_be_looked_up_later(monkeypatch):
    """The matches carry no passage text, so the artifact is the only thing that can
    answer "show me the sentence" — and the uploaded file is deleted the moment this
    result reaches the UI."""
    _cited(monkeypatch, "The effect replicates (Doe, 2020).", "Doe, J. (2020). A title.")

    result = pipe.run_real_pipeline(_LOADED)
    anchor = result.citation_matches[0].anchor

    assert result.artifact is not None
    assert result.artifact.paragraph_text(anchor) == "The effect replicates (Doe, 2020)."


def test_a_document_that_cites_nothing_is_not_a_failure(monkeypatch):
    """"Found no citations" and "the search did not run" are different states, and this
    is the first: the search ran and the manuscript has no markers.

    It is not CITATIONS_OK either, which is the distinction Phase 5 had to add. The empty
    tuple is the same value here as in the two failure states, so the status is the only
    thing that can stop a screen reading "detected nothing" as "every reference in this
    bibliography is uncited"."""
    _cited(monkeypatch, "A body paragraph with no markers at all.", "Doe, J. (2020). A title.")

    result = pipe.run_real_pipeline(_LOADED)

    assert result.citation_matches == ()
    assert result.citation_run_status == pipe.CITATIONS_NONE_DETECTED
    assert result.citation_run_status not in (pipe.CITATIONS_NOT_RUN, pipe.CITATIONS_FAILED)


def test_a_run_that_resolved_nothing_is_not_a_run_that_found_nothing(monkeypatch):
    """Detecting a marker is not placing one, and only placing one licenses a per-reference
    claim.

    Three markers are read here and none can be resolved: the reference list carries two
    entries and prints no numbers of its own, so the index is positional and "[11]" names
    a position it does not have. Every match is UNRESOLVED — the status whose entire
    meaning is that this project declined to answer.

    Reported as CITATIONS_OK that run flags the whole bibliography uncited, which is the
    same false finding CITATIONS_NONE_DETECTED exists to prevent, differing only in how
    far the pipeline got before it had nothing to say. The manuscript is not accused of
    failing to cite its own references on the strength of an index this project could not
    read.
    """
    _cited(
        monkeypatch,
        "As shown [11], and again [12], and once more [13].",
        "Doe, J. (2020). A title.",
        "Roe, R. (2021). Another title.",
    )

    result = pipe.run_real_pipeline(_LOADED)

    assert [m.status.value for m in result.citation_matches] == ["unresolved"] * 3
    assert result.citation_run_status == pipe.CITATIONS_NONE_MATCHED


def test_a_marker_that_names_no_entry_still_carries_the_run(monkeypatch):
    """The boundary of the state above: ORPHANED is a decision, not a refusal.

    A marker is orphaned only after the index was consulted and found to hold no such
    entry, so a run that produced one has read the reference list and is entitled to say
    what it does and does not contain. Degrading it to NONE_MATCHED would withhold the
    one status that is a genuine finding about the manuscript.
    """
    _cited(monkeypatch, "The effect replicates (Nobody, 1999).", "Doe, J. (2020). A title.")

    result = pipe.run_real_pipeline(_LOADED)

    assert [m.status.value for m in result.citation_matches] == ["orphaned"]
    assert result.citation_run_status == pipe.CITATIONS_OK


def test_reference_checking_is_unchanged_when_citation_matching_fails(monkeypatch):
    """The plan's first Success Criterion. There is no disable toggle to exercise it with
    (detection is unconditional by decision), so the regression test is the failure path
    itself: whatever citation matching does, the reference results are the same objects
    they would have been without it.
    """
    def raise_anything(*_args, **_kwargs):
        raise RuntimeError("citation matching fell over")

    _cited(monkeypatch, "The effect replicates (Doe, 2020).", "Doe, J. (2020). A title.")
    working = pipe.run_real_pipeline(_LOADED)

    monkeypatch.setattr(pipe, "match_citations", raise_anything)
    broken = pipe.run_real_pipeline(_LOADED)

    assert broken.references == working.references
    assert broken.citation_matches == ()
    assert broken.citation_run_status == pipe.CITATIONS_FAILED
    assert working.citation_run_status == pipe.CITATIONS_OK


def test_a_cancelled_check_reports_that_the_search_did_not_run(monkeypatch):
    """Not "no citations found": nothing was searched, and a reviewer told otherwise
    would read an empty list as a clean bill of health."""
    _cited(monkeypatch, "The effect replicates (Doe, 2020).", "Doe, J. (2020). A title.")

    result = pipe.run_real_pipeline(_LOADED, is_cancelled=lambda: True)

    assert result.references == []
    assert result.citation_run_status == pipe.CITATIONS_NOT_RUN


def test_citation_matching_runs_before_the_lookups_it_does_not_depend_on(monkeypatch):
    """A marker resolves against the extracted bibliography, not against what Crossref
    says about it — so matching finishing first means a failure in it cannot waste a
    check's worth of live lookups, and a cancelled check still keeps what it computed."""
    order = []
    monkeypatch.setattr(pipe, "extract_document", lambda path, **_: _extracted("Doe, J. (2020). A title.", body="Cited (Doe, 2020)."))
    original = pipe.match_citations
    monkeypatch.setattr(
        pipe, "match_citations", lambda *a, **k: (order.append("match"), original(*a, **k))[1]
    )

    def fake_verify(title, raw_text=""):
        order.append("verify")
        return VerificationResult(matched=False, confidence=0.0)

    monkeypatch.setattr(pipe, "verify_reference", fake_verify)

    pipe.run_real_pipeline(_LOADED)

    assert order == ["match", "verify"]


def test_a_document_with_no_body_text_reports_that_the_search_did_not_run(monkeypatch):
    """Reachable through a bundled demo, not just in principle: demo_page_break.pdf is a
    bare reference list, so removing the bibliography leaves nothing. Calling that "no
    citations found" would be literally true and would still tell a reviewer every one of
    its references is uncited."""
    _cited(monkeypatch, "", "Doe, J. (2020). A title.")

    result = pipe.run_real_pipeline(_LOADED)

    assert result.citation_run_status == pipe.CITATIONS_NOT_RUN
    assert [r.n for r in result.references] == [1]
