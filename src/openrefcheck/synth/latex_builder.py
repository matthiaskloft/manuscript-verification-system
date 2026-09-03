"""Compile a minimal LaTeX document (a citing body + a chosen citation-style reference
list) into a PDF, using the locally installed TinyTeX toolchain (pdflatex + biber).

Renders through a real typesetting engine rather than hand-rolling each style's
formatting rules ourselves: biblatex-apa/-chicago/-ieee/-vancouver are maintained,
widely-used style packages, so the output reflects actual journal typesetting
(hyphenation, hanging indents, italics, numbering conventions) instead of an
approximation we'd have to keep correcting by hand. Style coverage is chosen to span
the fields relevant to Uni Marburg's faculties: APA7 (psychology/social sciences),
Chicago author-date (humanities/theology), Vancouver (medicine/life sciences), and
IEEE (CS/engineering).

Installed locally via:
    tlmgr install biblatex-chicago biblatex-ieee biblatex-vancouver
(biblatex-apa and natbib were already present in this machine's TinyTeX.)
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from openrefcheck.synth.bib_writer import write_bib_file
from openrefcheck.synth.entries import SynthReferenceEntry

# Only the citation-style package/options differ between styles; the .bib content and
# document body are style-independent, so one template covers all of them.
STYLE_PREAMBLES: dict[str, str] = {
    "apa7": (
        r"\usepackage[style=apa]{biblatex}" "\n"
        r"\DeclareLanguageMapping{american}{american-apa}"
    ),
    "chicago-authordate": r"\usepackage[authordate]{biblatex-chicago}",
    "ieee": r"\usepackage[style=ieee]{biblatex}",
    "vancouver": r"\usepackage[style=vancouver]{biblatex}",
}

_TEX_TEMPLATE = r"""
\documentclass{{article}}
{style_preamble}
\addbibresource{{{bib_name}}}

\title{{{title}}}
\author{{{author}}}
\date{{{year}}}

\begin{{document}}
\maketitle

\begin{{abstract}}
{abstract_text}
\end{{abstract}}

\section{{Introduction}}
{introduction}

\section{{Method}}
{method}

\section{{Results}}
{results}

\section{{Discussion}}
{discussion}

\printbibliography

