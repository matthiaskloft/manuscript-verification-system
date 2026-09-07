# Parser failure modes

Use the earliest layer that explains the observation. A later symptom does not override earlier evidence.

| Layer | Failure mode | Evidence | Typical repair location |
|---|---|---|---|
| PDF → Markdown | Reading-order or column interleaving | Words exist visually but appear out of order in `pymupdf.md` | Dependency choice/configuration or a narrowly justified preprocessing rule |
| PDF → Markdown | Glyph or encoding loss | Character is already missing or corrupted in `pymupdf.md` | Extraction normalization only when a general Unicode transformation is valid |
| Markdown cleanup | Header, footer, page number, or formatting leakage | Raw Markdown contains decoration that should be removed but normalized text retains it | `extraction/document.py` |
| Section isolation | Missing, premature, or overlong bibliography | `bibliography.md` starts or ends at the wrong location | Heading/stop logic in `extraction/document.py` |
| Entry splitting | Under-splitting or merge | One parsed entry contains two or more complete references | `extraction/tier0.py` or pre-split cleanup |
| Entry splitting | Over-splitting or fragment | One visual reference becomes multiple parsed entries | `extraction/tier0.py` or page/block continuation cleanup |
| Title extraction | Wrong or truncated query title | Entry boundary is correct, but query omits or includes non-title material | `extraction/title.py` |
| Verification | Correct query, poor candidate ranking | Parsed reference and title are sound; returned candidates are inappropriate | `verification/openalex_crossref.py`, only with source-backed matching evidence |
| Verification | Lookup outage/rate limit | `error` is populated or both services fail | No parser change; retry separately |
| Ground truth | Legitimate non-match | Parse/query are sound and services return no adequate record | No parser change; retain for manual review |

## Boundary checks

Use these questions in order:

1. Is the complete citation visible in the PDF?
2. Is the same content present and ordered in `pymupdf.md`?
3. Does it survive normalization and bibliography isolation?
4. Is exactly one parser entry produced for exactly one citation?
5. Is the extracted query the cited work's title rather than authors, venue, or neighboring text?
6. Did the APIs succeed, and do their candidates support or contradict the query?

## Fix quality

A robust fix has a positive discriminator for the affected structure and a negative test for the nearest plausible false positive. Prefer rules based on sequence, punctuation, layout artifacts, section structure, and citation grammar. Reject fixes based on a single document's literal names, titles, journals, or page numbers.

The nearest plausible false positive is usually in a *different citation style*, which
is why it survives review of the document that motivated the fix. Before proposing a
change, state which other style could contain the structure the fix keys on, and check
it in `tests/test_citation_styles.py`. Observed instances:

| Fix keyed on | Same structure, other style |
|---|---|
| Inline `N.` marker of a flattened numbered list | German edition/volume (`(1. Aufl.)`, `Vol. 1. Theoretical models`), German retrieval date (`am 1. Januar`) |
| Inline `Surname, I.` as an entry start | Edited-book chapter editors (`In Smith, A. B., & Jones, C. D. (Eds.)`), publisher location (`Hillsdale, N.J.:`) |
| Entry ends at terminal punctuation | APA DOI-final entry, which closes with no period |
| Parenthesised `(YYYY)` as the year signal | Vancouver/IEEE (`1954;228:1451-5`), `n.d.`, `in press`, German `o. J.` |
| A line beginning `Appendix`/`Received` as a heading | A wrapped title line inside a reference |

When a PDF-only fixture is required, generate it from project-owned synthetic source (`scripts/build_synthetic_benchmark.py`, writing to `tests/fixtures/synthetic/`). Do not derive a fixture by copying a real or competitor reference list.

The demo manuscripts under `src/openrefcheck/assets/` are not fixtures and carry no parser baseline: they are built separately by `scripts/build_demo_assets.py` and kept small because every reference in them becomes a live lookup on the public deployment. Never add a regression test that reads them, and never regenerate the test fixtures to change what the demo shows.
