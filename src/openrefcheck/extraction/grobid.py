"""Tier 1 reference extraction: GROBID (see docs/project-plan.md, Tier 1).

Wraps openrefcheck.benchmark.grobid_client (the same call_grobid/TEI parsing used by the
extraction benchmark) for production use, converting its structured ExtractedReference
results into the RawReferenceEntry shape the rest of the app (document.py,
real_pipeline.py) already knows how to consume.

Also Tier 1 of citation detection (docs/plans/plan-in-text-citation-parsing.md, Phase 3):
the same TEI response carries the body's inline `<ref type="bibr">` markers, each already
resolved by GROBID to the reference it cites. Where Tier 0 (extraction/intext_signals.py)
has to infer from characters on the page which entry a marker means, this tier is told —
which is why it is the upgrade path, and why the fallback still has to exist for DOCX and
for every PDF GROBID cannot process.

Only handles PDFs — GROBID has no DOCX support, so document.py falls back to the
Tier 0 text-splitting path for .docx and whenever GROBID itself is unavailable/errors.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from xml.etree.ElementTree import ParseError as ET_ParseError

import requests

from openrefcheck.benchmark.grobid_client import (
    ExtractedReference,
    call_grobid,
    parse_grobid_citation_contexts,
    parse_grobid_references,
    parse_tei_root,
)
from openrefcheck.extraction.tier0 import RawReferenceEntry

DEFAULT_GROBID_URL = "http://localhost:8070"

# Health check timeout is separate from call_grobid's own (180s, a real
# full-document parse can take a while). Cloud Run needs longer than this to start
# GROBID and load its models after scaling to zero — measured at 107s on 2026-08-16,
# where this timeout expired first and `wait_for_grobid` below carried the rest.
# Raising it is not the fix: a held probe blocks, where a retry loop can report progress.
_HEALTH_CHECK_TIMEOUT = 60

# How long `wait_for_grobid` keeps trying, and how long it pauses between attempts.
#
# Measured on the deployed service 2026-08-16 (docs/demo-deployment-decision.md): a
# scale-to-zero start took **107s** end to end. Cloud Run held the first probe for the
# full 60s above and GROBID was still loading, so the retry loop is what actually got the
# answer at 107s. 180 is therefore 1.7x the observed cold start, not the 3x a one-minute
# estimate implied — do not lower it without re-measuring, and re-measure if the GROBID
# image or its memory allocation changes. It stays shorter than GROBID's own Cloud Run
# request timeout (300s) so this gives up before the platform does.
#
# The pause only matters for the attempts that fail *fast*: the 503-while-starting and
# connection-refused cases, which come back immediately and need spacing out. The held
# request is the other shape, and one attempt does not cover it on its own.
_COLD_START_DEADLINE = 180
_COLD_START_PAUSE = 3


class GrobidUnavailableError(Exception):
    """Raised when GROBID can't be reached or fails to process the document.

    Callers (document.py) catch this to fall back to the Tier 0 splitter rather than
    surfacing it to the user — GROBID is a best-effort upgrade, not a hard dependency.
    """


def grobid_url() -> str:
    """The GROBID base URL, overridable via the GROBID_URL env var.

    Defaults to a local container (see docker/grobid, docs/project-plan.md Tier 1) —
    consistent with the "local" deployment mode's privacy claim that documents don't
    leave the device: a same-machine container is not an external service.
    """
    return os.environ.get("GROBID_URL", DEFAULT_GROBID_URL)


def _identity_token_header(url: str) -> dict[str, str]:
    """Authorization header for a non-local GROBID URL (see docs/demo-deployment-decision.md).

    The demo deployment runs GROBID as a private Cloud Run service, invokable only by
    callers presenting a Google-signed identity token for its own URL as audience —
    Cloud Run's standard service-to-service auth pattern, which needs no key file:
    the calling service's own service account is available via the metadata server.

    Skipped for localhost/127.0.0.1 (the local-container/native-app case, per
    grobid_url()'s docstring) since there's nothing to authenticate to there, and
    best-effort — e.g. running outside GCP, where there's no metadata server to ask.
    Any failure here just means GROBID stays unreachable, which callers already treat
    as a fall-back-to-Anchor case rather than a hard error.
    """
    if urlsplit(url).hostname in {"localhost", "127.0.0.1"}:
        return {}
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.id_token import fetch_id_token

        token = fetch_id_token(Request(), url)
    except Exception:
        return {}
    return {"Authorization": f"Bearer {token}"}


def is_grobid_available(url: str | None = None) -> bool:
    """Best-effort check for whether a GROBID instance is reachable at url.

    One attempt, deliberately. This is the probe `extract_references` consults per
    extraction and the one the live-GROBID tests gate on at import, so a retry loop here
    would stall a check and add a minute to collecting a suite on a machine with no
    GROBID. Waiting for a service that is still starting is `wait_for_grobid`.
    """
    target = url or grobid_url()
    try:
        response = requests.get(
            f"{target}/api/isalive", timeout=_HEALTH_CHECK_TIMEOUT, headers=_identity_token_header(target)
        )
        return response.ok
    except requests.RequestException:
        return False


def has_cold_start(url: str | None = None) -> bool:
    """Whether a failed probe of this URL is worth waiting on.

    A local container is running or it is not: nothing about the answer changes by asking
    again, and a UI that said "starting…" for three minutes on a developer's machine with
    no GROBID would be lying about the commonest case. A scale-to-zero Cloud Run service
    is the opposite — "not reachable" there is very often "not reachable *yet*".

    Same localhost split, and the same reason, as `_identity_token_header`: the two
    branches of this module's behaviour are always local-container versus deployed service.
    """
    return urlsplit(url or grobid_url()).hostname not in {"localhost", "127.0.0.1"}


def wait_for_grobid(
    url: str | None = None,
    *,
    on_wait: Callable[[float], None] | None = None,
    deadline: float = _COLD_START_DEADLINE,
) -> bool:
    """`is_grobid_available`, but give a starting service time to finish starting.

    The demo deploys GROBID as its own Cloud Run service at zero minimum instances, so
    the first probe after an idle period is the one that triggers the cold start — and a
    single failed attempt was being reported as a settled "GROBID not reachable, falling
    back to the built-in parser". That is a fact about the second the page loaded dressed
    up as a fact about the deployment, and it is the shape this project keeps having to
    correct: an absence read as a fact.

    `on_wait` is called with the seconds elapsed so far before each pause, so a caller can
    show that something is still happening rather than freezing on "Checking…". It is
    called on whatever thread this runs on, which for the web UI is a worker rather than
    the event loop — so a caller updating widgets from it must marshal that itself.

    Returns as soon as GROBID answers. Local URLs get exactly one attempt (`has_cold_start`).
    """
    if is_grobid_available(url):
        return True
    if not has_cold_start(url):
        return False

    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        if elapsed + _COLD_START_PAUSE >= deadline:
            return False
        if on_wait is not None:
            on_wait(elapsed)
        time.sleep(_COLD_START_PAUSE)
        if is_grobid_available(url):
            return True


def _format_raw_text(ref: ExtractedReference) -> str:
    """Reconstruct a human-readable citation line for display in the GUI's raw-text
    column, since GROBID gives structured fields rather than the original text."""
    parts = [", ".join(ref.author_surnames)] if ref.author_surnames else []
    if ref.year:
        parts.append(f"({ref.year})")
    if ref.title:
        parts.append(ref.title)
    if ref.doi:
        parts.append(f"doi:{ref.doi}")
    return " ".join(parts).strip() or "(GROBID returned no parseable fields for this entry)"


@dataclass(frozen=True)
class CitationContext:
    """One in-text citation marker GROBID found, resolved to a bibliography entry.

    reference_index is the RawReferenceEntry.index of the entry the marker points at,
    or None when it points at nothing this document's bibliography carries. None is the
    matching engine's unresolved state and is deliberately kept rather than dropped: a
    marker GROBID saw but could not resolve is exactly the evidence an orphaned-citation
    check needs, and a guessed index would be indistinguishable from a real match.

    paragraph_text is the containing paragraph, session-scoped like every other raw
    passage this feature handles (see the citation plan's privacy requirements), and
    start/end index into it rather than into the manuscript, because TEI is GROBID's own
    rendering and shares no coordinates with a DocumentArtifact.

    It is kept out of the generated repr. The plan's requirement is that a raw passage
    never reach a log, an error message or a crash report, and a dataclass repr is how
    it would get there without anyone deciding to put it there — a failing assertion or
    a traceback that happens to hold one of these prints the passage.
    """

    reference_index: int | None
    target: str | None
    marker_text: str
    paragraph_text: str = field(repr=False)
    start: int
    end: int


@dataclass(frozen=True)
class GrobidDocument:
    """What one GROBID call yields: the bibliography, and the body's citations of it."""

    references: list[RawReferenceEntry] = field(default_factory=list)
    citations: list[CitationContext] = field(default_factory=list)


def extract_document_via_grobid(pdf_path, url: str | None = None) -> GrobidDocument:
    """Extract a PDF's references *and* its in-text citations of them in one GROBID call.

    Raises GrobidUnavailableError on any connection failure, timeout, malformed
    response, or failure to read pdf_path itself (call_grobid opens it directly), so
    callers can fall back to Tier 0. A document GROBID processes but finds no citations
    in yields an empty `citations` list, not an error — an uncited manuscript and an
    unparseable one are different states, and only the caller knows which one matters.

    The TEI id map is built explicitly rather than assumed. `ExtractedReference.index`
    is a TEI `xml:id` ("b12"), `RawReferenceEntry.index` is a 1-based position in the
    list below, and the two share a name while meaning different things. Nothing in
    GROBID's output guarantees "b12" is the thirteenth entry — ids can be
    non-sequential, and the header `<biblStruct>` that carries no id at all is dropped
    before this list is built — so a body `<ref target="#b12">` is resolved through the
    map or not at all. Each entry keeps its own id in `RawReferenceEntry.source_id`, so
    the map stays re-derivable by a caller holding only the references.

    RecursionError is caught alongside the transport and parse failures: the citation
    walk descends a paragraph's element tree, and a deeply enough nested response would
    otherwise escape as an exception type document.py's fallback does not catch, turning
    a best-effort upgrade into a failed check.
    """
    target = url or grobid_url()
    try:
        tei_xml = call_grobid(pdf_path, grobid_url=target, headers=_identity_token_header(target))
        root = parse_tei_root(tei_xml)
        parsed = parse_grobid_references(root)
        contexts = parse_grobid_citation_contexts(root)
    except (OSError, requests.RequestException, ET_ParseError, RecursionError) as exc:
        raise GrobidUnavailableError(f"GROBID request failed: {exc}") from exc

    references: list[RawReferenceEntry] = []
    index_by_xml_id: dict[str, int] = {}
    for position, ref in enumerate(parsed, start=1):
        references.append(
            RawReferenceEntry(
                index=position,
                raw_text=_format_raw_text(ref),
                title=ref.title,
                source_id=ref.index,
                source_text=ref.raw_reference,
            )
        )
        # First occurrence wins: a duplicate xml:id is malformed TEI, and the entry a
        # body ref most likely means is the one that was declared first.
        index_by_xml_id.setdefault(ref.index, position)

    citations = [
        CitationContext(
            reference_index=index_by_xml_id.get(context.target) if context.target else None,
            target=context.target,
            marker_text=context.marker_text,
            paragraph_text=context.paragraph_text,
            start=context.start,
            end=context.end,
        )
        for context in contexts
    ]
    return GrobidDocument(references=references, citations=citations)


def extract_references_via_grobid(pdf_path, url: str | None = None) -> list[RawReferenceEntry]:
    """Extract references from a PDF via GROBID.

    The bibliography-only view of extract_document_via_grobid, kept unchanged for the
    callers (document.py, the tests) that want exactly today's behaviour. Parsing the
    body's citation markers alongside costs one XML walk over a response that has
    already been fetched and parsed, so there is no separate call to skip.
    """
    return extract_document_via_grobid(pdf_path, url).references
