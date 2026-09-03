import datetime as _dt
from types import SimpleNamespace

import pytest

from openrefcheck.contact import CONTACT_EMAIL_ENV
from openrefcheck.verification import openalex_crossref as ver


def _patch(monkeypatch, crossref=None, openalex=None):
    def _crossref(normalized_query, title):
        if crossref is None:
            raise RuntimeError("Crossref unavailable")
        return crossref

    def _openalex(normalized_query, title):
        if openalex is None:
            raise RuntimeError("OpenAlex unavailable")
        return openalex

    monkeypatch.setattr(ver, "_crossref_candidate", _crossref)
    monkeypatch.setattr(ver, "_openalex_candidate", _openalex)


def _clear_openalex_refusal(monkeypatch):
    """Module state, so each test starts from a source that is expected to answer."""
    monkeypatch.setattr(ver, "_openalex_refusal", None)
    monkeypatch.setattr(ver, "_openalex_refusal_until", None)


def _no_openalex_doi(monkeypatch):
    """OpenAlex not answering for this DOI. Stubbed explicitly in every direct-DOI test:
    both sources are asked now, and an unstubbed pyalex would make a real network call."""
    monkeypatch.setattr(
        ver.pyalex,
        "Works",
        lambda: type("W", (), {"__getitem__": lambda self, k: (_ for _ in ()).throw(RuntimeError("404"))})(),
    )


def test_verify_reference_matches_above_threshold(monkeypatch):
    candidate = ver._Candidate("Crossref", "10.1/xyz", "A title about ecology", 0.95)
    _patch(monkeypatch, crossref=[candidate], openalex=[])

    result = ver.verify_reference("A title about ecology")

    assert result.matched
    assert result.confidence == 0.95
    assert result.candidate_doi == "10.1/xyz"
    assert result.source == "Crossref"
    assert result.error is None


def test_verify_reference_picks_best_of_both_sources(monkeypatch):
    weak = ver._Candidate("Crossref", "10.1/weak", "unrelated", 0.4)
    strong = ver._Candidate("OpenAlex", "10.1/strong", "the right title", 0.9)
    _patch(monkeypatch, crossref=[weak], openalex=[strong])

    result = ver.verify_reference("the right title")

    assert result.matched
    assert result.source == "OpenAlex"
    assert result.candidate_doi == "10.1/strong"


def test_verify_reference_below_threshold_is_not_matched(monkeypatch):
    weak = ver._Candidate("Crossref", "10.1/weak", "barely related", 0.5)
    _patch(monkeypatch, crossref=[weak], openalex=[])

    result = ver.verify_reference("something else entirely")

    assert not result.matched
    assert result.error is None
    assert result.confidence == 0.5


def test_verify_reference_reports_error_when_both_lookups_fail(monkeypatch):
    _patch(monkeypatch, crossref=None, openalex=None)

    result = ver.verify_reference("any title")

    assert not result.matched
    assert result.confidence == 0.0
    assert result.error is not None


def test_verify_reference_survives_one_lookup_failing(monkeypatch):
    strong = ver._Candidate("Crossref", "10.1/ok", "a working title", 0.9)
    _patch(monkeypatch, crossref=[strong], openalex=None)

    result = ver.verify_reference("a working title")

    assert result.matched
    assert result.source == "Crossref"
    assert result.error is None


def test_verify_reference_exposes_runner_up_candidates_when_matched(monkeypatch):
    best = ver._Candidate("Crossref", "10.1/best", "the right title", 0.95)
    runner_up = ver._Candidate("OpenAlex", "10.1/runner-up", "the right title, revised edition", 0.88)
    _patch(monkeypatch, crossref=[best], openalex=[runner_up])

    result = ver.verify_reference("the right title")

    assert result.matched
    assert result.candidate_doi == "10.1/best"
    assert [c.doi for c in result.candidates] == ["10.1/runner-up"]


def test_verify_reference_exposes_ranked_candidates_when_not_matched(monkeypatch):
    weak = ver._Candidate("Crossref", "10.1/weak", "barely related", 0.5)
    weaker = ver._Candidate("OpenAlex", "10.1/weaker", "even less related", 0.3)
    _patch(monkeypatch, crossref=[weak], openalex=[weaker])

    result = ver.verify_reference("something else entirely")

    assert not result.matched
    assert [c.doi for c in result.candidates] == ["10.1/weak", "10.1/weaker"]


