"""Real extraction + verification pipeline: PDF/DOCX -> ReferenceResult list.

Bridges refcheck.extraction.document (bibliography isolation + splitting) and
refcheck.verification.openalex_crossref (live Crossref/OpenAlex lookups) into the
data shape the GUI screens already know how to render, now that both backends exist.
See check_runner.py for where this is invoked.

Known gaps vs. the mock pipeline:
- Title comes from GROBID's structured parse (extraction/grobid.py) when GROBID is
  reachable and the file is a PDF; extraction/title.py's regex heuristic (covering
  this project's four target citation styles: APA, Chicago author-date, Vancouver,
  IEEE) is the Tier 0 fallback otherwise — an entry in an unrecognized style with no
  GROBID title falls back further to the full raw_text.
- Citation counts, retraction status, and topic classification aren't available from
  verify_reference() yet, so those fields are always their zero-ish default here
  (0 / False / "").
- year is only populated for matched/verified references (from the winning
  candidate's publication year) — a "review" or "halluc" entry has no winning
  candidate to take a year from, so it stays None there and is excluded from the
  Summary screen's publication-age histogram (age_bin_counts skips falsy years).
- Duplicate detection is a same-DOI check within this document's own reference list
  only, not a check against the wider literature.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

from refcheck.extraction.citation_matching import CitationMatch, MatchStatus, match_citations
from refcheck.extraction.document import NoBibliographySectionError, extract_document
from refcheck.extraction.document_artifact import DocumentArtifact
from refcheck.extraction.reference_list_audit import NOT_AUDITED, ReferenceListAudit
from refcheck.extraction.engine_status import ENGINE_AUTO
from refcheck.extraction.title import extract_title
from refcheck.gui.file_info import LoadedFile
from refcheck.gui.models import Candidate, ReferenceResult
from refcheck.verification.openalex_crossref import VerificationResult, verify_reference

# Below this, a non-match reads as "this reference probably doesn't exist" rather than
# "found something, just not confident enough" — mirrors the rough split the mock
# pipeline used (halluc confidence 0.02-0.2, review confidence 0.35-0.7).
HALLUCINATION_CEILING = 0.3

# What happened to citation matching on this run. States rather than an empty list,
# because the plan's Success Criteria require "no citations found for this reference" and
# "the citation search did not run or failed" to be visibly different: the first is a
# finding about the manuscript and the second is a fact about the tool, and a reader who
# cannot tell them apart is being invited to act on the wrong one.
#
# NONE_DETECTED is the fourth, added in Phase 5 because the three above could not express
# the state the UI most needed to recognise. A search that ran cleanly and found no marker
# anywhere reported `ok` with an empty match list, which is true and useless: every
# reference then satisfies `unused_reference_numbers`, so the screen would flag a whole
# bibliography as uncited on the strength of having detected nothing. It is not `failed`
# — nothing broke — and not `not_run` — the search did run. The difference that matters
# downstream is that a per-reference "uncited" flag is only a claim about a reference when
# *something* was detected to compare it against.
#
# NONE_MATCHED is the same argument one step further along, and the step NONE_DETECTED was
# written without. Detecting a marker is not the same as placing one: a run whose every
# match is UNRESOLVED made no claim about any reference, because UNRESOLVED *is* the
# status for declining to make one. Reported as `ok`, that run flags the whole
# bibliography uncited on the strength of the tool having given up — the identical false
# finding, differing only in how far the pipeline got before producing nothing usable. It
# is reachable in the ordinary way: a numbered manuscript whose reference list extraction
# came out short leaves every marker unresolved against a positional index.
#
# ORPHANED is deliberately not counted as declining. A marker is orphaned only after the
# index was consulted and found to carry no such entry, so an all-orphaned run has
# examined the list and is entitled to say nothing in it was cited. Which leaves the
# residual this state cannot express: a *mixed* run still supports per-reference claims,
# and every unresolved marker in it weakens them, because the reference an unresolved
# marker would have named is exactly the one now reading as uncited.
CITATIONS_OK = "ok"
CITATIONS_NONE_DETECTED = "none_detected"
CITATIONS_NONE_MATCHED = "none_matched"
CITATIONS_NOT_RUN = "not_run"
CITATIONS_FAILED = "failed"


class BibliographyNotFoundError(Exception):
    """Raised when no bibliography/references section could be located in the document."""


@dataclass(frozen=True)
class CheckResult:
    """Everything one check produces, for the caller that has to render it.

    `run_real_pipeline` returned a bare `list[ReferenceResult]` until Phase 4, and nothing
    in that channel could carry a citation match, the document artifact, or whether
    citation matching ran at all. The list is now one field of four rather than the whole
    return value.

    `artifact` is the in-memory body text the matches' anchors index into, and is the only
    place a raw context passage can be read from — matches carry none themselves. It is
    session-scoped like everything else here: the plan puts durable storage of manuscript
    text behind a DSGVO sign-off this work does not have and does not assume.

    `audit` is whether `references` is the list the document printed. Every other field
    here is a claim about a reference list, so it is the field that says how much any of
    them can be trusted — a check whose extraction merged two entries reports one fewer
    reference than the manuscript has and counts two works' citations against one row,
    with nothing else on screen to suggest it.
    """

    references: list[ReferenceResult] = field(default_factory=list)
    citation_matches: tuple[CitationMatch, ...] = ()
    artifact: DocumentArtifact | None = None
    citation_run_status: str = CITATIONS_NOT_RUN
    audit: ReferenceListAudit = NOT_AUDITED


def _status_for(result: VerificationResult) -> str:
    if result.error:
        return "unchecked"
    if result.matched:
        return "verified"
    return "halluc" if result.confidence < HALLUCINATION_CEILING else "review"


def _candidates_for(status: str, result: VerificationResult) -> tuple[Candidate, ...]:
    # Mirrors mock_pipeline.py: only "review" gets a candidate list to pick from — a
    # "verified" match doesn't need alternatives, and "halluc"/"unchecked" don't have
    # a confident-enough field to offer one from either.
    if status != "review":
        return ()
    return tuple(
        Candidate(
            title=c.title,
            doi=c.doi,
            similarity=c.similarity,
            year=c.year,
            source=c.source,
            outlet=c.outlet,
            citations_crossref=c.citations_crossref,
            citations_openalex=c.citations_openalex,
            retracted=c.retracted,
            retraction_doi=c.retraction_doi or "",
            abstract=c.abstract or "",
            topics=c.topics,
            keywords=c.keywords,
        )
        for c in result.candidates
    )


def _doi_label(result: VerificationResult) -> str:
    if result.error:
        return "not checked (lookup failed)"
    if result.matched:
        return result.candidate_doi or "—"
    return "no match"


def run_real_pipeline(
    loaded_file: LoadedFile,
    *,
    engine: str = ENGINE_AUTO,
    on_progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> CheckResult:
    """Extract references from loaded_file.path and verify each one against Crossref/OpenAlex.

    engine (see extraction.engine_status.ENGINE_*) overrides the default auto-detect
    of GROBID vs. the Anchor heuristic splitter — see extract_references().

    on_progress(done, total) fires after each reference is verified, so a caller
    running this off the GUI thread can drive a progress bar. is_cancelled() is
    polled between references so a long check can be aborted without waiting for
    every remaining live lookup.

    Citation matching runs in the same pass (the plan's Activation decision: no separate
    trigger, no per-run opt-in) and cannot affect the reference results. It is computed
    before verification because it needs none of it — a marker resolves against the
    extracted bibliography, not against what Crossref says about it — and because failing
    early leaves the rest of the check exactly as it was.
    """
    try:
        extracted = extract_document(loaded_file.path, engine=engine)
    except NoBibliographySectionError as exc:
        raise BibliographyNotFoundError(str(exc)) from exc

    entries = extracted.references

    # A parser call is currently one blocking operation. If cancellation arrived
    # while it was in flight, stop here before performing any external metadata
    # lookups once extraction returns.
    if is_cancelled is not None and is_cancelled():
        return CheckResult(citation_run_status=CITATIONS_NOT_RUN)

    citation_matches, citation_run_status = _match_citations(extracted)

    total = len(entries)
    results: list[ReferenceResult] = []
    seen_dois: dict[str, int] = {}  # normalized DOI -> ref number of its first occurrence

    def bundle(references: list[ReferenceResult]) -> CheckResult:
        return CheckResult(
            references=references,
            citation_matches=citation_matches,
            artifact=extracted.artifact,
            citation_run_status=citation_run_status,
            audit=extracted.audit,
        )

    for i, entry in enumerate(entries, start=1):
        if is_cancelled is not None and is_cancelled():
            return bundle(results)

        title = entry.title or extract_title(entry.raw_text) or entry.raw_text
        verification = verify_reference(title, raw_text=entry.raw_text)
        status = _status_for(verification)
        dup_of: int | None = None
        if status == "verified" and verification.candidate_doi:
            normalized_doi = verification.candidate_doi.lower()
            if normalized_doi in seen_dois:
                status = "dup"
                dup_of = seen_dois[normalized_doi]
            else:
                seen_dois[normalized_doi] = entry.index

        results.append(
            ReferenceResult(
                n=entry.index,
                raw=entry.raw_text,
                title=verification.candidate_title or "—",
                doi=_doi_label(verification),
                status=status,
                confidence=verification.confidence,
                year=verification.candidate_year,
                source=verification.source or "",
                outlet=verification.candidate_outlet or "",
                citations=verification.candidate_citations,
                citations_crossref=verification.candidate_citations_crossref,
                citations_openalex=verification.candidate_citations_openalex,
                retracted=verification.candidate_retracted,
                retraction_doi=verification.candidate_retraction_doi or "",
                abstract=verification.candidate_abstract or "",
                topics=verification.candidate_topics,
                keywords=verification.candidate_keywords,
                queried="" if verification.error else dt.datetime.now().strftime("%H:%M"),
                candidates=_candidates_for(status, verification),
                dup_of=dup_of,
            )
        )
        if on_progress is not None:
            on_progress(i, total)

    return bundle(results)


def _match_citations(extracted) -> tuple[tuple[CitationMatch, ...], str]:
    """Resolve this document's in-text citations, or say why there are none.

    Wrapped because reference checking must not depend on it. The plan's first Success
    Criterion is that the reference output is byte-identical when citation matching fails
    or its inputs are unavailable, and there is no user-facing toggle to exercise that
    path — the failure path *is* the path. A bare `except Exception` is the honest shape
    for that promise: an unanticipated failure in matching would otherwise take a check
    the user is entitled to with it.

    A document with no artifact never ran the search at all, which is a different answer
    from a document whose search found nothing, and both are different from a search that
    broke. A search that ran and returned nothing gets its own answer too
    (CITATIONS_NONE_DETECTED) rather than being folded into CITATIONS_OK: the empty tuple
    is the same value in both, and only the status says whether it means "this manuscript
    cites nothing" or "we found nothing to compare its references against". A search that
    returned only markers it could not resolve gets a fifth (CITATIONS_NONE_MATCHED) on
    the same reasoning — a non-empty list that still supports no claim about any
    reference. Nothing here logs the exception's text: it can quote the manuscript, and
    raw passages must not reach a log or a crash report.

    A document with no body text is the same case as no artifact, and reaching it is not
    hypothetical: the bundled page-break demo is a bare reference list, and extraction
    correctly leaves nothing once the bibliography is removed. "No citations found" would
    be true of it and would still mislead — every reference reads as unused when there was
    no prose to cite them in.
    """
    if extracted.artifact is None or not extracted.artifact.body_text.strip():
        return (), CITATIONS_NOT_RUN
    try:
        matches = match_citations(
            extracted.artifact,
            extracted.references,
            grobid_citations=extracted.citations,
            audit=extracted.audit,
            profile=extracted.profile,
        )
    except Exception:
        return (), CITATIONS_FAILED
    if not matches:
        return matches, CITATIONS_NONE_DETECTED
    if all(match.status is MatchStatus.UNRESOLVED for match in matches):
        return matches, CITATIONS_NONE_MATCHED
    return matches, CITATIONS_OK
