"""In-text citations in the exported report (citation plan phase 5, step 5).

The screen shows passages outright; this gate protects a file. An export is written to
disk, mailed, attached to a review, so it keeps an opt-in of its own that starts off —
and the tests that matter here are the ones about what does *not* come out.
"""

from __future__ import annotations

from types import SimpleNamespace

from openrefcheck.extraction.citation_matching import CitationMatch, MatchStatus
from openrefcheck.extraction.document_artifact import DocumentArtifact, SourceAnchor
from openrefcheck.gui.models import ReferenceResult
from openrefcheck.gui.real_pipeline import CITATIONS_NONE_DETECTED, CITATIONS_NOT_RUN, CITATIONS_OK
from openrefcheck.gui.report_builder import (
    DEFAULT_EXPORT_INCLUDED,
    ReportMeta,
    build_html_report,
)

_PASSAGE = "The effect replicates (Author, 2020) in every sample we looked at."
_LINES = [f"An opening sentence. {_PASSAGE}", "", "An unrelated closing paragraph."]
_META = ReportMeta(document="manuscript.pdf", check_date="2026-08-11")


def _artifact() -> DocumentArtifact:
    return DocumentArtifact.from_lines(_LINES, raw_text="\n".join(_LINES), parser="test")


def _results(count: int = 2) -> list[ReferenceResult]:
    return [
        ReferenceResult(
            n=n, raw=f"Author {n}. (2020). A title.", title="A title", doi=f"10.1/{n}",
            status="verified", confidence=0.9,
        )
        for n in range(1, count + 1)
    ]


def _match(n: int = 1) -> CitationMatch:
    artifact = _artifact()
    start = artifact.body_text.index("(Author, 2020)")
    return CitationMatch(
        marker_text="(Author, 2020)", tier="tier0", status=MatchStatus.RESOLVED,
        reference_n=n,
        anchor=SourceAnchor(start=start, end=start + 14, paragraph_index=0, source_line=0),
    )


def _report(included: dict | None = None, **kwargs) -> str:
    settings = dict(DEFAULT_EXPORT_INCLUDED)
    settings.update(included or {})
    return build_html_report(_results(), {}, _META, settings, **kwargs)


def test_passages_are_off_by_default():
    """The assertion this file exists for. A reviewer who exports without reading the
    checkbox list must not find the manuscript's sentences in the file."""
    assert DEFAULT_EXPORT_INCLUDED["citation_passages"] is False

    html = _report(citation_matches=[_match()], citation_run_status=CITATIONS_OK, artifact=_artifact())

    assert _PASSAGE not in html


def test_the_structured_figures_are_on_by_default():
    """Counts and flags carry no manuscript prose beyond the reference list the report
    already prints, so they are not what the gate is for."""
    html = _report(citation_matches=[_match()], citation_run_status=CITATIONS_OK, artifact=_artifact())

    assert "In-text citations" in html
    assert "Cited once in this manuscript" in html
    assert "No in-text citation found for this reference" in html


def test_passages_appear_only_when_that_box_is_ticked():
    html = _report(
        {"citation_passages": True},
        citation_matches=[_match()],
        citation_run_status=CITATIONS_OK,
        artifact=_artifact(),
    )

    assert _PASSAGE in html


def test_passages_on_screen_do_not_put_them_in_the_file(tmp_path, monkeypatch):
    """The screen shows passages unconditionally since the on-screen gate was removed
    (2026-08-11), which makes this the surviving boundary: a reviewer reading passages in
    the app exports, does not touch the checkbox list, and gets a file with no manuscript
    prose in it."""
    from nicegui import ui

    from openrefcheck.webui.pages import report_export
    from openrefcheck.webui.state import AppState

    monkeypatch.setattr(ui, "notify", lambda *a, **k: None)
    # Writing a caller-supplied path is the native desktop app's export; a server refuses
    # it outright (report_export.is_native_session). This test is about what lands *in*
    # the file, so it takes the native branch.
    monkeypatch.setattr(report_export, "is_native_session", lambda: True)
    state = AppState()
    state.results = _results()
    state.citation_matches = (_match(),)
    state.citation_run_status = CITATIONS_OK
    state.document_artifact = _artifact()

    target = tmp_path / "report.html"
    report_export._do_export(
        state,
        SimpleNamespace(value=str(target), set_value=lambda _v: None),
        SimpleNamespace(set_text=lambda _t: None),
    )

    written = target.read_text(encoding="utf-8")
    assert _PASSAGE not in written
    assert "Cited once in this manuscript" in written


def test_a_report_from_a_caller_that_knows_nothing_about_citations_claims_nothing():
    """The keyword arguments default to "the search did not run" rather than to an empty
    match list, so an old call site produces a report that says so instead of one that
    reads as a clean manuscript."""
    html = _report()

    assert "The in-text citation search did not run" in html
    assert "No in-text citation found" not in html


def test_a_manuscript_with_no_detected_markers_says_so_rather_than_flagging_everything():
    html = _report(citation_matches=[], citation_run_status=CITATIONS_NONE_DETECTED)

    assert "No in-text citations were detected in this manuscript" in html
    assert "No in-text citation found for this reference" not in html


def test_the_section_can_be_left_out_entirely():
    html = _report(
        {"citations": False}, citation_matches=[_match()], citation_run_status=CITATIONS_OK
    )

    assert "In-text citations" not in html


def test_a_passage_cannot_be_written_without_the_artifact_it_came_from():
    """Belt and braces: the toggle is on, the matches are there, and there is nothing to
    quote from. The report must come out without passages rather than raise mid-export."""
    html = _report(
        {"citation_passages": True},
        citation_matches=[_match()],
        citation_run_status=CITATIONS_OK,
        artifact=None,
    )

    assert _PASSAGE not in html
    assert "Cited once in this manuscript" in html


def test_a_passage_is_escaped_like_every_other_untrusted_string():
    """Manuscript text reaches the template the same way raw citations do, and the report
    is opened in a browser."""
    lines = ["A claim <script>alert(1)</script> (Author, 2020) follows."]
    artifact = DocumentArtifact.from_lines(lines, raw_text=lines[0], parser="test")
    start = artifact.body_text.index("(Author, 2020)")
    match = CitationMatch(
        marker_text="(Author, 2020)", tier="tier0", status=MatchStatus.RESOLVED, reference_n=1,
        anchor=SourceAnchor(start=start, end=start + 14, paragraph_index=0, source_line=0),
    )

    html = _report(
        {"citation_passages": True},
        citation_matches=[match],
        citation_run_status=CITATIONS_OK,
        artifact=artifact,
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_the_report_and_the_screen_use_the_same_wording():
    """One source for the sentences, so an exported report cannot contradict the screen
    it was generated from."""
    from openrefcheck.gui import citation_display

    matches = [_match()]
    html = _report(citation_matches=matches, citation_run_status=CITATIONS_OK, artifact=_artifact())
    records = citation_display.per_reference([1, 2], matches, CITATIONS_OK)

    assert records[1].label in html
    assert records[2].label in html


def test_the_default_settings_cover_every_checkbox_on_the_export_screen():
    """A key present on the screen and missing here falls back to a guess; for the passage
    toggle the guess would have been "on"."""
    from openrefcheck.webui.pages.report_export import EXPORT_ITEMS

    assert {key for key, _, _ in EXPORT_ITEMS} == set(DEFAULT_EXPORT_INCLUDED)


def test_the_run_status_default_is_the_one_that_claims_least():
    import inspect

    signature = inspect.signature(build_html_report)

    assert signature.parameters["citation_run_status"].default == CITATIONS_NOT_RUN