def test_verify_reference_dedupes_candidates_by_doi(monkeypatch):
    best = ver._Candidate("Crossref", "10.1/same", "the right title", 0.95)
    duplicate = ver._Candidate("OpenAlex", "10.1/SAME", "the right title", 0.9)
    other = ver._Candidate("OpenAlex", "10.1/other", "the right title, part two", 0.87)
    _patch(monkeypatch, crossref=[best], openalex=[duplicate, other])

    result = ver.verify_reference("the right title")

    assert result.matched
    assert [c.doi for c in result.candidates] == ["10.1/other"]


def test_verify_reference_skips_doi_less_candidates_without_shrinking_the_list(monkeypatch):
    best = ver._Candidate("Crossref", "10.1/best", "the right title", 0.95)
    # Ranks ahead of "other" but has no DOI, so it can't be shown to a reviewer —
    # it must be filtered out before the MAX_CANDIDATES cap, not after, or it would
    # displace "other" instead of just being skipped.
    no_doi = ver._Candidate("OpenAlex", None, "the right title, undated preprint", 0.9)
    other = ver._Candidate("OpenAlex", "10.1/other", "the right title, part two", 0.87)
    _patch(monkeypatch, crossref=[best], openalex=[no_doi, other])

    result = ver.verify_reference("the right title")

    assert result.matched
    assert [c.doi for c in result.candidates] == ["10.1/other"]


def test_crossref_candidate_parses_real_response_shape(monkeypatch):
    fake_response = {
        "message": {
            "items": [
                {"DOI": "10.1/no-title"},  # no "title" key at all — must be skipped
                {"DOI": "10.1/empty-title", "title": []},  # empty list — must be skipped
                {"DOI": "10.1/match", "title": ["Deep learning for reference checking"]},
            ]
        }
    }
    monkeypatch.setattr(ver._crossref, "works", lambda **kwargs: fake_response)

    normalized_query = ver.normalize_title("Deep learning for reference checking")
    ranked = ver._crossref_candidate(normalized_query, "Deep learning for reference checking")

    assert ranked[0].doi == "10.1/match"
    assert ranked[0].source == "Crossref"
    assert ranked[0].score >= ver.MATCH_THRESHOLD


def test_crossref_candidate_uses_preprint_server_as_outlet(monkeypatch):
    fake_response = {
        "message": {
            "items": [{
                "DOI": "10.1/preprint",
                "title": ["A preprint title"],
                "type": "posted-content",
                "institution": [{"name": "Example Preprints"}],
                "publisher": "Example Publisher",
            }]
        }
    }
    monkeypatch.setattr(ver._crossref, "works", lambda **kwargs: fake_response)

    ranked = ver._crossref_candidate(ver.normalize_title("A preprint title"), "A preprint title")

    assert ranked[0].outlet == "Example Preprints"


def test_crossref_candidate_select_omits_fields_invalid_for_works_route(monkeypatch):
    # Crossref's /works route rejects the whole request with HTTP 400 if `select`
    # names a field outside its route-specific whitelist (confirmed live: querying
    # api.crossref.org/works with select=...,institution,... returns
    # {"status": "failed", "message": [{"type": "select-not-available", "value":
    # "institution", ...}]}). "institution" is valid on the /works/{doi} route but
    # not on /works, so including it here silently breaks every lookup at once.
    valid_works_select_fields = {
        "abstract", "URL", "resource", "member", "posted", "score", "created",
        "degree", "update-policy", "short-title", "license", "ISSN",
        "container-title", "issued", "update-to", "issue", "prefix", "approved",
        "indexed", "article-number", "clinical-trial-number", "accepted", "author",
        "group-title", "DOI", "is-referenced-by-count", "updated-by", "event",
        "chair", "standards-body", "original-title", "funder", "translator",
        "published", "archive", "published-print", "alternative-id", "subject",
        "subtitle", "published-online", "publisher-location", "content-domain",
        "reference", "title", "link", "type", "publisher", "volume",
        "references-count", "ISBN", "issn-type", "assertion", "deposited", "page",
        "contributor", "content-created", "short-container-title", "relation",
        "editor",
    }
    captured = {}
    monkeypatch.setattr(
        ver._crossref,
        "works",
        lambda **kwargs: captured.update(kwargs) or {"message": {"items": []}},
    )

    ver._crossref_candidate(ver.normalize_title("some title"), "some title")

    assert set(captured["select"]) <= valid_works_select_fields


