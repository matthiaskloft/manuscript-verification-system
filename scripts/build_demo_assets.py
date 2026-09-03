"""Build the bundled demo manuscripts shipped under src/openrefcheck/assets/.

Deliberately separate from scripts/build_synthetic_benchmark.py, which builds the
*test* fixtures under tests/fixtures/synthetic/. The two used to be the same PDFs —
the assets were byte-identical copies of the fixtures — which coupled two things that
want opposite properties:

- A test fixture wants to be big and adversarial. Its 30-entry reference list exists
  to give entry splitting enough material to get wrong, and its entry count is a
  recorded baseline in tests/fixtures/citation_styles/corpus.json: changing it is a
  deliberate decision that has to be argued for.
- A demo wants to be small and fast. Every entry in a demo document becomes a live
  Crossref/OpenAlex lookup on a public deployment, so a 30-entry demo is 30 network
  round-trips before a first-time visitor sees anything.

Keeping them identical meant neither could change without disturbing the other. They
are now independently generated from the same curated entry pool, so a demo can be
resized freely and a fixture baseline can only move when a test says so.

Demo documents are capped at DEMO_ENTRY_LIMIT references. Requires the LaTeX toolchain
described in openrefcheck.synth.latex_builder (pdflatex + biber + biblatex style packages).

Usage:
    python scripts/build_demo_assets.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openrefcheck.synth import corruption_generators as cg
from openrefcheck.synth.entries import CURATED_ENTRIES
from openrefcheck.synth.latex_builder import build_pdf

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "src" / "openrefcheck" / "assets"
MANIFEST_PATH = ASSETS_DIR / "demo_manifest.json"

# Small enough that a demo run is a handful of lookups rather than a benchmark, large
# enough that the reference list still spans a page break and looks like a real one.
# tests/test_demo_assets.py enforces the ceiling so a future resize can't quietly
# turn the demo back into a benchmark.
DEMO_ENTRY_LIMIT = 15


def _entries(broad_field: str, limit: int = DEMO_ENTRY_LIMIT):
    """First `limit` curated entries of a field, in curated order.

    Taking a prefix rather than a sample keeps the demo documents reproducible: the
    same command produces the same PDFs, so a rebuild shows up as a real change or
    not at all.
    """
    return [e for e in CURATED_ENTRIES if e.broad_field == broad_field][:limit]


# Reference list only, with a page break placed inside a single entry's author list.
# The corruption generators can't produce this one: it needs the break at a chosen
# point mid-entry, which is a property of where the text sits on the page, not of the
# bibliography style. Written out here rather than shared with the test fixture of the
# same shape (tests/fixtures/synthetic/corruption_variants/reference_page_break.tex)
# so that neither file constrains the other.
_PAGE_BREAK_TEX = r"""
\documentclass{article}
\usepackage[margin=1in]{geometry}
\usepackage[colorlinks=true,urlcolor=blue]{hyperref}

\begin{document}
\section*{References}

\noindent Ahlgren, P., Jarneving, B., Rousseau, R., Persson, O., Larsen, B.,
Schneider, J. W., Egghe, L., Rousseau, R., Bornmann, L., Daniel, H.-D.,
Waltman, L., Van Eck, N. J., Leydesdorff, L., Bar-Ilan, J., Thelwall, M.,
Sugimoto, C. R., Lariviere, V., Haustein, S., Costas, R., Robinson-Garcia, N.,

\newpage

