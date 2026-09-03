"""Which extraction engine will actually run, for display in the GUI/web UI.

Kept separate from document.py's extract_references() so a caller can show "which
engine is active" up front (e.g. on the Upload screen, before a file is even chosen)
without triggering an extraction. Naming: GROBID is the ML-based Tier 1 engine
(docs/project-plan.md); "Anchor" is this project's own Tier 0 regex/heuristic
splitter (tier0.py's own heuristics are literally anchored on line-start patterns —
numbered markers, "Surname, I." starts, etc.).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from openrefcheck.extraction.grobid import grobid_url, is_grobid_available

ANCHOR_ENGINE_NAME = "Built-in parser"
GROBID_ENGINE_NAME = "GROBID"

# Preference values a caller (the Upload screen, extract_references) can pass to
# override the default GROBID-if-reachable-else-Anchor behaviour.
ENGINE_AUTO = "auto"
ENGINE_GROBID = "grobid"
ENGINE_ANCHOR = "anchor"
ENGINE_PREFERENCES = (ENGINE_AUTO, ENGINE_GROBID, ENGINE_ANCHOR)

ENGINE_PREFERENCE_LABELS = {
    ENGINE_AUTO: "Auto (GROBID if reachable)",
    ENGINE_GROBID: "GROBID",
    ENGINE_ANCHOR: "Built-in parser (rule-based)",
}


@dataclass(frozen=True)
class EngineStatus:
    name: str
    detail: str
    reachable: bool  # False only for the fallback case: GROBID configured but not responding


def current_engine_status(
    preference: str = ENGINE_AUTO, *, probe: Callable[[], bool] | None = None
) -> EngineStatus:
    """Best-effort description of which engine a PDF upload will be extracted with.

    DOCX always uses Anchor regardless of GROBID's reachability or preference (see
    document.py) — GROBID has no DOCX support — but this reports the PDF case since
    that's what the Upload screen's status line is about; a DOCX-specific caveat is
    left to the caller to add if it wants one.

    preference lets the user pin the engine instead of the default GROBID-if-
    reachable behaviour (see ENGINE_* constants) — e.g. to force the Anchor
    heuristic splitter for comparison even when GROBID is up, or to make a
    misconfigured GROBID_URL visible as "forced but unreachable" rather than a
    silent fallback.

    `probe` is how reachability is decided, defaulting to one attempt. The Upload screen
    passes `grobid.wait_for_grobid` on its second pass so a deployed GROBID gets the time
    a cold start needs; the parameter exists rather than the waiting being built in
    because most callers of this want an answer now, not in three minutes.
    """
    if preference == ENGINE_ANCHOR:
        return EngineStatus(
            ANCHOR_ENGINE_NAME, "rule-based extraction — selected manually", reachable=True
        )

    reachable = (probe or is_grobid_available)()
    if preference == ENGINE_GROBID:
        if reachable:
            return EngineStatus(GROBID_ENGINE_NAME, f"reachable at {grobid_url()}", reachable=True)
        return EngineStatus(
            ANCHOR_ENGINE_NAME,
            f"GROBID selected but not reachable at {grobid_url()} — falling back",
            reachable=False,
        )

    # ENGINE_AUTO (or any unrecognized value — treat like auto rather than raising)
    if reachable:
        return EngineStatus(GROBID_ENGINE_NAME, f"reachable at {grobid_url()}", reachable=True)
    return EngineStatus(
        ANCHOR_ENGINE_NAME,
        f"rule-based fallback — GROBID not reachable at {grobid_url()}",
        reachable=False,
    )