def test_openalex_candidate_parses_real_response_shape(monkeypatch):
    fake_results = [
        {"doi": None, "title": "no doi at all"},
        {
            "doi": "https://doi.org/10.1/match",
            "title": "Deep learning for reference checking",
            "primary_location": {"source": {"display_name": "Journal of Reference Checking"}},
        },
    ]

    class _FakeQuery:
        def get(self, per_page):
            return fake_results

    monkeypatch.setattr(ver.pyalex, "Works", lambda: type("W", (), {"search": lambda self, s: _FakeQuery()})())

    normalized_query = ver.normalize_title("Deep learning for reference checking")
    ranked = ver._openalex_candidate(normalized_query, "Deep learning for reference checking")

    assert ranked[0].doi == "10.1/match"
    assert ranked[0].source == "OpenAlex"
    assert ranked[0].score >= ver.MATCH_THRESHOLD
    assert ranked[0].outlet == "Journal of Reference Checking"


def test_extract_doi_from_text_finds_bare_and_url_forms():
    assert ver.extract_doi_from_text("... see https://doi.org/10.1038/s43586-021-00055-w for details") == (
        "10.1038/s43586-021-00055-w"
    )
    assert ver.extract_doi_from_text("Some ref. 10.1000/xyz123. More text.") == "10.1000/xyz123"
    assert ver.extract_doi_from_text("No identifier printed here at all.") is None


def test_verify_reference_resolves_via_direct_doi_before_title_search(monkeypatch):
    # If the title-search path were reached, this would raise — proving the direct
    # DOI lookup short-circuits it entirely. The extracted title is deliberately
    # messy (extra boilerplate a real extractor might grab) but still shares whole
    # words with the resolved title, so it clears _direct_doi_title_is_plausible.
    def _boom(*a, **k):
        raise AssertionError("title-search path should not run when a DOI resolves directly")

    monkeypatch.setattr(ver, "_crossref_candidate", _boom)
    monkeypatch.setattr(ver, "_openalex_candidate", _boom)
    monkeypatch.setattr(
        ver._crossref,
        "works",
        lambda ids: {"message": {"title": ["Network analysis of multivariate data"], "issued": {"date-parts": [[2021]]}}},
    )
    _no_openalex_doi(monkeypatch)

    result = ver.verify_reference(
        "Network analysis of multivariate data (author's personal copy, non-final formatting)",
        raw_text="... (2021). Network analysis of multivariate data. https://doi.org/10.1038/s43586-021-00055-w",
    )

    assert result.matched
    assert result.confidence == 1.0
    assert result.candidate_doi == "10.1038/s43586-021-00055-w"
    assert result.candidate_title == "Network analysis of multivariate data"
    assert result.candidate_year == 2021
    assert result.source == "Crossref (direct DOI)"


def test_verify_reference_demotes_direct_doi_hit_with_unrelated_title(monkeypatch):
    # A DOI that resolves but shares no whole word with the extracted title is more
    # likely a garbled/misread DOI that coincidentally points somewhere else than a
    # real match — this should surface as "review" with the mismatch visible, not
    # be trusted at confidence 1.0 the way a plausible match is.
    def _boom(*a, **k):
        raise AssertionError("title-search path should not run when a DOI resolves directly")

    monkeypatch.setattr(ver, "_crossref_candidate", _boom)
    monkeypatch.setattr(ver, "_openalex_candidate", _boom)
    monkeypatch.setattr(
        ver._crossref,
        "works",
        lambda ids: {"message": {"title": ["Network analysis of multivariate data"], "issued": {"date-parts": [[2021]]}}},
    )
    _no_openalex_doi(monkeypatch)

    result = ver.verify_reference(
        "A completely unrelated paper about frog migration patterns",
        raw_text="... (2021). https://doi.org/10.1038/s43586-021-00055-w",
    )

    assert not result.matched
    assert result.confidence < ver.MATCH_THRESHOLD
    assert len(result.candidates) == 1
    assert result.candidates[0].doi == "10.1038/s43586-021-00055-w"
    assert result.candidates[0].title == "Network analysis of multivariate data"
    assert result.candidates[0].year == 2021
    assert result.candidates[0].source == "Crossref (direct DOI)"


