"""Sidebar navigation labels + deployment-mode env-var plumbing, framework-agnostic
(shared by the web GUI; formerly embedded in the PySide6 sidebar.py)."""

from __future__ import annotations

from openrefcheck.env import env_name, read_env
from openrefcheck.gui.deployment import MODES, PRIVACY_STRIPE

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
    return read_env("DEV").strip().lower() in {"1", "true", "yes"}


def configured_mode() -> str:
    """The deployment mode this build/run is configured for (OPENREFCHECK_DEPLOYMENT_MODE)."""
    raw = read_env("DEPLOYMENT_MODE", "local").strip().lower()
    if raw not in MODES:
        import warnings

        warnings.warn(
            f"{env_name('DEPLOYMENT_MODE')}={raw!r} is not one of {sorted(MODES)}; falling back "
            "to 'local'. A misconfigured deployment could otherwise ship the wrong disclaimer.",
            stacklevel=2,
        )
        return "local"
    return raw


def privacy_stripe_text(mode: str) -> str:
    return PRIVACY_STRIPE.get(mode, "")
