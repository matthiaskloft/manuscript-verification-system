"""OpenAlex/Crossref lookups with minimal field scope (title/author/DOI only).

See docs/project-plan.md, "Datenübermittlung an Drittländer" for why the field scope
here is deliberately narrow (Art. 44 ff. DSGVO transfer-minimization).
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import pyalex
import requests
from habanero import Crossref

from openrefcheck.benchmark.doi_utils import normalize_doi
from openrefcheck.benchmark.parsing_match import normalize_title, title_similarity
from openrefcheck.contact import contact_email

logger = logging.getLogger(__name__)

# Standard DOI syntax (Crossref's own recommended pattern) — same as
# openrefcheck.benchmark.regex_doi_extractor's _DOI_RE, duplicated here rather than
# imported since that module is benchmark-only tooling and this one is the actual
# app-facing verification path.
_RAW_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)

_URL_RE = re.compile(r"https?://[^\s)>\]\"']+", re.IGNORECASE)

# Software-package servers that routinely have no DOI at all (a CRAN or PyPI
# package listing isn't a Crossref/OpenAlex work), which is exactly where the
# DOI path above never fires and the title-similarity search below is weak (a
# package name isn't a paper title to fuzzy-match on). For these domains a
# reachable link is itself the identity check.
#
# Deliberately excludes github.com: unlike a package-registry listing, where
# reaching the page confirms the named package exists as advertised, a
# github.com URL only confirms *some* repo/gist/issue/wiki page is reachable
# at that path — not that it's the work being cited. Treating any live
# github.com link as a full identity match would let unrelated-but-reachable
# GitHub URLs in a reference's raw text skip human review entirely.
_PACKAGE_SERVER_DOMAINS = (
    "cran.r-project.org",
    "cran.rstudio.com",
    "pypi.org",
    "bioconductor.org",
    "npmjs.com",
    "ctan.org",
    "anaconda.org",
)

# Same threshold parsing_match.py uses for gold-standard title matching — this lookup
# is answering the same kind of question (is this the same work?) against the same
# kind of noisy title strings, so there's no reason for a different cutoff here.
MATCH_THRESHOLD = 0.85

# Cap on how many runner-up candidates VerificationResult carries for the manual-review
# screen — enough to give a reviewer real alternatives without dumping the whole
# _LOOKUP_LIMIT*2 raw result set on them.
MAX_CANDIDATES = 3

_LOOKUP_LIMIT = 3
_TIMEOUT_SECONDS = 10

# None unless the operator set REFCHECK_CONTACT_EMAIL — see openrefcheck.contact for why
# there is no compiled-in default. habanero omits the `mailto` from its User-Agent when
# this is None (habanero_utils.make_ua), which is the anonymous pool: slower, still
# working, and the right behaviour for a deployment that has not chosen an address.
_crossref = Crossref(mailto=contact_email(), timeout=_TIMEOUT_SECONDS)

# OpenAlex meters requests against a daily budget rather than a request rate. Its own
# response says so when it refuses: {"error": "Rate limit exceeded", "message":
# "Insufficient budget. This request costs $0.0001 but you only have $0 remaining. Resets
# at midnight UTC..."}, alongside X-RateLimit-Limit-USD and a Retry-After in seconds.
#
# Anonymous callers get $0.10/day — 1,000 requests. A free API key raises that to $1/day
# (openalex.org/settings/api), which is 10,000. Set OPENALEX_API_KEY to use one; without
# it a couple of dozen full checks exhaust the day's budget, and every OpenAlex-only field
# — abstract, topics, keywords — silently disappears from every card.
_OPENALEX_API_KEY_ENV = "OPENALEX_API_KEY"

# Once the budget is gone it is gone until midnight UTC, so a check with thirty references
# would otherwise make thirty more requests that cannot succeed, each waiting on a network
# round-trip. The first refusal closes the door, and records why so the UI can say it
# rather than showing empty fields.
#
# It closes the door *until the budget resets*, not for the life of the process. This runs
# in a web server that stays up for days: a flag with no expiry would disable OpenAlex on
# every future check too, while the message on screen went on promising a reset at midnight
# UTC — the code contradicting its own explanation.
_openalex_refusal: str | None = None
_openalex_refusal_until: _dt.datetime | None = None

# pyalex has no per-call timeout knob; retries default to disabled, which is what we
# want here — a bounded per-reference lookup with no retry, since verify_reference
# already treats a failed lookup as "try the other source" rather than something to
# retry on its own.
pyalex.config.max_retries = 0


@dataclass
class VerificationCandidate:
    """A runner-up match, offered to the manual-review screen as an alternative to
    the automatically-picked (or automatically-rejected) best candidate.

    doi/title are non-optional here (unlike the raw _Candidate this is built from):
    a candidate an API returned with no title or no DOI isn't something a reviewer
    could usefully act on, so verify_reference() filters those out before this type
    is ever constructed.
    """

    title: str
    doi: str
    similarity: float
    year: int | None = None
    source: str = ""  # "OpenAlex" / "Crossref" — which lookup surfaced this candidate
    outlet: str = ""
    # The same evidence the winning match carries. A reviewer picking between candidates is
    # making the identification the automated match could not, and a title and a similarity
    # score are not enough to make it: a retracted candidate in particular must not be
    # selectable without the reviewer being told, since confirming it writes a retracted
    # work into the reference list.
    citations_crossref: int | None = None
    citations_openalex: int | None = None
    retracted: bool | None = None
    retraction_doi: str | None = None
    abstract: str | None = None
    topics: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass
class VerificationResult:
    matched: bool
    confidence: float
    candidate_doi: str | None = None
    candidate_title: str | None = None
    candidate_year: int | None = None
    source: str | None = None  # "Crossref" / "OpenAlex" — whichever produced the best candidate
    candidate_outlet: str | None = None
    # How often the wider literature cites the matched work. None when the lookup that
    # produced the match did not report one — a link-check hit has no metadata at all, and
    # "not reported" must stay distinguishable from a genuine zero.
    candidate_citations: int | None = None
    # Kept per source as well: the two disagree substantially and the card shows both
    # rather than picking one for the reader. See _Candidate.citations_crossref.
    candidate_citations_crossref: int | None = None
    candidate_citations_openalex: int | None = None

    # Whether the matched work has been retracted, and the notice that retracted it.
    # None is "nobody told us", never "clean": see _Candidate.retracted.
    candidate_retracted: bool | None = None
    candidate_retraction_doi: str | None = None

    # The matched work's own abstract and subject areas, for the reference card. Public
    # metadata about a published work — unlike a citation context, which quotes the
    # manuscript under review and is gated behind an explicit opt-in.
    candidate_abstract: str | None = None
    candidate_topics: tuple[str, ...] = ()
    candidate_keywords: tuple[str, ...] = ()

    # Set only when *both* lookups failed (network/outage/rate-limit), as opposed to
    # both succeeding but finding nothing above threshold. Per docs/project-plan.md
    # ("Verhalten bei API-Ausfall oder Rate-Limiting festlegen"), callers need to be
    # able to tell "we checked and found no match" apart from "we couldn't check" —
    # the former is real signal for a hallucination/review flag, the latter isn't.
    error: str | None = None

    # Alternatives to the winning match (when matched) or the full ranked field (when
    # not), for the manual-review screen. Capped at MAX_CANDIDATES, deduped by DOI.
    candidates: tuple[VerificationCandidate, ...] = ()


@dataclass
class _Candidate:
    source: str
    doi: str | None
    title: str | None
    score: float
    year: int | None = None
    outlet: str | None = None
    # How often the wider literature cites this work: OpenAlex's `cited_by_count`,
    # Crossref's `is-referenced-by-count`. None means the lookup did not report one,
    # which is not the same as zero — a work genuinely cited by nobody. The Summary
    # screen's frequency chart and the references panel both need that distinction.
    citations: int | None = None
    # The same figure kept per source, because the two disagree substantially and the card
    # shows both: measured on 10.1371/journal.pmed.0020124, Crossref reported 8,121 and
    # OpenAlex 10,653 for the identical work. Each counts the citing works *it* indexes, so
    # neither is wrong and neither is the truth; `citations` above is the higher of the
    # two, which is the closest thing to a lower bound on the real figure.
    citations_crossref: int | None = None
    citations_openalex: int | None = None
    # Whether the work has been retracted. None means no lookup said either way, and it
    # must never be rendered as "not retracted": this is the one finding where a missed
    # alarm is the actual harm, so "we did not check" and "we checked and it is clean"
    # cannot be allowed to look the same.
    retracted: bool | None = None
    # The retraction notice's own DOI, where the source named it (Crossref does; OpenAlex
    # gives only the boolean). A retraction is an accusation about someone's work, and a
    # reviewer must be able to go read the notice rather than take this screen's word.
    retraction_doi: str | None = None
    # OpenAlex only, and free: the search already returns whole work objects, so the
    # abstract and the topics are downloaded on every lookup today and thrown away.
    # Crossref was measured and dropped as a source for both — see _openalex_abstract.
    abstract: str | None = None
    topics: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


# The keys _rank_candidates reads out of each raw item. Named rather than positional: the
# tuple this replaced was unpacked by index with `len(item) > n` guards, so every new field
# silently defaulted to None on any caller that had not been updated in step.
_ITEM_FIELDS = (
    "doi", "title", "year", "outlet", "citations", "citations_crossref",
    "citations_openalex", "retracted", "retraction_doi", "abstract", "topics", "keywords",
)

# How many OpenAlex topics to keep. Three is what the API returns per work, ordered by
# score, and they are the display-ready end of its subject hierarchy.
_MAX_TOPICS = 3

# Keywords are finer-grained and noisier than topics — the same three sample works
# returned "MEDLINE" and "Affect (linguistics)" among usable ones. Both are shown, each
# under its own heading so a reader can see which vocabulary a term came from, and this
# cap keeps the noisier list from crowding out the better one.
_MAX_KEYWORDS = 5


def _rank_candidates(
    items: list[dict],
    normalized_query: str,
    source: str,
) -> list[_Candidate]:
    """Score every item against the query and return them best-first.

    Unlike a "pick the single best" reduction, this keeps every scored item so
    verify_reference can offer runner-ups to the manual-review screen, not just the
    one candidate it decided (or declined) to auto-match on.
    """
    ranked = [
        _Candidate(
            source=source,
            score=title_similarity(normalized_query, normalize_title(item["title"])),
            # Absent keys fall through to _Candidate's own defaults rather than becoming
            # None, which matters for the ones whose default is not None (topics is an
            # empty tuple, and callers iterate it).
            **{key: item[key] for key in _ITEM_FIELDS if key in item},
        )
        for item in items
        if item.get("title")
    ]
    ranked.sort(key=lambda c: c.score, reverse=True)
    return ranked


def _best_of(items: list[dict], normalized_query: str, source: str) -> _Candidate:
    """Single-best convenience wrapper around _rank_candidates, kept for callers/tests
    that only care about the top match, not the full ranked field.
    """
    ranked = _rank_candidates(items, normalized_query, source)
    return ranked[0] if ranked else _Candidate(source, None, None, 0.0)


def _crossref_year(item: dict) -> int | None:
    for key in ("published-print", "published-online", "issued"):
        date_parts = item.get(key, {}).get("date-parts")
        if date_parts and date_parts[0] and date_parts[0][0]:
            return date_parts[0][0]
    return None


def _crossref_candidate(normalized_query: str, title: str) -> list[_Candidate]:
    response = _crossref.works(
        query=title,
        select=[
            "DOI", "title", "published-print", "published-online", "issued", "type",
            "container-title", "publisher", "is-referenced-by-count", "updated-by",
        ],
        limit=_LOOKUP_LIMIT,
    )
    items = [
        {
            "doi": item.get("DOI"),
            "title": (item.get("title") or [None])[0],
            "year": _crossref_year(item),
            "outlet": _crossref_outlet(item),
            "citations": item.get("is-referenced-by-count"),
            "citations_crossref": item.get("is-referenced-by-count"),
            "retracted": _crossref_retraction(item) is not None,
            "retraction_doi": _crossref_retraction(item),
        }
        for item in response.get("message", {}).get("items", [])
    ]
    return _rank_candidates(items, normalized_query, "Crossref")


def _utcnow() -> _dt.datetime:
    """Indirection so a test can control the clock across a budget reset."""
    return _dt.datetime.now(_dt.timezone.utc)


def _next_utc_midnight(now: _dt.datetime) -> _dt.datetime:
    """When OpenAlex says the daily budget refills — quoting its own refusal message,
    "Resets at midnight UTC"."""
    return (now + _dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def openalex_refusal() -> str | None:
    """Why OpenAlex stopped answering, or None if it is expected to answer again.

    Read by the UI. An OpenAlex-only field going blank looks exactly like a work with no
    abstract and no subject areas, and a reviewer has no way to tell those apart from the
    card — so the reason has to be stated somewhere rather than left as an absence.

    Clears itself once the budget should have reset, which is also what re-opens the source
    for the next check: the state is a "do not bother until", not a permanent verdict.
    """
    global _openalex_refusal, _openalex_refusal_until
    if _openalex_refusal_until is not None and _utcnow() >= _openalex_refusal_until:
        _openalex_refusal = None
        _openalex_refusal_until = None
    return _openalex_refusal


def _configure_openalex() -> None:
    # Read per call rather than once at import: unlike the Crossref client, which is
    # constructed once, this runs on every check, so a deployment that sets the variable
    # after start (or a test that sets it) is picked up. Left as None when unset —
    # pyalex then calls the anonymous pool. See openrefcheck.contact.
    pyalex.config.email = contact_email()
    key = os.environ.get(_OPENALEX_API_KEY_ENV)
    if key:
        pyalex.config.api_key = key


def _openalex_is_available() -> bool:
    return openalex_refusal() is None


def _retry_after(exc: Exception) -> _dt.datetime | None:
    """When the response said to come back, if it said.

    Usually it does not: pyalex retries internally and surfaces a `requests.RetryError`
    with no response attached, so the header is gone by the time this sees the failure.
    Read anyway for the paths where a response survives, since the server's own answer
    beats an assumption about when its day rolls over.
    """
    response = getattr(exc, "response", None)
    header = getattr(response, "headers", {}).get("Retry-After") if response else None
    try:
        return _utcnow() + _dt.timedelta(seconds=int(header))
    except (TypeError, ValueError):
        return None


def _note_openalex_failure(exc: Exception) -> None:
    """Stop asking until the budget resets, if this was the budget.

    Only for a refusal that will still be true on the next call, and only until it will
    not be. A timeout or a single transport error says nothing about the next reference
    and must not disable the source at all.
    """
    global _openalex_refusal, _openalex_refusal_until
    if "429" not in str(exc) and "rate limit" not in str(exc).lower():
        return
    now = _utcnow()
    _openalex_refusal_until = _retry_after(exc) or _next_utc_midnight(now)
    _openalex_refusal = (
        "OpenAlex declined further requests: its daily free budget is used up. "
        f"It resets at {_openalex_refusal_until:%Y-%m-%d %H:%M} UTC, and this check will "
        "not ask again before then — so abstracts, topics, keywords and OpenAlex citation "
        f"counts are missing from it. Set {_OPENALEX_API_KEY_ENV} to a free key from "
        "openalex.org/settings/api for ten times the allowance."
    )


def _openalex_candidate(normalized_query: str, title: str) -> list[_Candidate]:
    if not _openalex_is_available():
        raise RuntimeError("OpenAlex unavailable for the rest of this run")
    _configure_openalex()
    try:
        results = pyalex.Works().search(title).get(per_page=_LOOKUP_LIMIT)
    except Exception as exc:
        _note_openalex_failure(exc)
        raise
    items = []
    for item in results:
        doi_url = item.get("doi")
        doi = doi_url.rsplit("doi.org/", 1)[-1] if doi_url else None
        source = (item.get("primary_location") or {}).get("source") or {}
        items.append(
            {
                "doi": doi,
                "title": item.get("title"),
                "year": item.get("publication_year"),
                "outlet": source.get("display_name"),
                "citations": item.get("cited_by_count"),
                # OpenAlex reports the fact and not the notice, so retraction_doi stays
                # unset here; Crossref's `updated-by` is where the notice's own DOI comes
                # from when a Crossref candidate wins.
                "retracted": item.get("is_retracted"),
                "abstract": _openalex_abstract(item),
                "topics": _openalex_topics(item),
                "keywords": _openalex_keywords(item),
            }
        )
    return _rank_candidates(items, normalized_query, "OpenAlex")


def _openalex_abstract(item: dict) -> str | None:
    """Rebuild the abstract OpenAlex stores as an inverted index.

    OpenAlex publishes `abstract_inverted_index` — {word: [positions]} — rather than the
    abstract as prose. Reassembling it is the documented way to read it and costs one pass
    over the words. Coverage is partial and publisher-dependent (measured: present for two
    of three sample DOIs, missing on the Elsevier one), which is why the card must render
    nothing at all rather than an empty field when this returns None.

    Crossref was measured as a second source and dropped: its own `abstract` was absent for
    every DOI tried, and it arrives as JATS XML that would need stripping before display.

    A position that repeats or a gap in the sequence is possible in real data, so this
    sorts by position rather than trusting the index to be dense — a missing position
    would otherwise shift every later word by one.
    """
    inverted = item.get("abstract_inverted_index")
    if not inverted:
        return None
    placed = sorted(
        (position, word) for word, positions in inverted.items() for position in positions
    )
    text = " ".join(word for _position, word in placed).strip()
    return text or None


def _openalex_topics(item: dict) -> tuple[str, ...]:
    """The work's subject areas, best-scoring first — the labelled end of OpenAlex's own
    hierarchy ("Meta-analysis and systematic reviews", "Complex Network Analysis
    Techniques")."""
    return _display_names(item.get("topics"), _MAX_TOPICS)


def _openalex_keywords(item: dict) -> tuple[str, ...]:
    """The work's keywords, best-scoring first.

    A different and noisier vocabulary from `topics`: measured on three DOIs it returned
    "Pairwise comparison" and "Network analysis" alongside "MEDLINE", "Biology" and
    "Affect (linguistics)". Kept because the good ones are more specific than any topic —
    and shown under its own heading rather than mixed in, so a reader can see which
    vocabulary a term came from and discount accordingly.
    """
    return _display_names(item.get("keywords"), _MAX_KEYWORDS)


def _display_names(entries, limit: int) -> tuple[str, ...]:
    names = [(entry.get("display_name") or "").strip() for entry in (entries or [])[:limit]]
    return tuple(name for name in names if name)


def _crossref_retraction(item: dict) -> str | None:
    """The DOI of the notice retracting this work, or None if nothing retracts it.

    Crossref records the relationship on the *retracted* work as `updated-by`, one entry
    per update with a `type`. Verified live against 10.1016/S0140-6736(97)11096-0
    (Wakefield 1998), which carries two entries — a 2004 `correction` and the 2010
    `retraction` — so the type has to be read rather than the list's presence taken as the
    signal. A correction is not a retraction, and treating one as the other would put the
    loudest warning this application has on an ordinary erratum.
    """
    for update in item.get("updated-by") or []:
        if (update.get("type") or "").lower() == "retraction":
            return update.get("DOI")
    return None


def _crossref_outlet(item: dict) -> str | None:
    if item.get("type") == "posted-content":
        institutions = item.get("institution") or []
        if institutions and institutions[0].get("name"):
            return institutions[0]["name"]
    containers = item.get("container-title") or []
    return containers[0] if containers else item.get("publisher")


def _dedupe_by_doi(candidates: list[_Candidate]) -> list[_Candidate]:
    """Collapse repeat DOIs (Crossref and OpenAlex both surfacing the same work) into one
    candidate per DOI, keeping the first (highest-scoring, since candidates arrives
    pre-sorted) and *merging* what the others knew into it. Candidates without a DOI can't
    be deduped this way and are all kept.

    Merging rather than discarding, because the two sources answer different questions
    about the same work and the winner is decided by title similarity, which has nothing
    to do with which of them is better informed. Crossref names the retraction notice and
    OpenAlex carries the abstract and the topics; whichever scored higher would otherwise
    take the whole record, and a Crossref win would silently drop a retraction OpenAlex had
    flagged on the identical DOI. This used to `continue` past the duplicate.
    """
    kept: dict[str, _Candidate] = {}
    order: list[_Candidate] = []
    for candidate in candidates:
        if not candidate.doi:
            order.append(candidate)
            continue
        key = candidate.doi.lower()
        if key not in kept:
            kept[key] = candidate
            order.append(candidate)
            continue
        _merge_into(kept[key], candidate)
    return order


def _merge_into(winner: _Candidate, other: _Candidate) -> None:
    """Fill the winner's blanks from another source's record of the same work.

    Only blanks: the winner's own answers stand, so a merge can add knowledge and never
    overwrite it. Retraction is the exception and is a logical OR — one source reporting a
    retraction the other has not recorded is still a retraction, and this is the direction
    the whole feature has to fail in.
    """
    # `title` is in the list because of the direct-DOI path: a Crossref record that
    # resolves without a title would otherwise leave the match titleless even when OpenAlex
    # supplied one, and `_direct_doi_title_is_plausible` then demotes a correct match to
    # manual review for want of a string the other source had. On the title-search path
    # this can never fire — candidates with no title are dropped before ranking.
    for field_name in (
        "title", "year", "outlet", "citations_crossref", "citations_openalex",
        "retraction_doi", "abstract",
    ):
        if getattr(winner, field_name) is None:
            setattr(winner, field_name, getattr(other, field_name))
    if not winner.topics:
        winner.topics = other.topics
    if not winner.keywords:
        winner.keywords = other.keywords
    if other.retracted is not None:
        winner.retracted = bool(winner.retracted) or other.retracted
    # Not a blank-fill: each source counts only the citing works it indexes, so the higher
    # figure is the closest thing available to a lower bound on the real one. The two are
    # also kept apart above, because the card shows both rather than picking for the reader.
    reported = [c for c in (winner.citations, other.citations) if c is not None]
    winner.citations = max(reported) if reported else None


def extract_doi_from_text(raw_text: str) -> str | None:
    """Pull a DOI already printed in a reference's raw text, if any.

    Most reference styles print the work's own DOI (as a bare "10.xxxx/..." or a
    "https://doi.org/10.xxxx/..." URL). When that's present it's a far stronger
    signal than a fuzzy title match — see _direct_doi_lookup, which verify_reference
    tries first when this returns non-None.
    """
    match = _RAW_DOI_RE.search(raw_text)
    return normalize_doi(match.group(0).rstrip(".,;)")) if match else None


def extract_package_url_from_text(raw_text: str) -> str | None:
    """Pull a URL pointing at a known software-package server (CRAN, PyPI, ...) out
    of a reference's raw text, if any.

    Matched against the URL's host (via urlparse), not a substring search on the raw
    URL text — a substring check on "cran.r-project.org" would also match an
    attacker- or typo-controlled host like "cran.r-project.org.evil.example", since
    that string still contains the domain.
    """
    for match in _URL_RE.finditer(raw_text):
        url = match.group(0).rstrip(".,;)")
        host = urlparse(url).netloc.lower()
        if any(host == domain or host.endswith(f".{domain}") for domain in _PACKAGE_SERVER_DOMAINS):
            return url
    return None


def _direct_url_lookup(url: str) -> VerificationResult | None:
    """Check that a package-server URL printed in the reference actually resolves.

    Unlike _direct_doi_lookup (which resolves a DOI to bibliographic metadata), this
    is a plain reachability check — CRAN/PyPI/etc. package pages don't come with a
    title/year an API would hand back, so there's no candidate metadata to attach.
    A HEAD request is tried first since it's cheaper (no body transfer); some hosts
    don't support HEAD on these paths and answer 405, so a GET is retried in that
    case specifically rather than for every non-2xx status.
    """
    try:
        response = requests.head(url, allow_redirects=True, timeout=_TIMEOUT_SECONDS)
        if response.status_code == 405:
            response = requests.get(url, allow_redirects=True, timeout=_TIMEOUT_SECONDS, stream=True)
        if response.status_code < 400:
            return VerificationResult(
                matched=True,
                confidence=1.0,
                source=f"{urlparse(url).netloc.lower()} (link check)",
            )
        logger.info("Package-server link check got status %s for %r", response.status_code, url)
    except requests.RequestException as exc:
        logger.info("Package-server link check failed for %r: %s", url, exc)
    return None


def _direct_doi_lookup(doi: str) -> VerificationResult | None:
    """Resolve a DOI already found in the reference's own text directly, instead of
    fuzzy-matching on title.

    Returns None (not a VerificationResult) if the DOI doesn't resolve anywhere —
    callers should fall back to the title-search path in that case, since a DOI
    that's garbled (OCR/extraction noise) or simply wrong doesn't mean the reference
    itself doesn't exist. A DOI that *does* resolve is about as strong a signal as
    this system gets (the exact, unambiguous identifier printed in the source
    document, not a fuzzy title guess), so it's returned at confidence 1.0 without
    going through MATCH_THRESHOLD at all.

    Both sources are asked, and whichever answered first has its blanks filled from the
    other. This used to return the moment Crossref replied, which is where most references
    land — a reference list normally prints the DOI — and Crossref carries no abstract, no
    topics and no keywords, so the whole matched-work half of the reference card was empty
    for exactly the references this tool identifies most confidently. It also meant a
    retraction OpenAlex had recorded went unseen whenever Crossref answered first. Two
    requests instead of one on this path, which is what the title-search path already
    costs.
    """
    found = [
        candidate
        for candidate in (_crossref_by_doi(doi), _openalex_by_doi(doi))
        if candidate is not None
    ]
    if not found:
        return None

    best = found[0]
    for other in found[1:]:
        _merge_into(best, other)
    return VerificationResult(
        matched=True,
        confidence=1.0,
        candidate_doi=doi,
        candidate_title=best.title,
        candidate_year=best.year,
        candidate_outlet=best.outlet,
        candidate_citations=best.citations,
        candidate_citations_crossref=best.citations_crossref,
        candidate_citations_openalex=best.citations_openalex,
        candidate_retracted=best.retracted,
        candidate_retraction_doi=best.retraction_doi,
        candidate_abstract=best.abstract,
        candidate_topics=best.topics,
        candidate_keywords=best.keywords,
        source=" + ".join(c.source for c in found) + " (direct DOI)",
    )


def _crossref_by_doi(doi: str) -> _Candidate | None:
    try:
        item = _crossref.works(ids=doi)["message"]
    except Exception as exc:
        logger.info("Direct Crossref DOI lookup failed for %r: %s", doi, exc)
        return None
    return _Candidate(
        source="Crossref",
        doi=doi,
        title=(item.get("title") or [None])[0],
        score=1.0,
        year=_crossref_year(item),
        outlet=_crossref_outlet(item),
        citations=item.get("is-referenced-by-count"),
        citations_crossref=item.get("is-referenced-by-count"),
        retracted=_crossref_retraction(item) is not None,
        retraction_doi=_crossref_retraction(item),
    )


def _openalex_by_doi(doi: str) -> _Candidate | None:
    if not _openalex_is_available():
        return None
    try:
        _configure_openalex()
        item = pyalex.Works()[f"https://doi.org/{doi}"]
    except Exception as exc:
        _note_openalex_failure(exc)
        logger.info("Direct OpenAlex DOI lookup failed for %r: %s", doi, exc)
        return None
    return _Candidate(
        source="OpenAlex",
        doi=doi,
        title=item.get("title"),
        score=1.0,
        year=item.get("publication_year"),
        outlet=((item.get("primary_location") or {}).get("source") or {}).get("display_name"),
        citations=item.get("cited_by_count"),
        citations_openalex=item.get("cited_by_count"),
        retracted=item.get("is_retracted"),
        abstract=_openalex_abstract(item),
        topics=_openalex_topics(item),
        keywords=_openalex_keywords(item),
    )


def _direct_doi_title_is_plausible(title: str, candidate_title: str | None) -> bool:
    """Sanity check for a direct-DOI hit's resolved title against the extracted title.

    Deliberately checks for *any* shared whole word rather than a title_similarity()
    score: at the low end, SequenceMatcher-based similarity between two entirely
    unrelated titles still regularly lands around 0.2-0.35 just from coincidental
    character/substring overlap (shared letters, similar length) — verified against
    several unrelated title pairs while designing this check. That's nowhere near a
    reliable "these are obviously different works" signal. Sharing zero whole words
    is a much less noisy one, and a real match — even with a messy/garbled extracted
    title (extra boilerplate, OCR typos in some words) — almost always keeps at
    least one intact content word in common with the true title.
    """
    if not title or not candidate_title:
        return True  # nothing to compare against — trust the DOI resolution as-is
    query_tokens = set(normalize_title(title).split())
    candidate_tokens = set(normalize_title(candidate_title).split())
    if not query_tokens or not candidate_tokens:
        return True
    return bool(query_tokens & candidate_tokens)


def verify_reference(title: str, author: str = "", raw_text: str = "") -> VerificationResult:
    """Look up a single reference via OpenAlex/Crossref live API calls.

    If raw_text carries a DOI the source itself printed, that's resolved directly
    first (see _direct_doi_lookup) — an exact identifier lookup beats a fuzzy title
    guess, and it's cheaper too (one lookup instead of two ranked searches). Falls
    back to the title-similarity search below when raw_text has no DOI, or when the
    DOI it has doesn't resolve (garbled/wrong DOI shouldn't sink an otherwise
    findable reference).

    A direct-DOI hit is still sanity-checked against the extracted title
    (_direct_doi_title_is_plausible) before being trusted outright: a DOI that
    resolves but shares no whole word with the extracted title is more likely a
    garbled/misread DOI that coincidentally resolves to an unrelated work than a
    real match. Rather than either trusting it blindly (confidence 1.0 on a wrong
    paper, never seen by a reviewer) or discarding the resolution outright, that
    case is downgraded to "review" with the mismatched candidate attached, so a
    human sees exactly what happened instead of it being silently marked verified.

    When no DOI resolves (or none is present), raw_text is also checked for a URL on
    a known software-package server (CRAN, PyPI, Bioconductor, ...) — see
    extract_package_url_from_text/_direct_url_lookup. These entries routinely have
    no DOI at all, and a package name is a poor query for the title-similarity search
    below, so a reachable package-server link is treated as sufficient on its own
    rather than falling through to a fuzzy title match that's unlikely to help.

    Matches on title only in the fallback path, same rationale as
    parsing_match.py's title_similarity: it's the one field precise enough for a
    threshold-based fuzzy match, and requiring author agreement too would drop real
    matches whenever a source's author field is missing or formatted differently.
    `author` is accepted for a future richer match but isn't used yet.
    """
    normalized_query = normalize_title(title)

    if raw_text:
        doi = extract_doi_from_text(raw_text)
        if doi:
            direct = _direct_doi_lookup(doi)
            if direct is not None:
                if _direct_doi_title_is_plausible(title, direct.candidate_title):
                    return direct
                similarity = (
                    title_similarity(normalized_query, normalize_title(direct.candidate_title))
                    if direct.candidate_title
                    else 0.0
                )
                logger.info(
                    "Direct DOI %r resolved to a title sharing no word with the extracted "
                    "title — treating as review, not verified.",
                    doi,
                )
                return VerificationResult(
                    matched=False,
                    confidence=MATCH_THRESHOLD - 0.01,
                    candidates=(
                        VerificationCandidate(
                            title=direct.candidate_title,
                            doi=direct.candidate_doi,
                            similarity=similarity,
                            year=direct.candidate_year,
                            source=direct.source,
                            outlet=direct.candidate_outlet or "",
                        ),
                    ),
                )

        package_url = extract_package_url_from_text(raw_text)
        if package_url:
            link_result = _direct_url_lookup(package_url)
            if link_result is not None:
                return link_result

    ranked_lists: list[list[_Candidate]] = []

    for lookup in (_crossref_candidate, _openalex_candidate):
        try:
            ranked_lists.append(lookup(normalized_query, title))
        except Exception as exc:
            logger.warning("%s lookup failed for %r: %s", lookup.__name__, title, exc)

    if not ranked_lists:
        return VerificationResult(
            matched=False,
            confidence=0.0,
            error="Both Crossref and OpenAlex lookups failed (outage or rate limit).",
        )

    all_candidates = _dedupe_by_doi(
        sorted((c for ranked in ranked_lists for c in ranked), key=lambda c: c.score, reverse=True)
    )
    if not all_candidates:
        return VerificationResult(matched=False, confidence=0.0)

    best = all_candidates[0]
    # Runner-ups: exclude the winning match when it auto-matched (nothing to offer as
    # an "alternative" to itself); include it when it didn't, since with no auto-match
    # the reviewer needs the full ranked field, best candidate included.
    matched = best.score >= MATCH_THRESHOLD
    runner_ups = all_candidates[1:] if matched else all_candidates
    # Filter before capping at MAX_CANDIDATES, not after — otherwise a doi-less or
    # title-less candidate ranked in the top slots (VerificationCandidate requires
    # both) would silently displace a lower-ranked but usable one instead of just
    # being skipped over.
    candidates = tuple(
        VerificationCandidate(
            title=c.title,
            doi=c.doi,
            similarity=c.score,
            year=c.year,
            source=c.source,
            outlet=c.outlet or "",
            citations_crossref=c.citations_crossref,
            citations_openalex=c.citations_openalex,
            retracted=c.retracted,
            retraction_doi=c.retraction_doi,
            abstract=c.abstract,
            topics=c.topics,
            keywords=c.keywords,
        )
        for c in runner_ups
        if c.doi and c.title
    )[:MAX_CANDIDATES]

    if not matched:
        return VerificationResult(matched=False, confidence=best.score, candidates=candidates)

    return VerificationResult(
        matched=True,
        confidence=best.score,
        candidate_doi=best.doi,
        candidate_title=best.title,
        candidate_year=best.year,
        source=best.source,
        candidate_outlet=best.outlet,
        candidate_citations=best.citations,
        candidate_citations_crossref=best.citations_crossref,
        candidate_citations_openalex=best.citations_openalex,
        # Both already carry whatever the other source knew about this DOI: _dedupe_by_doi
        # merges same-DOI candidates rather than dropping the loser.
        candidate_retracted=best.retracted,
        candidate_retraction_doi=best.retraction_doi,
        candidate_abstract=best.abstract,
        candidate_topics=best.topics,
        candidate_keywords=best.keywords,
        candidates=candidates,
    )