def test_verify_reference_falls_back_to_title_search_when_doi_does_not_resolve(monkeypatch):
    def _raise_not_found(ids):
        raise RuntimeError("404 not found")

    monkeypatch.setattr(ver._crossref, "works", _raise_not_found)
    monkeypatch.setattr(ver.pyalex, "Works", lambda: type("W", (), {"__getitem__": lambda self, k: (_ for _ in ()).throw(RuntimeError("404"))})())
    candidate = ver._Candidate("Crossref", "10.1/real", "the real title", 0.95)
    _patch(monkeypatch, crossref=[candidate], openalex=[])

    result = ver.verify_reference("the real title", raw_text="... 10.9999/does-not-exist ...")

    assert result.matched
    assert result.candidate_doi == "10.1/real"
    assert result.source == "Crossref"


def test_verify_reference_without_raw_text_skips_direct_doi_lookup(monkeypatch):
    def _boom(ids):
        raise AssertionError("direct DOI lookup should not be attempted with no raw_text")

    monkeypatch.setattr(ver._crossref, "works", _boom)
    candidate = ver._Candidate("Crossref", "10.1/xyz", "A title about ecology", 0.95)
    _patch(monkeypatch, crossref=[candidate], openalex=[])

    result = ver.verify_reference("A title about ecology")

    assert result.matched
    assert result.candidate_doi == "10.1/xyz"


def test_extract_package_url_from_text_matches_known_server():
    assert ver.extract_package_url_from_text(
        "R Core Team (2023). dplyr: A Grammar of Data Manipulation. "
        "https://cran.r-project.org/package=dplyr"
    ) == "https://cran.r-project.org/package=dplyr"


def test_extract_package_url_from_text_rejects_lookalike_host():
    # A substring check on "cran.r-project.org" would wrongly match this — the host
    # itself is attacker/typo-controlled, not the real CRAN domain.
    assert ver.extract_package_url_from_text(
        "See https://cran.r-project.org.evil.example/package=dplyr for details."
    ) is None


