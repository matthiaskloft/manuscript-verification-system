"""Which engine-status refresh gets the last word (PR #66's review).

Waiting out a GROBID cold start made this refresh long — up to three minutes — and the
engine dropdown can be clicked while one is in flight. Two refreshes then race, and
before `EngineStatusView` took tickets the *older* one finished last and assigned last:
picking "Built-in parser" mid-wait showed it immediately and then, minutes later, put the
GROBID answer back. The label disagreed with the button, and the label was wrong.

The probe is injected and driven by futures, so completion order is chosen rather than
hoped for — the ordering is the whole subject, and a test that let the event loop decide
it would pass either way.

Each test drives its own loop through `asyncio.run` rather than using an async test
function: this project has no pytest-asyncio, and a plugin dependency added for one test
module would also land in the deployment image.
"""

from __future__ import annotations

import asyncio

from refcheck.extraction.engine_status import (
    ANCHOR_ENGINE_NAME,
    GROBID_ENGINE_NAME,
    EngineStatus,
)
from refcheck.webui.pages import upload
from refcheck.webui.pages.upload import EngineStatusView

GROBID_UP = EngineStatus(GROBID_ENGINE_NAME, "reachable", reachable=True)
GROBID_DOWN = EngineStatus(ANCHOR_ENGINE_NAME, "GROBID not reachable — falling back", reachable=False)
ANCHOR = EngineStatus(ANCHOR_ENGINE_NAME, "selected manually", reachable=True)


class Probe:
    """A probe whose every call is a future the test completes when it chooses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.pending: list[asyncio.Future] = []

    async def __call__(self, preference: str, waiting: bool) -> EngineStatus:
        self.calls.append((preference, waiting))
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending.append(future)
        return await future


async def _settle() -> None:
    """Let every ready callback run, without deciding anything about ordering."""
    for _ in range(5):
        await asyncio.sleep(0)


def _run(scenario, monkeypatch) -> None:
    """Run one interleaving with the configured GROBID treated as a deployed service.

    A local URL never waits (`grobid.has_cold_start`), so without this there is no
    overlap to race.
    """
    monkeypatch.setattr(upload, "has_cold_start", lambda: True)
    probe = Probe()
    renders: list[int] = []
    view = EngineStatusView(probe=probe, render=lambda: renders.append(1))
    asyncio.run(scenario(view, probe, renders))


def test_a_stale_wait_finishing_last_does_not_get_the_last_word(monkeypatch):
    """The defect, in the order that produced it: the user switches engine mid-wait, the
    new refresh answers immediately, and the abandoned cold-start wait completes minutes
    later. It must not put its answer back."""

    async def scenario(view, probe, _renders):
        first = asyncio.ensure_future(view.refresh("auto"))
        await _settle()
        probe.pending[0].set_result(GROBID_DOWN)  # the fast probe fails -> the wait begins
        await _settle()
        assert view.waking is True

        # The user picks another engine: `pick` invalidates synchronously, then starts a
        # refresh of its own.
        view.invalidate()
        second = asyncio.ensure_future(view.refresh("anchor"))
        await _settle()
        probe.pending[-1].set_result(ANCHOR)
        await _settle()
        assert view.status is ANCHOR
        assert view.waking is False

        # Only now does the abandoned wait return, with the answer for the old preference.
        probe.pending[1].set_result(GROBID_UP)
        await first
        await second

        assert view.status is ANCHOR, "a retired refresh overwrote the current one"
        assert view.waking is False

    _run(scenario, monkeypatch)


def test_the_newest_refresh_still_commits_when_it_finishes_last(monkeypatch):
    """The guard must retire the *older* ticket, not simply the one that returns second —
    otherwise it would trade this bug for its mirror image and nothing would ever
    update."""

    async def scenario(view, probe, _renders):
        stale = asyncio.ensure_future(view.refresh("auto"))
        await _settle()
        fresh = asyncio.ensure_future(view.refresh("auto"))
        await _settle()

        probe.pending[0].set_result(GROBID_UP)  # the older one answers first, and is stale
        await _settle()
        probe.pending[1].set_result(GROBID_DOWN)  # the newer one answers second
        await _settle()
        probe.pending[-1].set_result(GROBID_UP)
        await stale
        await fresh

        assert view.status is GROBID_UP

    _run(scenario, monkeypatch)


def test_a_retired_refresh_draws_nothing_after_it_is_retired(monkeypatch):
    """Not just the value: a stale refresh that still called `render` would repaint the
    line from state it does not own, which is the same wrong label by another route."""

    async def scenario(view, probe, renders):
        task = asyncio.ensure_future(view.refresh("auto"))
        await _settle()
        view.invalidate()
        drawn = len(renders)

        probe.pending[0].set_result(GROBID_UP)
        await task

        assert len(renders) == drawn

    _run(scenario, monkeypatch)


def test_an_uncontested_refresh_commits_both_of_its_answers(monkeypatch):
    """The ordinary path, so the guard cannot be satisfied by refusing to commit at all.
    The waking state is shown, then replaced by the answer the wait found."""

    async def scenario(view, probe, renders):
        task = asyncio.ensure_future(view.refresh("auto"))
        await _settle()
        probe.pending[0].set_result(GROBID_DOWN)
        await _settle()

        assert view.waking is True
        assert view.status is GROBID_DOWN

        probe.pending[1].set_result(GROBID_UP)
        await task

        assert view.waking is False
        assert view.status is GROBID_UP
        assert probe.calls == [("auto", False), ("auto", True)]
        assert renders

    _run(scenario, monkeypatch)


def test_a_reachable_grobid_never_enters_the_waking_state(monkeypatch):
    """No wait, no second probe, no "starting" label on the overwhelmingly common path."""

    async def scenario(view, probe, _renders):
        task = asyncio.ensure_future(view.refresh("auto"))
        await _settle()
        probe.pending[0].set_result(GROBID_UP)
        await task

        assert view.status is GROBID_UP
        assert view.waking is False
        assert probe.calls == [("auto", False)]

    _run(scenario, monkeypatch)
