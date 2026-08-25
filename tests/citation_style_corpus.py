"""Loader for the per-style regression corpus in fixtures/citation_styles.

Kept out of the test module so that scripts/check_corpus_reproduces.py can read the
corpus the same way the tests do — a checker with its own copy of the loading rules
would eventually disagree with them, which is exactly the class of bug the corpus is
supposed to catch.
"""

from __future__ import annotations

import json
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "fixtures" / "citation_styles"
META_FILE = "meta.json"

# "normalize" is the Markdown cleanup chain, the earliest layer that can lose a whole
# reference; "split" and "section" run on text that is already clean, so a defect in
# cleanup is invisible to them.
LAYERS = ("normalize", "split", "section", "title")


def load_meta() -> dict:
    return json.loads((CORPUS_DIR / META_FILE).read_text(encoding="utf-8"))


def load_styles() -> dict[str, dict]:
    """Every style file, keyed by style key, in filename order."""
    styles = {}
    for path in sorted(CORPUS_DIR.glob("*.json")):
        if path.name == META_FILE:
            continue
        style = json.loads(path.read_text(encoding="utf-8"))
        if style["style"] != path.stem:
            raise ValueError(f"{path.name} declares style {style['style']!r}")
        styles[style["style"]] = style
    return styles


def load_cases() -> list[dict]:
    """All cases across all styles, each tagged with its style key.

    Cases carry their style rather than being grouped by it so that a failure names
    the style in its test id: "apa7/apa-flattened-editor-list" says which style file
    to open, which is the first question anyone asks when this corpus goes red.
    """
    cases = []
    for style_key, style in load_styles().items():
        for case in style["cases"]:
            cases.append({**case, "style": style_key})
    return cases
