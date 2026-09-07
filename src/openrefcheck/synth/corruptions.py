"""Catalogue of reference-list defects the synthetic benchmark should cover.

Each entry documents a real failure mode observed either directly in this project's
own GROBID/AnyStyle spikes (see docs/project-plan.md) or well-known from PDF text
extraction generally, plus which pipeline stage it stresses. Implementations are
added incrementally below the catalogue; PLANNED entries are not yet implemented.

Grouped by which stage of the pipeline they stress, since that determines where a
failure would actually show up:
- SPLIT: Tier 0's split_bibliography_block() heuristics (entry boundary detection)
- EXTRACT: GROBID/AnyStyle's per-entry field parsing
- TEXT: PyMuPDF/pdfminer's raw text extraction from the PDF itself
- MERGE: ensemble.py's cross-tier deduplication
- CONTENT: the reference's data is wrong, not the extraction of it - typos,
  transposed digits, mismatched cross-references, and other errors a human author or
  a citation-management tool (Zotero, EndNote, Word) introduces into the reference
  itself. These don't stress this project's extraction tiers so much as the
  downstream verification layer (does the extracted text correspond to a real,
  correctly-cited work) - cataloguing them here regardless since a manuscript-
  verification tool has to detect them eventually, and it's useful to distinguish
  "we misread a correct reference" from "we correctly read an incorrect reference."
"""

from dataclasses import dataclass


@dataclass
class DefectSpec:
    name: str
    stage: str  # "split" | "extract" | "text" | "merge" | "content"
    description: str
    observed_in_this_project: bool
    status: str  # "implemented" | "planned"


