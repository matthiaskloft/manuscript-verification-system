"""Deployment-mode copy for the disclaimer shown in the sidebar and status stripe.

Per docs/pyside-mvp-mockup-spec.md — content depends on where the app is running
(local desktop / hosted demo / Phase B university server).

The demo-mode retention copy is a promise to a visitor, so it has to describe what the
code does rather than an intention. `openrefcheck.webui.pages.upload` deletes a staged
upload when its check finishes, when the browser session ends, and — for anything a
crash left behind — at the next process start. The wording below says exactly those,
and must be re-checked against that module if either changes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModeCopy:
    short: str
    label: str
    title: str
    body: str


MODES: dict[str, ModeCopy] = {
    "local": ModeCopy(
        short="LOCAL",
        label="Local desktop app (Phase A target)",
        title="Processed locally",
        body="This document stays on your device. Only title, author and DOI are sent "
        "to OpenAlex/Crossref for verification.",
    ),
    "demo": ModeCopy(
        short="DEMO",
        label="Hosted demo server (for reviewers)",
        title="⚠ Demo deployment",
        body="Uploaded documents are processed on this server, not on your own device. "
        "Your file is deleted as soon as the check finishes, and when you close this "
        "tab. Don't upload unpublished or confidential work.",
    ),
    "prod": ModeCopy(
        short="PHASE B",
        label="Phase B production server (university)",
        title="Processed on university infrastructure",
        body="This document is processed on the university's server, not sent to any "
        "external service beyond OpenAlex/Crossref. Full text is retained per the "
        "retention policy and deleted accordingly.",
    ),
}

RETENTION_NOTICE = "Retention: files deleted when the check finishes or the tab closes"

PRIVACY_STRIPE: dict[str, str] = {
    "local": "Local processing — document has not left this device. "
    "Outbound: title/author/DOI to OpenAlex, Crossref.",
    "demo": "Demo server — uploads processed server-side, deleted when the check "
    "finishes or the tab closes. Synthetic example available.",
    "prod": "University server — full text retained per retention policy.",
}
