"""Build synthetic reference-list PDFs and their exact ground-truth manifest.

Unlike tests/fixtures/ground_truth.json (derived from Crossref/OpenAlex, which only
tags a subset of references with a clean title), ground truth here is exact by
construction: every field in the manifest is the same data the .bib/PDF was rendered
from. Because these PDFs are generated, not copyrighted originals, they're safe to
commit directly (see tests/fixtures/synthetic/, not gitignored).

One PDF per (broad_field, style) pairing rather than one big cross-field document per
style: a real manuscript cites within its own field in one consistent style, so pairing
kept per-document is more representative than a 41-entry mixed-field/mixed-discipline
reference list would be. The "other" bucket (entries that don't fit one of the four
target fields, e.g. the lone physics entry) is rendered once in APA7 as a bonus
diversity document, not counted toward the 10-20-per-field target.

Usage:
    python scripts/build_synthetic_benchmark.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openrefcheck.synth.entries import BROAD_FIELDS, CURATED_ENTRIES
from openrefcheck.synth.latex_builder import build_pdf, plan_citations

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "synthetic"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

# Maps each broad field to the citation style that fits it (see latex_builder.STYLE_PREAMBLES).
FIELD_STYLE = {
    "social_behavioral": "apa7",
    "humanities_theology": "chicago-authordate",
    "medicine_life_sciences": "vancouver",
    "cs_engineering": "ieee",
    "other": "apa7",
}


def _entry_ground_truth(entries) -> list[dict]:
    return [
        {
            "key": e.key,
            "entry_type": e.entry_type,
            "authors": [{"given": a.given, "family": a.family} for a in e.authors],
            "year": e.year,
            "title": e.title,
            "doi": e.doi,
            "journal": e.journal,
            "field_of_study": e.field_of_study,
        }
        for e in entries
    ]


def main() -> None:
    manifest = {"documents": []}
    for broad_field in [*BROAD_FIELDS, "other"]:
        style = FIELD_STYLE[broad_field]
        entries = [e for e in CURATED_ENTRIES if e.broad_field == broad_field]
        if not entries:
            continue
        doc_name = f"synthetic_{broad_field}_{style.replace('-', '_')}_clean"
        print(f"compiling {style} PDF for {broad_field} from {len(entries)} entries ...")
        pdf_path = build_pdf(entries, OUTPUT_DIR, style=style, doc_name=doc_name)
        print(f"wrote {pdf_path}")
        manifest["documents"].append(
            {
                "broad_field": broad_field,
                "style": style,
                "pdf": pdf_path.name,
                "entries": _entry_ground_truth(entries),
                # Which keys the body cites, and how - the ground truth for in-text
                # marker recall, exact by construction in the same way the entries are.
                "cited": [
                    {
                        "key": c.key,
                        "section": c.section,
                        "form": c.form,
                        "narrative": c.narrative,
                        "position": c.position,
                        "marker": c.marker,
                    }
                    for c in plan_citations(entries)
                ],
            }
        )

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