DEFECT_CATALOGUE: list[DefectSpec] = [
    DefectSpec(
        name="missing_doi",
        stage="extract",
        description=(
            "Reference has no DOI printed in the text at all (common for books, "
            "software, and older articles) - not itself a bug, but the dominant real "
            "cause of DOI-recall gaps found in the real-PDF benchmark; every "
            "extraction tier must be evaluated with this case present, not just DOI-"
            "complete documents."
        ),
        observed_in_this_project=True,
        status="implemented",  # entries.py already has DOI-less entries (lord1968, rcoreteam2024)
    ),
    DefectSpec(
        name="merged_entries",
        stage="split",
        description=(
            "Two consecutive reference entries run together with no blank line or "
            "hanging-indent break between them (compact single-spaced reference "
            "lists). Directly stresses split_bibliography_block()'s blank-line/line-"
            "start heuristics, which assume each entry starts a new visual block."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.merge_all_entries: collapses 29 -> 1
    ),
    DefectSpec(
        name="mixed_numbering_styles",
        stage="split",
        description=(
            "Same reference list mixes bracket-numbered [12] and plain-dot 12. "
            "markers, or drops numbering markers partway through (common after OCR "
            "or copy-paste from a different source). Tests whether split falls back "
            "gracefully instead of picking one heuristic and silently dropping the "
            "entries that don't match it."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.mixed_numbering: silently swallows entries 2/3 into entry 1
    ),
    DefectSpec(
        name="two_column_reflow",
        stage="text",
        description=(
            "Two-column journal layout where naive top-to-bottom, left-to-right text "
            "extraction interleaves the two columns' reference entries out of order. "
            "This is a PyMuPDF/pdfminer text-order problem, not a parsing-logic "
            "problem, and needs a real two-column PDF (LaTeX \\twocolumn) to "
            "reproduce - can't be simulated by corrupting plain text. Measured: GROBID "
            "scored 1.0 parsing recall on this synthetic document even in two-column "
            "layout - not a problem for this pipeline on this fixture, at least."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.build_two_column_pdf, GROBID-tested
    ),
    DefectSpec(
        name="hyphenated_line_wrap",
        stage="text",
        description=(
            "A word is split across a line break with a trailing hyphen (e.g. "
            "'infor-\\nmation') and the extractor doesn't rejoin it, breaking title-"
            "matching on that word. LaTeX's own hyphenation already produces this "
            "naturally in the compiled PDFs (see e.g. 'Physi-cal Review Letters' in "
            "the APA7 output) - already present as an unintentional case, worth "
            "confirming parsing_match.py's fuzzy matching tolerates it before "
            "treating it as a deliberate corruption."
        ),
        observed_in_this_project=True,
        status="implemented",  # occurs naturally in the compiled PDFs already
    ),
    DefectSpec(
        name="running_header_injection",
        stage="text",
        description=(
            "A running header/footer (journal name, page number) repeats between "
            "reference entries when a multi-page reference list's page texts are "
            "concatenated. Needs a long enough reference list to span multiple pages "
            "to reproduce. Measured: GROBID scored 1.0 parsing recall on this "
            "synthetic document even with a fancyhdr running header/footer on every "
            "page - not a problem for this pipeline on this fixture, at least."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.build_running_header_pdf, GROBID-tested
    ),
    DefectSpec(
        name="organizational_author",
        stage="split",
        description=(
            "Reference has an organizational author (e.g. 'American Educational "
            "Research Association') instead of 'Surname, F.' - breaks Tier 0's "
            "_APA_AUTHOR_START_RE regex, which assumes a personal-name pattern to "
            "detect where a new entry starts. Directly observed in the real Crossref "
            "gold data (see crossref_gold.py unstructured entries)."
        ),
        observed_in_this_project=True,
        status="implemented",  # entries.py's rcoreteam2024 uses a braced organizational author
    ),
    DefectSpec(
        name="doi_url_variants",
        stage="extract",
        description=(
            "DOI printed as a bare string (10.xxxx/yyy), a doi: prefix, or a "
            "resolver URL (https://doi.org/... or http://dx.doi.org/...) - already "
            "handled by normalize_doi(), but worth an explicit corruption variant to "
            "confirm each extraction tier recognizes all forms, not just the one its "
            "own test fixtures happened to use."
        ),
        observed_in_this_project=True,
        # corruption_generators.doi_url_variants + normalize_doi(): found and fixed a
        # real gap - normalize_doi() didn't strip a bare "doi:" prefix (only URL
        # forms), so "doi:10.x/y" and "10.x/y" compared unequal. Fixed in doi_utils.py.
        status="implemented",
    ),
    DefectSpec(
        name="duplicate_reference",
        stage="merge",
        description=(
            "The same work is cited twice (accidental duplication or repeated self-"
            "citation). Doesn't break single-tier extraction, but tests whether "
            "ensemble.py's dedup logic collapses true duplicates without also "
            "collapsing two genuinely different references that happen to share a "
            "similar title (false-merge risk from parsing_match.py's fuzzy "
            "threshold)."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.duplicate_reference_scenario + merge_extracted
    ),
    DefectSpec(
        name="truncated_reference_list",
        stage="text",
        description=(
            "The reference list is cut off partway through (e.g. last page missing), "
            "simulating an incomplete PDF upload. Tests that recall degrades "
            "gracefully and proportionally rather than the pipeline crashing or "
            "reporting a misleadingly high score on the truncated subset."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.truncate_reference_list
    ),
    DefectSpec(
        name="many_authors_et_al",
        stage="split",
        description=(
            "Reference has many authors (8+), stressing whether the author list is "
            "correctly kept as one block rather than being mistaken for several "
            "separate entry starts. Already present in entries.py (vaswani2017, 8 "
            "authors) but not yet corrupted further (e.g. truncated to 'et al.' "
            "form, which real APA7 does for 21+ authors - none of our entries are "
            "long enough to trigger that rule yet)."
        ),
        observed_in_this_project=True,
        status="implemented",  # 8-author entry present; "et al." truncation case still planned
    ),
    DefectSpec(
        name="mixed_citation_styles",
        stage="split",
        description=(
            "A single reference list mixes formatting styles (some APA, some "
            "numbered) - simulates a student thesis assembled by copy-pasting from "
            "multiple sources without normalizing citations, a realistic case given "
            "this tool's use in a university thesis-review context."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.mixed_citation_styles
    ),
    # --- Content-level errors: the reference itself is wrong, not misread ---
    DefectSpec(
        name="typo_in_author_name",
        stage="content",
        description=(
            "A misspelled surname (e.g. 'Kanheman' for 'Kahneman'), the single most "
            "common manual-entry error in student and manually-typed reference lists. "
            "Tests whether identity verification (matching the reference against a "
            "real record) tolerates small edit-distance errors, since an exact-string "
            "lookup would silently fail to find the real work. Measured: title-based "
            "matching is unaffected (the title field itself wasn't touched) - this "
            "shows author-name typos are invisible to this project's current "
            "title/DOI-only matching, not that they're harmless in general."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.typo_in_author_name + score_content_corruption
    ),
    DefectSpec(
        name="transposed_year_or_volume_digits",
        stage="content",
        description=(
            "Two digits swapped in a year or volume number (e.g. 1979 -> 1997), a "
            "common manual-transcription slip. Unlike a typo in a name, this can "
            "silently produce a *different real value* (a valid-looking year that "
            "isn't the actual publication year) rather than an obviously malformed "
            "one, making it harder to flag automatically. Measured: same as author "
            "typos - undetected by current title/DOI-only matching."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.transpose_year_digits
    ),
    DefectSpec(
        name="incorrect_page_range",
        stage="content",
        description=(
            "Wrong page numbers, often copy-pasted from an adjacent reference in the "
            "same list by accident. Doesn't affect title/DOI-based matching, but is a "
            "real correctness defect a full verification pass should catch - worth "
            "cataloguing even though this project's current metrics (score.py, "
            "parsing_match.py) don't check pages at all yet. Measured: confirmed "
            "undetectable by design, since neither metric inspects the pages field."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.swap_page_ranges
    ),
    DefectSpec(
        name="malformed_doi_single_character_typo",
        stage="content",
        description=(
            "A single-character error in an otherwise well-formed DOI (e.g. "
            "10.2307/1914185 -> 10.2307/1914195) - distinct from doi_url_variants "
            "(a formatting difference): this produces a syntactically valid DOI "
            "string that resolves to nothing or to the wrong work, which "
            "normalize_doi() cannot detect since it only reformats, it doesn't "
            "verify. A real verification pass needs an actual resolver lookup to "
            "catch this, not just string normalization. Measured: confirmed - DOI "
            "matching correctly fails (as expected, this is the one case current "
            "matching *should* catch and does), but title matching still succeeds, "
            "meaning the reference is still identifiable by title alone even when "
            "its DOI is silently wrong."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.typo_doi_digit
    ),
    DefectSpec(
        name="author_order_swapped",
        stage="content",
        description=(
            "Authors listed in the wrong order (e.g. a citation-manager import "
            "reversing first/last author), which changes the correct citation-key "
            "convention (author-year styles key off the *first* author) without "
            "necessarily being visually obvious. Measured: undetected by current "
            "title/DOI-only matching (first_author_surname isn't actually compared "
            "by score_parsing - title similarity dominates)."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.swap_author_order
    ),
    DefectSpec(
        name="smart_quotes_and_dash_variants",
        stage="text",
        description=(
            "Word/EndNote/Zotero auto-formatting artifacts: curly quotes (‘ ’ “ "
            "”) instead of straight ASCII quotes, em-dashes or en-dashes instead of "
            "hyphens in page ranges (263–291 vs 263-291), and non-breaking spaces "
            "between author initials. Very common in manually-typed or Word-exported "
            "reference lists (as opposed to the LaTeX-compiled fixtures this project "
            "currently uses, which don't naturally produce this), and can break "
            "regex-based Tier 0 heuristics that assume plain ASCII punctuation. "
            "Measured: no effect on split_bibliography_block()'s entry count on this "
            "text, since the APA-author-start heuristic anchors on the author name's "
            "opening pattern, not on quote/dash characters elsewhere in the entry."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.smart_quotes_and_dashes
    ),
    DefectSpec(
        name="inconsistent_journal_abbreviation",
        stage="content",
        description=(
            "The same journal referred to inconsistently across entries in one "
            "document (e.g. 'J. Pers. Soc. Psychol.' in one reference, 'Journal of "
            "Personality and Social Psychology' in another) - common when a "
            "reference list is assembled from multiple citation-manager exports with "
            "different journal-abbreviation settings. Stresses any future journal-"
            "name-based cross-checking, not the current title/DOI matching."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.abbreviate_journal
    ),
    DefectSpec(
        name="missing_required_field",
        stage="extract",
        description=(
            "A reference is missing a field its own style normally requires (e.g. no "
            "volume/issue for a journal article, no publisher for a book) - common "
            "in hastily assembled student reference lists rather than a PDF-"
            "extraction artifact. Tests that a tier degrades gracefully (partial "
            "match) instead of failing to recognize the entry as a reference at all."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.drop_required_field
    ),
    DefectSpec(
        name="unsorted_reference_list",
        stage="split",
        description=(
            "An author-year-style reference list not in alphabetical order (e.g. a "
            "reference added later without re-sorting the list) - a common real edit "
            "error. Tests whether any heuristic implicitly relies on alphabetical/"
            "numeric ordering as a splitting signal rather than treating each entry "
            "independently. Measured: no effect - split_bibliography_block() doesn't "
            "use ordering as a signal at all, so shuffled entries split identically."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.unsorted_order
    ),
    DefectSpec(
        name="citation_reference_mismatch",
        stage="content",
        description=(
            "A work is cited in-text but missing from the reference list, or listed "
            "in the reference list but never cited in-text - one of the most common "
            "real author errors, and a distinct check from extraction accuracy "
            "entirely (it needs in-text citation extraction, which this project "
            "doesn't build yet). Cataloguing it here as a target for a future "
            "citation-consistency check, not something score.py/parsing_match.py "
            "currently measure."
        ),
        observed_in_this_project=False,
        status="planned",
    ),
    DefectSpec(
        name="inconsistent_et_al_threshold",
        stage="split",
        description=(
            "Some entries abbreviate long author lists with 'et al.' after 3 "
            "authors, others spell out all 20+ authors, inconsistently within the "
            "same reference list - typically from mixing exports of different "
            "citation-manager style settings. Compounds many_authors_et_al by also "
            "varying which convention appears where. Still planned: none of our "
            "curated entries has 21+ authors (APA7's own et-al-truncation threshold), "
            "so there's no real 'full name list' case to contrast against a "
            "truncated one yet - would need a new curated entry with that many "
            "authors to test meaningfully rather than a synthetic string mockup."
        ),
        observed_in_this_project=False,
        status="planned",
    ),
    DefectSpec(
        name="diacritic_corruption",
        stage="text",
        description=(
            "Accented characters in non-English author names (e.g. 'Müller', "
            "'Björklund') get stripped, mis-encoded, or replaced with a placeholder "
            "during OCR or a bad PDF font's ToUnicode mapping (e.g. 'Müller' -> "
            "'Muller' or 'M?ller'), breaking exact-match author verification. "
            "Particularly relevant given this tool's Uni Marburg (German/European) "
            "context, where non-English names are common, not an edge case. Measured: "
            "undetected by current matching (title-only), same caveat as the other "
            "author-field corruptions above."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.corrupt_diacritics
    ),
    DefectSpec(
        name="duplicate_doi_different_works",
        stage="merge",
        description=(
            "Two genuinely different references accidentally share the same (wrong) "
            "DOI, due to a copy-paste error in the original manuscript rather than "
            "an extraction bug. Tests whether ensemble.py's DOI-keyed dedup silently "
            "collapses two distinct citations because they carry an identical but "
            "erroneous identifier - a failure mode the current first-seen-wins merge "
            "logic (ensemble.py) would not detect. Measured: confirmed - "
            "merge_extracted() silently collapses two genuinely different works into "
            "one, keeping only the first-seen title and dropping the other entirely, "
            "exactly the false-merge failure mode this defect describes."
        ),
        observed_in_this_project=True,
        status="implemented",  # corruption_generators.duplicate_doi_different_works_scenario
    ),
    DefectSpec(
        name="incomplete_editor_or_translator_info",
        stage="extract",
        description=(
            "Edited volumes or translated works (common in the humanities_theology "
            "field, e.g. entries.py's Gadamer/Ricoeur/Barth) missing editor or "
            "translator fields that a complete citation should carry. Real "
            "reference lists in the humanities frequently omit these, and it's a "
            "field type (editor/translator) this project's SynthReferenceEntry "
            "doesn't currently model at all. Still planned: implementing this "
            "properly needs an editor/translator field added to SynthReferenceEntry "
            "and bib_writer.py first - a data-model extension, not just a corruption "
            "function, so it's deferred rather than faked with an ad hoc workaround."
        ),
        observed_in_this_project=False,
        status="planned",
    ),
    DefectSpec(
        name="retracted_paper_cited_unflagged",
        stage="content",
        description=(
            "A reference to a paper that has since been retracted, cited without "
            "any indication in the manuscript. Not a parsing defect at all - it "
            "requires cross-referencing against a retraction database (e.g. "
            "Retraction Watch, a planned future integration), which is out of "
            "scope for the extraction "
            "benchmark specifically but is exactly the kind of content-level check "
            "this whole project ultimately exists to do."
        ),
        observed_in_this_project=False,
        status="planned",
    ),
]
