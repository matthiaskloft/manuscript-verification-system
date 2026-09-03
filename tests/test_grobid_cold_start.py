"""Waiting out a GROBID that is still starting (docs/demo-deployment-decision.md).

The demo deploys GROBID as its own Cloud Run service at zero minimum instances, so the
probe that reports it unreachable is frequently the probe that started it. One attempt
cannot tell "down" from "not up yet", and reporting the first answer as settled sends a
reviewer through a whole check on the fallback parser for no reason.

The clock and the probe are both injected here. A test that really waited would be
measuring `time.sleep`, and the thing worth pinning is the decision — how many attempts,
until when, and for which URLs — not the duration.
"""

from __future__ import annotations

import pytest

from openrefcheck.extraction import grobid


@pytest.fixture
def clock(monkeypatch):
    """A monotonic clock that only moves when the code under test sleeps."""
    now = [0.0]
    monkeypatch.setattr(grobid.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(grobid.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    return now


@pytest.fixture
def answers(monkeypatch):
    """Queue the probe's answers; the last one repeats once the queue runs out."""

    def install(*sequence):
        remaining = list(sequence)
        seen = []

        def probe(url=None):
            seen.append(url)
            return remaining.pop(0) if len(remaining) > 1 else remaining[0]

        monkeypatch.setattr(grobid, "is_grobid_available", probe)
        return seen

    return install


# --------------------------------------------------------------------------------------
# has_cold_start — which URLs are worth waiting on
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["http://localhost:8070", "http://127.0.0.1:8070"])
def test_a_local_container_is_never_treated_as_starting(url):
    """It is running or it is not, and asking again changes nothing. A UI that said
    "starting…" for three minutes on a developer machine with no GROBID would be wrong
    about the commonest case there is."""
    assert grobid.has_cold_start(url) is False


@pytest.mark.parametrize("url", ["https://refcheck-grobid-abc.a.run.app", "http://grobid.internal"])
def test_a_deployed_service_is_worth_waiting_on(url):
    assert grobid.has_cold_start(url) is True


# --------------------------------------------------------------------------------------
# wait_for_grobid
# --------------------------------------------------------------------------------------


def test_a_reachable_grobid_costs_no_waiting_at_all(clock, answers):
    """The warm path, which is every path except the first request after an idle period.
    It must not pay for the cold one."""
    seen = answers(True)

    assert grobid.wait_for_grobid("https://grobid.example") is True
    assert len(seen) == 1
    assert clock[0] == 0.0


def test_a_service_that_comes_up_late_is_found_rather_than_written_off(clock, answers):
    """The defect. Four failed probes and then success is a cold start, not a deployment
    without GROBID, and the difference is the whole point of the status line."""
    seen = answers(False, False, False, False, True)

    assert grobid.wait_for_grobid("https://grobid.example") is True
    assert len(seen) == 5


def test_a_service_that_never_answers_gives_up_at_the_deadline(clock, answers):
    """The other side: waiting has to end, or the screen promises something that is not
    coming. Bounded by the deadline, not by an attempt count."""
    answers(False)

    assert grobid.wait_for_grobid("https://grobid.example", deadline=30) is False
    assert clock[0] < 30


def test_a_local_url_gets_one_attempt_and_no_wait(clock, answers):
    """`has_cold_start` decides this, and it is the reason a developer with no GROBID
    sees the fallback immediately instead of a three-minute pause."""
    seen = answers(False)

    assert grobid.wait_for_grobid("http://localhost:8070") is False
    assert len(seen) == 1
    assert clock[0] == 0.0


def test_the_caller_is_told_how_long_it_has_been_waiting(clock, answers):
    """So the screen can show that something is still happening. A wait with no visible
    state is the half of this the deployment note asked for that a retry alone does not
    give — reported elapsed times rise, so a caller can render a count."""
    answers(False, False, False, True)
    elapsed = []

    grobid.wait_for_grobid("https://grobid.example", on_wait=elapsed.append)

    assert elapsed == sorted(elapsed)
    assert len(elapsed) == 3
    assert elapsed[0] == 0.0


def test_the_deadline_is_not_reached_by_overshooting_it(clock, answers):
    """The pause is checked *before* it is taken, so the wait never sleeps past the
    deadline it was given. (A probe already in flight can still overrun it — see
    `wait_for_grobid` — but the loop itself will not start a wait it cannot finish.)"""
    answers(False)

    grobid.wait_for_grobid("https://grobid.example", deadline=10)

    assert clock[0] <= 10


# --------------------------------------------------------------------------------------
# The status line's use of it
# --------------------------------------------------------------------------------------


def test_the_engine_status_asks_whichever_probe_it_was_given(monkeypatch):
    """The Upload screen runs the fast probe first and the waiting one only if that
    fails, so the parameter is what keeps a three-minute wait out of every other caller
    of `current_engine_status`."""
    from openrefcheck.extraction import engine_status

    monkeypatch.setattr(engine_status, "grobid_url", lambda: "https://grobid.example")
    monkeypatch.setattr(
        engine_status,
        "is_grobid_available",
        lambda: (_ for _ in ()).throw(AssertionError("the injected probe should be used")),
    )

    status = engine_status.current_engine_status(probe=lambda: True)

    assert status.name == engine_status.GROBID_ENGINE_NAME
    assert status.reachable is True
