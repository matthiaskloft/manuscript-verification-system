"""Loader for the in-text citation corpus in fixtures/intext_citations.

Kept out of the test module for the same reason `citation_style_corpus` is: anything
else that wants to run the corpus (a benchmark, a checker script) has to read it
through here rather than growing a second copy of the loading rules, which would
eventually disagree with these.
"""

from __future__ import annotations

import json
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "fixtures" / "intext_citations"
META_FILE = "meta.json"

# What a case's expected citation looks like once the omitted fields are filled in.
# Written out here rather than left to each assertion so that "the case didn't mention
# `narrative`" and "the case expects narrative to be false" are the same statement — a
# corpus where an unmentioned field is unchecked is a corpus that silently stops
# covering whatever gets added to the record later.
CITATION_DEFAULTS = {
    "family": None,
    "marker": None,
    "authors": None,
    "year": None,
    "number": None,
    "narrative": False,
}


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

    Cases carry their style so a failure names it in the test id: "german_apa/de-u-a-
    abbreviation" says which file to open, which is the first thing anyone asks when
    this corpus goes red.
    """
    return [
        {**case, "style": style_key}
        for style_key, style in load_styles().items()
        for case in style["cases"]
    ]


def expected_citations(case: dict) -> list[dict]:
    """A case's expected citations with every field present."""
    return [{**CITATION_DEFAULTS, **citation} for citation in case["expect"]["citations"]]