\end{{document}}
"""

# Real GROBID/AnyStyle need a title page, abstract, and multiple sections to correctly
# segment header/body/back-matter (see docs/project-plan.md, Referenzextraktion) - a
# bare paragraph with no title produced empty TEI output entirely when this was first
# tried, so the body here deliberately mimics that structure rather than being minimal.
#
# Every section opens with its own sentence rather than a shared filler paragraph. The
# shared one was identical four times over, and normalize_markdown_text's running-header
# pass (_drop_repeated_isolated_lines) deleted all four copies - which left these
# documents with 343 characters of body text and no in-text citations to detect in it.
_SECTION_OPENINGS: dict[str, str] = {
    "introduction": (
        "The question taken up here has been approached from several directions, and "
        "the paragraphs below trace the line of work this manuscript builds on rather "
        "than restating each contribution in full."
    ),
    "method": (
        "The procedure follows established practice at every step, so what matters in "
        "this section is which earlier report each decision was taken from."
    ),
    "results": (
        "The pattern observed in these data is reported first and then placed against "
        "the findings it is meant to be read alongside."
    ),
    "discussion": (
        "What remains is to say which of the earlier claims the present data support "
        "and which of them they leave open."
    ),
}

# Citation commands rather than marker text written out by hand: biblatex renders each
# style's real in-text form through the same maintained style packages the bibliographies
# already come from, so the markers the detector has to find were not authored alongside
# it. \textcite produces the narrative form ("Doe (2020)", "Doe [1]"), \parencite the
# parenthetical one ("(Doe, 2020)", "[1]").
#
# Four forms rather than two, because a corpus of bare single-key markers exercises the
# easiest shape there is and leaves the module's central invariant - one record per
# reference, one span per marker - entirely untested. A locator and a two-key group are
# where a real manuscript stops being uniform, and where the styles diverge most: APA
# writes a group as one span with a semicolon, the numeric styles compress consecutive
# numbers into a range.
#
# Several frames per form, cycled, because a sentence that repeats verbatim is a running
# header as far as the cleanup chain can tell - and it canonicalizes digit runs away, so
# in a numbered style two sentences differing only in their marker would look identical.
_FRAMES: dict[str, tuple[str, ...]] = {
    "narrative": (
        r"\textcite{{{keys}}} set out the position this section revisits.",
        r"A closely comparable argument is developed by \textcite{{{keys}}}.",
        r"Working from different material, \textcite{{{keys}}} reached much the same conclusion.",
    ),
    "parenthetical": (
        r"The same effect has been reported elsewhere \parencite{{{keys}}}.",
        r"Earlier evidence points in this direction as well \parencite{{{keys}}}.",
        r"This reading sits comfortably beside the surrounding literature \parencite{{{keys}}}.",
    ),
    "locator": (
        r"The argument is put most directly in a single passage \parencite[p.~14]{{{keys}}}.",
        r"One chapter takes up the question at length \parencite[pp.~204--211]{{{keys}}}.",
        r"The relevant table is reproduced there \parencite[p.~87]{{{keys}}}.",
    ),
    "grouped": (
        r"Two independent reports agree on this point \parencite{{{keys}}}.",
        r"The finding has since been replicated more than once \parencite{{{keys}}}.",
        r"Both of the surveys covering this period say the same \parencite{{{keys}}}.",
    ),
}

# How many references each form's marker names. Cycled in this order, so a document of
# thirty entries carries six of each single-key form and six two-key groups.
_FORM_CYCLE = ("narrative", "parenthetical", "locator", "grouped")
_KEYS_PER_FORM = {"narrative": 1, "parenthetical": 1, "locator": 1, "grouped": 2}

_SECTIONS = tuple(_SECTION_OPENINGS)

_ABSTRACT_TEXT = (
    "This synthetic manuscript exists only to exercise the reference-extraction "
    "pipeline against a document with realistic structure and an exactly known "
    "bibliography, generated from the entries in entries.py."
)

_TITLE = "A Synthetic Manuscript for Reference-Extraction Benchmarking"
_AUTHOR = "Synthetic Author"


@dataclass(frozen=True)
class PlannedCitation:
    """One reference named by one `\\cite`, decided before the document is rendered.

    `position` is 1-based and counts references in citation order, which for the numeric
    styles (IEEE, Vancouver) is also the number biblatex assigns: those styles sort the
    bibliography by first citation, and the plan cites every entry once, in the order the
    .bib lists them. That correspondence is what lets a detected "[7]" be checked against
    a known key rather than only counted.

    `marker` is the index of the `\\cite` this reference is named by, so the two halves
    of a two-key group share it while keeping separate positions. It is the ground truth
    for the invariant the detector is built around - one record per reference, one span
    per marker - which a corpus of single-key citations cannot test at all.
    """

    key: str
    section: str
    form: str
    position: int
    marker: int

    @property
    def narrative(self) -> bool:
        return self.form == "narrative"


def plan_citations(entries: list[SynthReferenceEntry]) -> list[PlannedCitation]:
    """Which entry each section cites, in which form, and grouped with what.

    Pure and deterministic, because both the builder and the manifest writer call it;
    a plan recorded separately from the one rendered would eventually disagree with it,
    and the manifest is the ground truth the recall test is measured against.

    Every entry is cited exactly once. Without `\\nocite{*}` an uncited entry simply
    vanishes from the bibliography, so full coverage is also what keeps these documents'
    reference lists the same ones the extraction corpus already measures - and it is why
    the form cycle advances by whole markers, never leaving a group half-filled.
    """
    plan: list[PlannedCitation] = []
    index = 0
    while index < len(entries):
        form = _FORM_CYCLE[len(plan) % len(_FORM_CYCLE)]
        group = entries[index : index + _KEYS_PER_FORM[form]]
        if len(group) < _KEYS_PER_FORM[form]:
            # Not enough entries left to fill this form's marker. Falling through to a
            # single-key form keeps the "every entry cited exactly once" guarantee for
            # any list length, including the one-entry "other" document.
            form = "parenthetical"
            group = entries[index : index + 1]
        # Spread by position rather than by a fixed chunk size. A ceiling-sized chunk
        # gives the last section whatever is left over, which for 5 to 9 entries is
        # nothing at all, and an empty section is one fewer place a marker can sit next
        # to a heading. Both keys of a group take the first one's section, so the last
        # section can still come up empty for very short lists (1, 2 or 5 entries).
        section = _SECTIONS[min(index * len(_SECTIONS) // len(entries), len(_SECTIONS) - 1)]
        marker = len({c.marker for c in plan})
        plan.extend(
            PlannedCitation(key=entry.key, section=section, form=form, position=index + offset + 1, marker=marker)
            for offset, entry in enumerate(group)
        )
        index += len(group)
    return plan


def _section_bodies(plan: list[PlannedCitation]) -> dict[str, str]:
    """The LaTeX paragraph for each section: its opening sentence, then its citations."""
    bodies = {section: [opening] for section, opening in _SECTION_OPENINGS.items()}
    for marker in dict.fromkeys(cited.marker for cited in plan):
        named = [cited for cited in plan if cited.marker == marker]
        frames = _FRAMES[named[0].form]
        sentences = bodies[named[0].section]
        sentences.append(frames[len(sentences) % len(frames)].format(keys=",".join(c.key for c in named)))
    return {section: " ".join(sentences) for section, sentences in bodies.items()}


def _run(cmd: list[str], cwd: Path) -> None:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(cmd)}\n--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )


def _check_log_for_biblatex_errors(log_path: Path) -> None:
    """pdflatex in -interaction=nonstopmode still exits 0 even when a citation style
    package is missing or fails to load (confirmed empirically: a bad style name
    produces "Package biblatex Error: Style '...' not found" in the log but a normal
    return code) - so _run()'s return-code check alone would silently accept a PDF
    with no actual bibliography in it. Must check the log content too."""
    if not log_path.exists():
        return
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    if "Package biblatex Error" in log_text or "Emergency stop" in log_text:
        raise RuntimeError(f"biblatex error found in {log_path.name} - see file for details")
    # Since the body cites entries by key instead of registering all of them with
    # \nocite{*}, a key that does not resolve costs a bibliography entry rather than a
    # citation marker - silently, and only in the document it happens to be in.
    #
    # The string is biblatex's, checked against a build with a deliberately bad key.
    # "There were undefined references" - the line to reach for by reflex - is classic
    # BibTeX's and never appears in a biblatex log, so a guard written against it passes
    # on exactly the document it was meant to catch.
    if "The following entry could not be found" in log_text:
        raise RuntimeError(f"undefined citation key in {log_path.name} - see file for details")


def build_pdf(
    entries: list[SynthReferenceEntry], build_dir: Path, style: str = "apa7", doc_name: str | None = None
) -> Path:
    """Write a .bib + .tex into build_dir and compile it to a PDF via
    pdflatex -> biber -> pdflatex -> pdflatex (the standard biblatex build cycle:
    biber needs pdflatex's first-pass .bcf, and a second pdflatex pass is needed to
    pick up biber's resolved citations before a final pass settles page numbers)."""
    if style not in STYLE_PREAMBLES:
        raise ValueError(f"unknown style {style!r}, expected one of {sorted(STYLE_PREAMBLES)}")
    doc_name = doc_name or f"synthetic_{style}"

    build_dir.mkdir(parents=True, exist_ok=True)
    bib_path = build_dir / f"{doc_name}.bib"
    tex_path = build_dir / f"{doc_name}.tex"

    write_bib_file(entries, bib_path)
    tex_path.write_text(
        _TEX_TEMPLATE.format(
            style_preamble=STYLE_PREAMBLES[style],
            bib_name=bib_path.name,
            **_section_bodies(plan_citations(entries)),
            abstract_text=_ABSTRACT_TEXT,
            title=_TITLE,
            author=_AUTHOR,
            year="2026",
        ),
        encoding="utf-8",
    )

    _run(["pdflatex", "-interaction=nonstopmode", tex_path.name], cwd=build_dir)
    _run(["biber", doc_name], cwd=build_dir)
    _run(["pdflatex", "-interaction=nonstopmode", tex_path.name], cwd=build_dir)
    _run(["pdflatex", "-interaction=nonstopmode", tex_path.name], cwd=build_dir)
    _check_log_for_biblatex_errors(build_dir / f"{doc_name}.log")

    return build_dir / f"{doc_name}.pdf"
