import asyncio

from refcheck.extraction.citation_matching import CitationMatch, MatchStatus
from refcheck.extraction.engine_status import ENGINE_AUTO
from refcheck.gui.models import ReferenceResult
from refcheck.gui.real_pipeline import CITATIONS_OK, BibliographyNotFoundError, CheckResult
from refcheck.webui import check_runner
from refcheck.webui.check_runner import CheckRunner


class _PendingTask:
    def __init__(self) -> None:
        self.cancelled = False

    def done(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True


def test_request_cancel_stops_coordinator_immediately():
    runner = object.__new__(CheckRunner)
    runner._cancel_requested = False
    runner._task = _PendingTask()

    runner.request_cancel()

    assert runner._cancel_requested is True
    assert runner._task.cancelled is True


def test_request_cancel_is_idempotent():
    runner = object.__new__(CheckRunner)
    runner._cancel_requested = True
    runner._task = None

    runner.request_cancel()

    assert runner._cancel_requested is True


def _runner(**callbacks) -> CheckRunner:
    """A runner without its NiceGUI client context, which _run_real never touches."""
    runner = object.__new__(CheckRunner)
    runner._loaded_file = None
    runner._engine = ENGINE_AUTO
    runner._cancel_requested = False
    runner._task = None
    runner._on_progress = callbacks.get("on_progress", lambda *_: None)
    runner._on_finished = callbacks.get("on_finished", lambda _result: None)
    runner._on_cancelled = callbacks.get("on_cancelled", lambda: None)
    runner._on_failed = callbacks.get("on_failed", lambda _message: None)
    return runner


def test_the_result_bundle_is_forwarded_unchanged(monkeypatch):
    """The runner is a transport, not a consumer: whatever the pipeline returns has to
    arrive at the UI intact, since everything the citation feature needs is in there and
    the uploaded file is deleted as soon as it does."""
    produced = CheckResult(
        references=[ReferenceResult(n=1, raw="Doe, J. (2020).", title="A title", doi="10.1/x", status="verified", confidence=0.9)],
        citation_matches=(CitationMatch(marker_text="(Doe, 2020)", tier="anchor", status=MatchStatus.RESOLVED, reference_n=1),),
        citation_run_status=CITATIONS_OK,
    )
    monkeypatch.setattr(check_runner, "run_real_pipeline", lambda *a, **k: produced)

    received = []
    progress = []
    runner = _runner(on_finished=received.append, on_progress=lambda *args: progress.append(args))

    asyncio.run(runner._run_real())

    assert received == [produced]
    assert progress[-1] == (2, 1, 1)


def test_a_failure_is_reported_as_a_message_not_as_an_empty_result(monkeypatch):
    def raise_not_found(*_args, **_kwargs):
        raise BibliographyNotFoundError("no heading found")

    monkeypatch.setattr(check_runner, "run_real_pipeline", raise_not_found)

    failures = []
    finished = []
    runner = _runner(on_failed=failures.append, on_finished=finished.append)

    asyncio.run(runner._run_real())

    assert failures == ["no heading found"]
    assert finished == []
