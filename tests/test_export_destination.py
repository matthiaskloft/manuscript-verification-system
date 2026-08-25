"""Where a report is allowed to be written, which depends on who chose the path.

The Report Export screen offers a filesystem path to write to. That control is safe in
the native desktop app — the person typing the path is the person at the machine — and
is a remote arbitrary file write in the hosted demo, where the path arrives from an
unauthenticated visitor's browser and the write lands in the server's container. These
tests pin the split, and the fallback direction of the check that decides it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from refcheck.gui.models import ReferenceResult
from refcheck.webui.pages import report_export
from refcheck.webui.state import AppState


def _state() -> AppState:
    state = AppState()
    state.results = [
        ReferenceResult(
            n=1,
            raw="Author, A. (2020). A title.",
            title="A title",
            doi="10.1/1",
            status="verified",
            confidence=0.99,
        )
    ]
    return state


@pytest.fixture(autouse=True)
def _silence_notify(monkeypatch):
    from nicegui import ui

    monkeypatch.setattr(ui, "notify", lambda *a, **k: None)


def test_a_server_session_refuses_to_write_a_client_supplied_path(tmp_path, monkeypatch):
    """The finding this closes: the demo deployment served this screen, so any visitor
    could name a path and have the server write an HTML file to it."""
    monkeypatch.setattr(report_export, "is_native_session", lambda: False)
    target = tmp_path / "attacker-chosen.html"

    report_export._do_export(
        _state(),
        SimpleNamespace(value=str(target), set_value=lambda _v: None),
        SimpleNamespace(set_text=lambda _t: None),
    )

    assert not target.exists()


def test_a_native_session_still_writes_the_path_the_user_picked(tmp_path, monkeypatch):
    monkeypatch.setattr(report_export, "is_native_session", lambda: True)
    target = tmp_path / "report.html"

    report_export._do_export(
        _state(),
        SimpleNamespace(value=str(target), set_value=lambda _v: None),
        SimpleNamespace(set_text=lambda _t: None),
    )

    assert target.exists()
    assert "<html" in target.read_text(encoding="utf-8").lower()


def test_an_unanswerable_native_check_counts_as_not_native(monkeypatch):
    """`app.native.main_window` is absent or raises in plenty of situations — a NiceGUI
    upgrade, a partially initialised app, a test. Every one of them must fall to the safe
    side, because the unsafe side is the arbitrary write."""

    class _Exploding:
        @property
        def main_window(self):
            raise RuntimeError("no native app here")

    monkeypatch.setattr(report_export.app, "native", _Exploding())

    assert report_export.is_native_session() is False


def test_a_plain_web_process_is_not_native():
    """No monkeypatching: this is how the module answers under the web entry point."""
    assert report_export.is_native_session() is False
