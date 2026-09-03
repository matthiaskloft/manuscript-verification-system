"""Guards the demo-mode retention disclaimer against shipping unresolved.

See docs/pyside-mvp-mockup-spec.md "Open follow-up" — the retention policy for the
hosted demo server was undecided; this must not silently regress to a placeholder.
"""

from openrefcheck.gui.deployment import MODES, PRIVACY_STRIPE, RETENTION_NOTICE

_PLACEHOLDER_MARKERS = ("TODO", "FIXME", "placeholder", "[TODO")


def test_retention_notice_has_no_placeholder():
    for marker in _PLACEHOLDER_MARKERS:
        assert marker.lower() not in RETENTION_NOTICE.lower()


def test_demo_mode_body_has_no_placeholder():
    demo_body = MODES["demo"].body
    for marker in _PLACEHOLDER_MARKERS:
        assert marker.lower() not in demo_body.lower()


def test_retention_notice_states_the_resolved_policy():
    """The copy names the two events that actually delete a file, because a visitor
    reading it is being told when their manuscript stops existing. `upload.py` deletes on
    a finished check and on client disconnect; the earlier "immediately after processing"
    covered only the first, and so overstated the promise for every check that failed,
    was cancelled, or was simply abandoned."""
    notice = RETENTION_NOTICE.lower()
    assert "check finishes" in notice
    assert "tab closes" in notice


def test_demo_mode_body_states_the_resolved_policy():
    body = MODES["demo"].body.lower()
    assert "check finishes" in body
    assert "close this tab" in body


def test_demo_privacy_stripe_states_the_resolved_policy():
    stripe = PRIVACY_STRIPE["demo"].lower()
    assert "check finishes" in stripe
    assert "tab closes" in stripe


def test_no_retention_copy_promises_more_than_the_code_delivers():
    """"Immediately after processing" is the specific overstatement this replaced: nothing
    deletes a manuscript whose check never reached a result. Keep it from coming back."""
    for text in (RETENTION_NOTICE, MODES["demo"].body, PRIVACY_STRIPE["demo"]):
        assert "immediately" not in text.lower()
