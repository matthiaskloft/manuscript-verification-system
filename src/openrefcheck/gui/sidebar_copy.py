"""Sidebar navigation labels + deployment-mode env-var plumbing, framework-agnostic
(shared by the web GUI; formerly embedded in the PySide6 sidebar.py)."""

from __future__ import annotations

import os

from openrefcheck.gui.deployment import MODES, PRIVACY_STRIPE

DEPLOYMENT_MODE_ENV = "OPENREFCHECK_DEPLOYMENT_MODE"

NAV_ITEMS: list[tuple[str, str]] = [
    ("upload", "Upload & check"),
    ("refs", "References"),
    ("review", "Manual review"),
    ("summary", "Summary"),
    ("export", "Report export"),
]


def dev_mode_enabled() -> bool:
    """Whether the deployment-mode switcher is exposed in the UI.

    In a real deployment the mode is fixed per build (the local desktop build only
    ever shows LOCAL copy, the hosted demo build only ever shows DEMO copy, etc.) —
    the switcher is a development aid for previewing all three disclaimer variants,
    not an end-user feature. Set OPENREFCHECK_DEV=1 to show it.
    """
    return os.environ.get("OPENREFCHECK_DEV", "").strip().lower() in {"1", "true", "yes"}


def configured_mode() -> str:
    """The deployment mode this build/run is configured for (OPENREFCHECK_DEPLOYMENT_MODE).

    Unset and set-but-unrecognised are different situations and must not share an answer.

    Unset means nobody configured anything, which is the desktop app: it really does keep
    the document on the device, and `local` is true of it. The web entry point never
    reaches this case — `app_web.main` fixes the variable before serving.

    Set to something this does not recognise means somebody *tried* to configure it and
    got it wrong: an empty value from a templated deploy, `production` for `prod`, a typo.
    That is overwhelmingly a server, and the old behaviour answered `local` — which put
    "This document stays on your device" in front of a visitor whose manuscript was on
    the operator's disk, and, because `webui.main._show_internal_errors` keys off the same
    answer, painted a full traceback onto the page as well. One misspelling did both.

    So a bad value fails closed to `demo`: the mode whose copy is true of every server,
    and which discloses nothing. A deployment that wants `prod` still has to say `prod`.
    """
    raw = os.environ.get(DEPLOYMENT_MODE_ENV)
    if raw is None:
        return "local"
    value = raw.strip().lower()
    if value in MODES:
        return value

    import warnings

    warnings.warn(
        f"{DEPLOYMENT_MODE_ENV}={raw!r} is not one of {sorted(MODES)}; falling back to "
        "'demo'. A misconfigured deployment must not claim local processing.",
        stacklevel=2,
    )
    return "demo"


def privacy_stripe_text(mode: str) -> str:
    return PRIVACY_STRIPE.get(mode, "")