\noindent Van Leeuwen, T. N., Moed, H. F., Glanzel, W., Schubert, A., Braun, T.,
and Debackere, K. (2023). A synthetic demonstration reference whose author list is
interrupted by a page break. \textit{Journal of Synthetic Demonstrations}, 12(3),
201--218. \href{https://doi.org/10.5555/demo.pagebreak}{doi:10.5555/demo.pagebreak}.

\bigskip

\noindent Fischer, M. and Weber, L. (2022). A second synthetic demonstration
reference that begins after the interrupted one. \textit{Journal of Synthetic
Demonstrations}, 11(1), 44--59.
\href{https://doi.org/10.5555/demo.second}{doi:10.5555/demo.second}.

\end{document}
"""


def _build_page_break_pdf(build_dir: Path, doc_name: str) -> Path:
    from openrefcheck.synth.latex_builder import _run

    tex_path = build_dir / f"{doc_name}.tex"
    tex_path.write_text(_PAGE_BREAK_TEX, encoding="utf-8")
    # No bibliography resource, so no biber pass; two pdflatex passes settle the
    # page break the document exists to demonstrate.
    _run(["pdflatex", "-interaction=nonstopmode", tex_path.name], cwd=build_dir)
    _run(["pdflatex", "-interaction=nonstopmode", tex_path.name], cwd=build_dir)
    return build_dir / f"{doc_name}.pdf"


# (asset name, menu group, label shown in the demo picker, builder)
DEMO_DOCUMENTS = [
    {
        "asset": "demo_social_apa7.pdf",
        "group": "valid",
        "label": "Social & behavioral · APA 7",
        "style": "apa7",
        "broad_field": "social_behavioral",
    },
    {
        "asset": "demo_humanities_chicago.pdf",
        "group": "valid",
        "label": "Humanities & theology · Chicago",
        "style": "chicago-authordate",
        "broad_field": "humanities_theology",
    },
    {
        "asset": "demo_medicine_vancouver.pdf",
        "group": "valid",
        "label": "Medicine & life sciences · Vancouver",
        "style": "vancouver",
        "broad_field": "medicine_life_sciences",
    },
    {
        "asset": "demo_cs_ieee.pdf",
        "group": "valid",
        "label": "Computer science & engineering · IEEE",
        "style": "ieee",
        "broad_field": "cs_engineering",
    },
    {
        "asset": "demo_other_apa7.pdf",
        "group": "valid",
        "label": "Other disciplines · APA 7",
        "style": "apa7",
        "broad_field": "other",
    },
    {
        "asset": "demo_page_break.pdf",
        "group": "corrupted",
        "label": "Page-break reference",
        "style": "plain",
        "broad_field": None,
        "defect": "reference_split_across_page_break",
    },
    {
        "asset": "demo_running_header.pdf",
        "group": "corrupted",
        "label": "Running header",
        "style": "apa7",
        "broad_field": "social_behavioral",
        "defect": "running_header_injection",
    },
    {
        "asset": "demo_two_column.pdf",
        "group": "corrupted",
        "label": "Two-column references",
        "style": "apa7",
        "broad_field": "social_behavioral",
        "defect": "two_column_reflow",
    },
]

_BUILDERS = {
    "running_header_injection": cg.build_running_header_pdf,
    "two_column_reflow": cg.build_two_column_pdf,
}


def _build(spec: dict, build_dir: Path) -> tuple[Path, int]:
    doc_name = spec["asset"].removesuffix(".pdf")
    if spec.get("defect") == "reference_split_across_page_break":
        return _build_page_break_pdf(build_dir, doc_name), 3

    entries = _entries(spec["broad_field"])
    builder = _BUILDERS.get(spec.get("defect"), build_pdf)
    pdf = builder(entries, build_dir, style=spec["style"], doc_name=doc_name)
    return pdf, len(entries)


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "purpose": (
            "Demo manuscripts bundled with the application, generated from the curated "
            "synthetic entry pool in openrefcheck.synth.entries. Not test fixtures: nothing "
            "under tests/ reads these files, and no parser baseline depends on them."
        ),
        "provenance": (
            "Generated by scripts/build_demo_assets.py via LaTeX/biblatex from "
            "project-owned synthetic bibliography entries. No third-party or published "
            "reference list is reproduced here."
        ),
        "entry_limit": DEMO_ENTRY_LIMIT,
        "documents": [],
    }

    with tempfile.TemporaryDirectory(prefix="refcheck-demo-build-") as tmp:
        build_dir = Path(tmp)
        for spec in DEMO_DOCUMENTS:
            print(f"building {spec['asset']} ...")
            pdf, entry_count = _build(spec, build_dir)
            if entry_count > DEMO_ENTRY_LIMIT:
                raise RuntimeError(
                    f"{spec['asset']} has {entry_count} references, over the "
                    f"{DEMO_ENTRY_LIMIT}-reference demo limit"
                )
            # Only the PDF is copied out; the .bib/.tex/.aux/.log stay in the temp
            # build directory so the installed package carries no build residue.
            shutil.copyfile(pdf, ASSETS_DIR / spec["asset"])
            manifest["documents"].append(
                {
                    "asset": spec["asset"],
                    "group": spec["group"],
                    "label": spec["label"],
                    "style": spec["style"],
                    "broad_field": spec["broad_field"],
                    "defect": spec.get("defect"),
                    "entry_count": entry_count,
                }
            )

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
