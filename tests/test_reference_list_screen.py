"""What the References screen and the report say about the list's completeness.

The wording is decided in `gui.reference_list_display` and tested there. This module is
the other half of the same argument test_citation_screens.py makes: a correct decision
that never reaches the page is not a feature, and a note about the reference list is
worth nothing unless it is on the screen above the numbers it qualifies.
"""

from __future__ import annotations

from types import SimpleNamespace

from nicegui import ui

from refcheck.extraction.reference_list_audit import NOT_AUDITED, ReferenceListAudit
from refcheck.gui.models import ReferenceResult
from refcheck.gui.report_builder import DEFAULT_EXPORT_INCLUDED, ReportMeta, build_html_report
from refcheck.webui.pages import references
from refcheck.webui.state import AppState

from test_citation_screens import _texts

_ACTIONS = SimpleNamespace(refresh_content=lambda: None)


def _reference(n: int) -> ReferenceResult:
    return ReferenceResult(
        n=n, raw=f"Author {n}. (2020). A title.", title=f"A title {n}", doi=f"10.1/{n}",
        status="verified", confidence=0.9,
    )


def _render(audit: ReferenceListAudit, count: int = 2) -> list[str]:
    state = AppState()
    state.results = [_reference(n) for n in range(1, count + 1)]
    state.audit = audit
    root = ui.column()
    with root:
        references.render(state, _ACTIONS)
    return _texts(root)


def _report(audit: ReferenceListAudit, count: int = 2) -> str:
    return build_html_report(
        [_reference(n) for n in range(1, count + 1)],
        decisions={},
        meta=ReportMeta(document="m.pdf", check_date="2026-08-11"),
        included=dict(DEFAULT_EXPORT_INCLUDED),
        audit=audit,
    )


def test_a_short_list_is_flagged_above_the_table():
    rendered = _render(
        ReferenceListAudit(read=True, numbered=True, printed_count=4, missing=(3, 4)), count=2
    )

    assert any("numbers 4 entries" in text for text in rendered)
    assert any("3 and 4" in text for text in rendered)


def test_a_whole_list_is_confirmed_rather_than_left_blank():
    """The quiet half of the same line. A reviewer who sees nothing cannot tell a list that
    was checked and matched from one nothing compared against anything, and the second is
    what every DOCX produces."""
    rendered = _render(ReferenceListAudit(read=True, numbered=True, printed_count=2), count=2)

    assert any("All 2 references match" in text for text in rendered)


def test_an_unchecked_list_puts_nothing_on_the_screen():
    rendered = _render(NOT_AUDITED)

    assert not any("reference list" in text.lower() and "print" in text.lower() for text in rendered)


def test_the_report_carries_the_same_finding():
    """Same wording, one source. The report outlives the session, so a caveat that is on
    screen and not in the file is a caveat the reader of the file never gets."""
    html = _report(ReferenceListAudit(read=True, numbered=True, printed_count=4, missing=(3, 4)))

    assert "numbers 4 entries" in html
    assert "3 and 4" in html


def test_a_report_built_without_an_audit_claims_nothing_about_the_list():
    """The default is "not checked", so a caller that knows nothing about the audit — the
    benchmark harness, a test, any future caller — produces a report that stays silent
    rather than one quietly asserting a complete reference list."""
    html = build_html_report(
        [_reference(1)],
        decisions={},
        meta=ReportMeta(document="m.pdf", check_date="2026-08-11"),
        included=dict(DEFAULT_EXPORT_INCLUDED),
    )

    assert "match the list this document prints" not in html