def test_extract_package_url_from_text_ignores_unrelated_urls():
    assert ver.extract_package_url_from_text("See https://example.com/paper for details.") is None


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_verify_reference_matches_via_reachable_package_url(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("title-search path should not run when a package link resolves")

    monkeypatch.setattr(ver, "_crossref_candidate", _boom)
    monkeypatch.setattr(ver, "_openalex_candidate", _boom)
    monkeypatch.setattr(ver.requests, "head", lambda *a, **k: _FakeResponse(200))

    result = ver.verify_reference(
        "dplyr: A Grammar of Data Manipulation",
        raw_text="R Core Team (2023). dplyr. https://cran.r-project.org/package=dplyr",
    )

    assert result.matched
    assert result.confidence == 1.0
    assert result.source == "cran.r-project.org (link check)"


def test_verify_reference_falls_back_to_get_when_head_not_allowed(monkeypatch):
    monkeypatch.setattr(ver.requests, "head", lambda *a, **k: _FakeResponse(405))
    monkeypatch.setattr(ver.requests, "get", lambda *a, **k: _FakeResponse(200))

    result = ver.verify_reference(
        "dplyr: A Grammar of Data Manipulation",
        raw_text="https://cran.r-project.org/package=dplyr",
    )

    assert result.matched
    assert result.source == "cran.r-project.org (link check)"


def test_verify_reference_falls_back_to_title_search_when_package_url_unreachable(monkeypatch):
    monkeypatch.setattr(ver.requests, "head", lambda *a, **k: _FakeResponse(404))
    candidate = ver._Candidate("Crossref", "10.1/xyz", "dplyr: A Grammar of Data Manipulation", 0.95)
    _patch(monkeypatch, crossref=[candidate], openalex=[])

    result = ver.verify_reference(
        "dplyr: A Grammar of Data Manipulation",
        raw_text="https://cran.r-project.org/package=dplyr",
    )

    assert result.matched
    assert result.candidate_doi == "10.1/xyz"


def test_best_of_picks_highest_scoring_candidate():
    normalized_query = ver.normalize_title("machine learning basics")
    items = [
        {"doi": "10.1/a", "title": "unrelated topic"},
        {"doi": "10.1/b", "title": "machine learning basics"},
        {"doi": None, "title": None},  # candidates with no title must be skipped, not crash
        {},  # and an item carrying nothing at all must not crash either
    ]
    result = ver._best_of(items, normalized_query, "Crossref")
    assert result.doi == "10.1/b"
    assert result.score >= ver.MATCH_THRESHOLD


def test_crossref_candidate_carries_the_cited_by_count(monkeypatch):
    """`is-referenced-by-count` is Crossref's name for it (verified live against
    api.crossref.org, and already inside the /works select whitelist above)."""
    fake_response = {
        "message": {
            "items": [
                {"DOI": "10.1/match", "title": ["A title"], "is-referenced-by-count": 8121},
                {"DOI": "10.1/quiet", "title": ["A quiet title"], "is-referenced-by-count": 0},
                {"DOI": "10.1/silent", "title": ["A silent title"]},
            ]
        }
    }
    monkeypatch.setattr(ver._crossref, "works", lambda **kwargs: fake_response)

    ranked = ver._crossref_candidate(ver.normalize_title("A title"), "A title")
    by_doi = {c.doi: c.citations for c in ranked}

    assert by_doi["10.1/match"] == 8121
    # A work nobody cites and a work the API said nothing about are different answers, and
    # only one of them may be printed as a number.
    assert by_doi["10.1/quiet"] == 0
    assert by_doi["10.1/silent"] is None


def test_openalex_candidate_carries_the_cited_by_count(monkeypatch):
    """`cited_by_count`, verified live against api.openalex.org."""
    fake_results = [
        {
            "doi": "https://doi.org/10.1/match",
            "title": "A title",
            "cited_by_count": 10653,
        }
    ]

    class _FakeQuery:
        def get(self, per_page):
            return fake_results

    monkeypatch.setattr(ver.pyalex, "Works", lambda: type("W", (), {"search": lambda self, s: _FakeQuery()})())

    ranked = ver._openalex_candidate(ver.normalize_title("A title"), "A title")

    assert ranked[0].citations == 10653


def test_the_matched_works_citation_count_reaches_the_result(monkeypatch):
    """The end of the wire. Nothing captured a count before, so every reference reached the
    UI with citations=0 and the frequency chart had nothing to draw."""
    best = ver._Candidate("Crossref", "10.1/x", "A title", 0.99, 2021, "A Journal", 4200)
    _patch(monkeypatch, crossref=[best], openalex=[])

    result = ver.verify_reference("A title")

    assert result.matched
    assert result.candidate_citations == 4200


def test_a_match_from_a_lookup_with_no_count_reports_none(monkeypatch):
    best = ver._Candidate("Crossref", "10.1/x", "A title", 0.99)
    _patch(monkeypatch, crossref=[best], openalex=[])

    assert ver.verify_reference("A title").candidate_citations is None


def test_the_openalex_abstract_is_rebuilt_from_its_inverted_index():
    """OpenAlex publishes the abstract as {word: [positions]} rather than as prose."""
    item = {"abstract_inverted_index": {"The": [0], "effect": [1], "replicates": [2, 4], "reliably": [3]}}

    assert ver._openalex_abstract(item) == "The effect replicates reliably replicates"


def test_a_gap_in_the_positions_does_not_shift_the_words():
    """Real data is not guaranteed dense. Indexing by position rather than assuming a
    complete 0..n sequence keeps a missing slot from moving every later word."""
    item = {"abstract_inverted_index": {"first": [0], "third": [7]}}

    assert ver._openalex_abstract(item) == "first third"


def test_a_work_with_no_abstract_reports_none_rather_than_an_empty_string():
    """Coverage is partial and publisher-dependent — measured absent for an Elsevier DOI
    that OpenAlex otherwise describes fully. The card renders nothing at all for None,
    which is different from rendering an empty field."""
    assert ver._openalex_abstract({}) is None
    assert ver._openalex_abstract({"abstract_inverted_index": {}}) is None


def test_topics_are_preferred_over_openalexs_keywords():
    """Measured side by side on three DOIs: keywords returned "MEDLINE" and "Affect
    (linguistics)" where topics returned "Meta-analysis and systematic reviews"."""
    item = {
        "topics": [
            {"display_name": "Meta-analysis and systematic reviews"},
            {"display_name": "Health Sciences Research"},
            {"display_name": "Quality of Life"},
            {"display_name": "A fourth the card has no room for"},
        ],
        "keywords": [{"display_name": "MEDLINE"}],
    }

    topics = ver._openalex_topics(item)

    assert topics == (
        "Meta-analysis and systematic reviews",
        "Health Sciences Research",
        "Quality of Life",
    )
    assert "MEDLINE" not in topics


def test_a_crossref_retraction_is_read_from_the_update_type_not_the_lists_presence():
    """Verified live against Wakefield 1998, which carries a 2004 correction *and* a 2010
    retraction. Treating the list's presence as the signal would put the loudest warning
    this application has on an ordinary erratum."""
    corrected_only = {"updated-by": [{"type": "correction", "DOI": "10.1/corr"}]}
    retracted = {
        "updated-by": [
            {"type": "correction", "DOI": "10.1/corr"},
            {"type": "retraction", "DOI": "10.1/retraction-notice"},
        ]
    }

    assert ver._crossref_retraction(corrected_only) is None
    assert ver._crossref_retraction(retracted) == "10.1/retraction-notice"


def test_the_two_sources_are_merged_rather_than_one_winning_the_whole_record(monkeypatch):
    """The bug this replaced: dedupe kept the higher-scoring candidate and dropped the
    other outright, so a Crossref win discarded OpenAlex's abstract, topics and retraction
    flag for the *same DOI*. Which source scores higher is decided by title similarity and
    says nothing about which is better informed."""
    crossref = ver._Candidate(
        "Crossref", "10.1/x", "A title", 0.99, retracted=True,
        retraction_doi="10.1/notice",
    )
    # Scores lower and is deduped away by DOI (case-insensitively), which is exactly the
    # candidate whose knowledge used to be thrown out.
    openalex = ver._Candidate(
        "OpenAlex", "10.1/X", "A title", 0.98, year=2021, outlet="A Journal",
        citations=99, abstract="An abstract.", topics=("A topic",),
    )
    _patch(monkeypatch, crossref=[crossref], openalex=[openalex])

    result = ver.verify_reference("A title")

    assert result.candidate_retracted is True
    assert result.candidate_retraction_doi == "10.1/notice"
    assert result.candidate_abstract == "An abstract."
    assert result.candidate_topics == ("A topic",)
    assert result.candidate_citations == 99


def test_a_retraction_from_either_source_survives_the_merge(monkeypatch):
    """The asymmetry the feature turns on: one source reporting a retraction the other has
    not recorded is still a retraction."""
    silent = ver._Candidate("Crossref", "10.1/x", "A title", 0.99, retracted=False)
    flagging = ver._Candidate("OpenAlex", "10.1/x", "A title", 0.98, retracted=True)
    _patch(monkeypatch, crossref=[silent], openalex=[flagging])

    assert ver.verify_reference("A title").candidate_retracted is True


def test_a_work_nobody_reported_on_stays_unknown(monkeypatch):
    """None must never become False: "we did not check" and "we checked and it is clean"
    lead a reviewer to opposite actions."""
    unknown = ver._Candidate("Crossref", "10.1/x", "A title", 0.99)
    _patch(monkeypatch, crossref=[unknown], openalex=[])

    assert ver.verify_reference("A title").candidate_retracted is None


def test_a_direct_doi_hit_is_filled_in_from_both_sources(monkeypatch):
    """The path most references take, and the one that used to return early.

    A reference list normally prints the DOI, so Crossref answered and OpenAlex was never
    asked — leaving the whole matched-work half of the reference card empty (no abstract,
    no topics, no keywords) for exactly the references identified most confidently.
    """
    monkeypatch.setattr(
        ver._crossref,
        "works",
        lambda ids: {
            "message": {
                "title": ["A shared title"],
                "issued": {"date-parts": [[2021]]},
                "is-referenced-by-count": 4200,
                "updated-by": [{"type": "retraction", "DOI": "10.1/notice"}],
            }
        },
    )
    openalex_item = {
        "title": "A shared title",
        "publication_year": 2021,
        "abstract_inverted_index": {"An": [0], "abstract.": [1]},
        "topics": [{"display_name": "A topic"}],
        "keywords": [{"display_name": "A keyword"}],
        "primary_location": {"source": {"display_name": "A Journal"}},
    }
    monkeypatch.setattr(
        ver.pyalex, "Works", lambda: type("W", (), {"__getitem__": lambda self, k: openalex_item})()
    )

    result = ver.verify_reference(
        "A shared title", raw_text="A shared title. https://doi.org/10.1038/s43586-021-00055-w"
    )

    assert result.matched and result.confidence == 1.0
    # From Crossref
    assert result.candidate_citations == 4200
    assert result.candidate_retraction_doi == "10.1/notice"
    # From OpenAlex, which used never to be asked on this path
    assert result.candidate_abstract == "An abstract."
    assert result.candidate_topics == ("A topic",)
    assert result.candidate_keywords == ("A keyword",)
    assert result.candidate_outlet == "A Journal"
    assert result.source == "Crossref + OpenAlex (direct DOI)"


def test_a_direct_doi_retraction_from_either_source_survives(monkeypatch):
    """Crossref names the notice and OpenAlex carries the boolean, so whichever answers
    first must not be able to bury the other's verdict."""
    monkeypatch.setattr(
        ver._crossref, "works", lambda ids: {"message": {"title": ["A shared title"]}}
    )
    monkeypatch.setattr(
        ver.pyalex,
        "Works",
        lambda: type("W", (), {"__getitem__": lambda self, k: {"title": "A shared title", "is_retracted": True}})(),
    )

    result = ver.verify_reference(
        "A shared title", raw_text="A shared title. https://doi.org/10.1038/s43586-021-00055-w"
    )

    assert result.candidate_retracted is True


def test_a_direct_doi_still_resolves_when_only_one_source_answers(monkeypatch):
    monkeypatch.setattr(
        ver._crossref, "works", lambda ids: (_ for _ in ()).throw(RuntimeError("404"))
    )
    monkeypatch.setattr(
        ver.pyalex,
        "Works",
        lambda: type("W", (), {"__getitem__": lambda self, k: {"title": "A shared title", "publication_year": 2021}})(),
    )

    result = ver.verify_reference(
        "A shared title", raw_text="A shared title. https://doi.org/10.1038/s43586-021-00055-w"
    )

    assert result.matched
    assert result.source == "OpenAlex (direct DOI)"


def test_a_titleless_crossref_record_takes_its_title_from_openalex(monkeypatch):
    """Crossref answers first on the direct-DOI path. A record that resolves without a
    title would otherwise leave the match titleless while OpenAlex had one, and the
    plausibility check then demotes a correct, DOI-confirmed match to manual review."""
    monkeypatch.setattr(ver._crossref, "works", lambda ids: {"message": {"issued": {"date-parts": [[2021]]}}})
    monkeypatch.setattr(
        ver.pyalex,
        "Works",
        lambda: type("W", (), {"__getitem__": lambda self, k: {"title": "A shared title"}})(),
    )

    result = ver.verify_reference(
        "A shared title", raw_text="A shared title. https://doi.org/10.1038/s43586-021-00055-w"
    )

    assert result.matched
    assert result.candidate_title == "A shared title"


def test_a_budget_refusal_closes_openalex_for_the_rest_of_the_run(monkeypatch):
    """OpenAlex meters against a daily budget, not a rate: once it is spent it stays spent
    until midnight UTC. Without this, a thirty-reference check makes thirty more requests
    that cannot succeed, each costing a network round-trip."""
    _clear_openalex_refusal(monkeypatch)
    calls = []

    def _refuse(*_a, **_k):
        calls.append(1)
        raise RuntimeError("429 Client Error: Too Many Requests")

    monkeypatch.setattr(ver.pyalex, "Works", _refuse)
    monkeypatch.setattr(ver._crossref, "works", lambda **k: {"message": {"items": []}})

    for _ in range(3):
        ver.verify_reference("a title")

    assert len(calls) == 1
    assert ver.openalex_refusal() is not None
    assert "daily free budget is used up" in ver.openalex_refusal()


def test_an_ordinary_failure_does_not_disable_the_source(monkeypatch):
    """A timeout says nothing about the next reference, and must not take OpenAlex out for
    the whole check."""
    _clear_openalex_refusal(monkeypatch)
    calls = []

    def _timeout(*_a, **_k):
        calls.append(1)
        raise RuntimeError("connection timed out")

    monkeypatch.setattr(ver.pyalex, "Works", _timeout)
    monkeypatch.setattr(ver._crossref, "works", lambda **k: {"message": {"items": []}})

    for _ in range(3):
        ver.verify_reference("a title")

    assert len(calls) == 3
    assert ver.openalex_refusal() is None


def test_an_api_key_is_used_when_one_is_configured(monkeypatch):
    """The free key raises the daily allowance tenfold, which is the difference between a
    couple of dozen checks a day and a couple of hundred."""
    monkeypatch.setenv(ver._OPENALEX_API_KEY_ENV, "a-free-key")
    monkeypatch.setenv(CONTACT_EMAIL_ENV, "ops@example.org")
    monkeypatch.setattr(ver.pyalex.config, "api_key", None, raising=False)

    ver._configure_openalex()

    assert ver.pyalex.config.api_key == "a-free-key"
    assert ver.pyalex.config.email == "ops@example.org"


def test_no_contact_address_is_sent_when_none_is_configured(monkeypatch):
    """The address reaches OpenAlex on every lookup, so a fork that has not set one must
    send nothing rather than whoever built the code — see openrefcheck.contact."""
    monkeypatch.delenv(CONTACT_EMAIL_ENV, raising=False)
    monkeypatch.setattr(ver.pyalex.config, "email", "stale@example.org", raising=False)

    ver._configure_openalex()

    assert ver.pyalex.config.email is None


def test_a_blank_contact_address_counts_as_unset(monkeypatch):
    """Exporting the variable empty is how a shell or a Cloud Run env var clears it; it
    must not become a malformed `mailto:` in front of the API."""
    monkeypatch.setenv(CONTACT_EMAIL_ENV, "   ")

    ver._configure_openalex()

    assert ver.pyalex.config.email is None


def test_the_refusal_expires_when_the_budget_resets(monkeypatch):
    """The review finding this closes: the flag had no expiry, so one 429 disabled OpenAlex
    for the life of the process — days, in the web app — while the message on screen went
    on promising a reset at midnight UTC. The code has to keep the promise the UI makes.
    """
    _clear_openalex_refusal(monkeypatch)
    before = _dt.datetime(2026, 8, 11, 22, 30, tzinfo=_dt.timezone.utc)
    monkeypatch.setattr(ver, "_utcnow", lambda: before)

    calls = []

    def _refuse(*_a, **_k):
        calls.append(1)
        raise RuntimeError("429 Client Error: Too Many Requests")

    monkeypatch.setattr(ver.pyalex, "Works", _refuse)
    monkeypatch.setattr(ver._crossref, "works", lambda **k: {"message": {"items": []}})

    ver.verify_reference("a title")
    assert ver.openalex_refusal() is not None
    assert "2026-08-12 00:00 UTC" in ver.openalex_refusal()

    # Still before midnight: the door stays shut and no further request is made.
    monkeypatch.setattr(ver, "_utcnow", lambda: before + _dt.timedelta(minutes=29))
    ver.verify_reference("a title")
    assert len(calls) == 1
    assert ver.openalex_refusal() is not None

    # Past the reset: the banner clears and OpenAlex is asked again.
    after = _dt.datetime(2026, 8, 12, 0, 0, 1, tzinfo=_dt.timezone.utc)
    monkeypatch.setattr(ver, "_utcnow", lambda: after)
    assert ver.openalex_refusal() is None

    found = ver._Candidate("OpenAlex", "10.1/x", "a title", 0.99)
    monkeypatch.setattr(ver, "_openalex_candidate", lambda *_a: [found])
    result = ver.verify_reference("a title")

    assert result.matched
    assert result.candidate_doi == "10.1/x"


def test_the_server_gets_to_say_when_to_come_back(monkeypatch):
    """A Retry-After beats an assumption about when the day rolls over. Usually absent —
    pyalex retries internally and surfaces a RetryError with no response attached — which
    is why the midnight fallback exists rather than being the only rule."""
    _clear_openalex_refusal(monkeypatch)
    now = _dt.datetime(2026, 8, 11, 12, 0, tzinfo=_dt.timezone.utc)
    monkeypatch.setattr(ver, "_utcnow", lambda: now)

    exc = RuntimeError("429 Too Many Requests")
    exc.response = SimpleNamespace(headers={"Retry-After": "3600"})

    ver._note_openalex_failure(exc)

    assert "2026-08-11 13:00 UTC" in ver.openalex_refusal()


def test_a_refusal_without_a_usable_retry_after_falls_back_to_midnight(monkeypatch):
    _clear_openalex_refusal(monkeypatch)
    now = _dt.datetime(2026, 8, 11, 12, 0, tzinfo=_dt.timezone.utc)
    monkeypatch.setattr(ver, "_utcnow", lambda: now)

    exc = RuntimeError("429 Too Many Requests")
    exc.response = SimpleNamespace(headers={"Retry-After": "not-a-number"})

    ver._note_openalex_failure(exc)

    assert "2026-08-12 00:00 UTC" in ver.openalex_refusal()
