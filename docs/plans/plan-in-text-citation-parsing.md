# Plan: In-Text Citation Parsing (Citation Context Check)

**Created**: 2026-08-04
**Author**: Claude Code (Sonnet 5)

This is the `docs/project-plan.md` "**Zitationskontext**" / "Citation Context Check"
capability (see [Erweiterungsmodule](../project-plan.md#erweiterungsmodule) and
[Umsetzung, Stufe 2](../project-plan.md#umsetzung)), scoped down to what can ship
without the Phase B server/DSGVO prerequisite that document already gates on.

## Status

| Phase | Status | Date | Notes |
|-------|--------|------|-------|
| Spec | DONE | 2026-08-04 | Scoping discussion resolved persistence and context-depth decisions (see Design Decisions). |
| Plan | DONE | 2026-08-05 | Independent review pass run 2026-08-05 (Claude Code, Fable 5); findings folded back into this doc — see Notes. |
| Phase 1: Structured document artifact & source anchors | DONE | 2026-08-05 | `extraction/document_artifact.py` + `build_document_artifact`. Page-number anchors deferred (see Notes). Reviewed 2026-08-08 by two independent reviewers: span-level provenance was wrong for 0/121 markers and is fixed (segment map, now 121/121); three findings recorded as open, see Notes. |
| Phase 2: Tier-0 marker detection (regex) | DONE | 2026-08-05 | `extraction/intext_signals.py` + `fixtures/intext_citations/` corpus. Two extra files modified (`signals.py`, plus this plan) and one verification step not runnable — see Notes. Reviewed 2026-08-06 by two independent reviewers; all findings fixed or stated as limits. Recall measured 2026-08-06 on citing manuscripts (see Notes): 121/121 references over 93 markers, no false positives, after fixing the numbered-marker locator gap that measurement found. |
| Phase 3: Tier-1 GROBID body-ref extraction | DONE | 2026-08-09 | `parse_grobid_citation_contexts` + `extract_document_via_grobid`, with the explicit TEI `xml:id` → `RawReferenceEntry.index` map. Three departures from the phase's own file list and one open item — see Notes. Reviewed 2026-08-09 by two independent reviewers: the walk missed appendix and abstract citations (6 of 87 markers in GROBID's own sample) and is fixed; six further findings fixed, four recorded as open — see Notes. |
| Phase 4: Matching engine | DONE | 2026-08-09 | `extraction/citation_matching.py` + the `CheckResult` bundle, wired through `run_real_pipeline` → `CheckRunner` → `upload.py`. `document.extract_document` reads a document once for all three outputs. 121/121 Tier-0 citations resolved on the synthetic corpus and no real reference reported uncited. Two departures from the phase's file list. Reviewed 2026-08-09 by two independent reviewers plus an invariant fuzz: seven defects fixed (a page range read as a year, a title-first entry inheriting an author at full confidence, a deleted short surname, a marker anchored inside a year, a partly numbered list orphaning its own entries, an unguarded body read failing whole checks, and the artifact leaking the manuscript through `repr`), eleven surviving mutations closed, two claims in this document corrected, four items recorded as open — see Notes. |
| Phase 5: UI surfacing and report export | DONE | 2026-08-11 | `gui/citation_display.py` + `webui/components/citation_context.py`, read by `references.py`, `manual_review.py` and the exported report. One file created beyond the phase's "none anticipated" (the display layer) and one state added the phase did not list (`CITATIONS_NONE_DETECTED`) — see Notes. First render tests in the project. |
| Review | DONE | 2026-08-15 | Whole-feature review (Claude Code, Fable 5) against `ce560d4`, covering all five phases at once rather than each in turn. Nine findings, every one confirmed by execution before it was reported; all nine closed in #64, and the review's own review (Codex, GPT-5.6) found a behaviour regression in the first fix, closed in the same PR. Three areas were left unexamined for budget — see Notes. |
| Ship | DONE | 2026-08-16 | Deployed to Cloud Run as `refcheck-web-00010-wrt`, image `nicegui:3195606`, serving 100 % of traffic. First request hit a real scale-to-zero GROBID cold start and the status line resolved at 107s — see docs/demo-deployment-decision.md. One deployment item still open there (`OPENALEX_API_KEY`), which is configuration rather than this feature. |

## Spec

### Summary

When a user runs a check, the app should locate in-text citation markers in the
manuscript's body text, match each one to a bibliography entry already produced by
the existing extraction/verification pipeline, and surface two findings reviewers
currently have no way to get: **orphaned citations** (a marker with no matching
bibliography entry — a real authoring error) and **unused references** (a
bibliography entry never cited in the body). This runs entirely inside the existing
per-session, in-memory check. No full text or context passage is persisted beyond
the session or an explicit export; server-side storage remains the separate,
already-gated Phase B step in `project-plan.md` and is not authorized by this plan.

### Requirements

- Detect in-text citation markers for both author-date and numbered citation
  families, in English and German.
- Cross-validate which marker family to expect against the bibliography's own
  `style_profile.py` evidence rather than parsing in-text markers blind.
- Match each detected marker to zero, one, or more bibliography entries
  (`ReferenceResult.n`); an unresolved or ambiguous marker must stay explicitly
  ambiguous — never a guessed match.
- Flag bibliography entries with zero in-text matches as unused.
- Flag in-text markers with zero bibliography matches as orphaned.
- Reuse `signals.py`'s shared year/no-date vocabulary (`YEAR`, `YEAR_PAREN_RE`,
  `NO_DATE_RE`) for in-text year matching instead of redefining it a third time —
  see that module's own docstring on why two independent definitions of the same
  concept is how this project's past reference-matching bugs happened.
- Keep raw surrounding text (snippet or paragraph) session-scoped only: never
  written to disk, a database, or a log/error report. This introduces no *new*
  external transmission beyond whatever the configured extraction backend
  (local or remote GROBID) already receives today for bibliography extraction —
  see Constraints; "never leaves the device" is not an accurate claim when
  `GROBID_URL` points at a remote deployment, and this plan doesn't change that.
- Preserve each bibliography entry's GROBID TEI `xml:id` through to its final
  `ReferenceResult.n` (or expose an explicit id→n mapping) — `RawReferenceEntry`'s
  current positional `index` does not coincide with a body `<ref target="#bXX">`'s
  target today (see Constraints), so this cannot be assumed.
- Hide raw context-passage text in the session UI by default; show it only after
  a reviewer explicitly enables a "show citation context" setting. Structured
  match status (reference number, confidence, orphaned/unused flags) stays
  visible regardless of that setting.
- Run citation detection and matching automatically as part of the existing check
  pipeline (the same pass as reference extraction/verification) — no separate
  manual trigger and no per-run opt-in for the matching step itself.
- Default report/export view shows structured match status only; raw passage text
  is opt-in per export, off by default and independent of the in-session setting
  above.
- Extend the extraction pipeline to expose body text with stable position/source-anchor
  information; `extract_references`'s existing bibliography-only return must keep
  working unchanged for current callers.
- Must not change reference-checking behavior when this feature is absent or its
  detection fails.
- Must produce usable (if lower-recall) matches with GROBID entirely unavailable,
  on both PDF and DOCX — Tier 0 is a real fallback, not a token one.

### Design Decisions

| Decision | Options | Chosen | Rationale |
|----------|---------|--------|-----------|
| Persistence scope | Phase B durable server storage now; storage-agnostic core; Phase A session-scoped only | Phase A session-scoped only | Resolved in scoping discussion: ships without the DSGVO/DPO/DSFA sign-off `project-plan.md` calls a prerequisite for Phase B; matches the precedent already set by [plan-statistical-reporting-consistency.md](plan-statistical-reporting-consistency.md)'s own session-scoped-first decision. |
| Context-passage visibility & depth | Visible by default at snippet/paragraph depth; hidden by default until explicitly enabled | Hidden by default even in-session — a reviewer must enable a "show citation context" setting; once enabled, snippet by default with full paragraph on expand | Resolved 2026-08-04, tightened from the original choice: structured match status is visible automatically, but the actual quoted passage is the part that's optional — gated one level stronger than first planned (in-session visibility, not just export). Still session-only regardless: the project plan's Stufe-2 privacy risk is about durable storage, not transient in-session display. |
| Context-visibility reset scope | Reset on every new upload; persist for the session | Reset on every new upload | Resolved 2026-08-04: matches how most of `AppState` already behaves — a new upload clears prior results — so a reviewer starts each new manuscript from the same hidden-by-default state as their first check, rather than risking an accidental carry-over exposure. |
| Data model | Extend `ReferenceResult`; new parallel type | New `CitationMatch` type referencing `ReferenceResult.n` | `plan-statistical-reporting-consistency.md` already established that the existing result classes are reference-specific and a new module "should not be forced into `ReferenceResult`" — the same reasoning applies here. |
| Source-anchor infrastructure | Citation-specific one-off; shared structured-document-artifact | Shared — this plan builds it first; `plan-statistical-reporting-consistency.md` adopts/extends it when that (currently unstarted) work begins | Resolved 2026-08-04: both plans independently need the same missing prerequisite — position-tracked body text (`extract_full_text` currently returns a flat string with no coordinate mapping at all) — and this is the active plan, so it becomes the reference implementation rather than a separately-scheduled task. |
| Tier 1 extraction path | New custom service; extend GROBID's existing response | Extend GROBID's `processFulltextDocument` response | GROBID already returns inline `<ref type="bibr" target="#bXX">` markers in `<body>`, linked by id to `<biblStruct xml:id="bXX">` — verified directly against GROBID's own test-fixture TEI output, not just prose docs (see Permitted Sources; the official docs pages turned out not to cover this at all). `parse_grobid_tei` currently walks only `<biblStruct>` and discards `<body>` entirely, even though the app already POSTs to `processFulltextDocument` today. |
| GROBID parse structure | Extend `parse_grobid_tei` directly; fully independent function; shared internal parse helper | Shared internal parse (`_parse_tei_root`), two public functions | Resolved 2026-08-04: one parse pass serves both `parse_grobid_tei` and a new `parse_grobid_citation_contexts`; the 2 existing call sites (one production, in `extraction/grobid.py`; one in the benchmark ensemble) and 3 existing bibliography-only tests stay untouched, and it fits the automatic-pipeline decision below since bibliography and citation data are now needed together on every check. |
| Tier 0 fallback | Regex-only fallback, required | Required, not optional | DOCX has no GROBID path at all (existing constraint), and GROBID may be unavailable/disabled for PDFs too — same reasoning as the existing Tier 0/Tier 1 reference-extraction split. |
| Matching threshold | Reuse `parsing_match.py`'s 0.85; benchmark separately; tunable constant, decide later | Benchmark a separate threshold before implementation | Resolved 2026-08-04: a common surname plus a common year collides far more easily than a full title string, so the 0.85 title-matching threshold isn't assumed to transfer. Requires Phase 2's synthetic fixtures to exist first. |
| Grouped citation representation | One `CitationMatch` per grouped occurrence (multi-reference); one per individual reference; vary by tier | One `CitationMatch` per individual reference, sharing one source position | Resolved 2026-08-04: keeps "cited N times" counts and unused/orphaned flags correct without special-casing groups downstream. GROBID's Tier 1 output already splits grouped citations into separate `<ref>` tags (see Constraints), so this shape matches Tier 1 natively; Tier 0's regex path is the one that has to actively split a detected group into multiple records. |
| Style detection | Standalone in-text classifier | Reuse/extend `style_profile.py`'s evidence-count approach, cross-validated against the bibliography's own style evidence | Consistent with this codebase's existing "evidence, not verdict" philosophy; avoids a second style pass that can disagree with the first. |
| GROBID target-identity preservation | Assume `RawReferenceEntry.index` order coincides with TEI target ids; explicitly map TEI `xml:id` → final `ReferenceResult.n` | Explicitly map TEI `xml:id` → `RawReferenceEntry.index` → `ReferenceResult.n`, with tests for non-sequential and missing/unmatched ids | Resolved 2026-08-05, per review: nothing today guarantees a body `<ref target="#bXX">`'s id coincides with the sequential position `extract_references_via_grobid` currently assigns. Must be built and tested explicitly, not assumed. |
| Pipeline output contract | Bare `list[ReferenceResult]` return value (current); explicit result bundle | New result bundle (`references`, `citation_matches`, the document artifact, `citation_run_status`) replacing the bare list `run_real_pipeline` returns today | Resolved 2026-08-05, per review: `run_real_pipeline` today returns only `list[ReferenceResult]`; `CheckRunner.on_finished` and `webui/pages/upload.py`'s handler forward exactly that into `state.results`. Nothing carries citation matches, the document artifact, or a citation-run status through that channel today — required to satisfy this plan's own Success Criteria distinguishing "no citations found" from "search failed/didn't run." |
| Activation | Always-on; opt-in per run, off by default | Detection/matching always-on; raw context-passage visibility gated separately (see above) | Resolved 2026-08-04: neither original reason for gating the whole feature held up — Tier 1 adds no new data recipient, and the structured `CitationMatch` record carries no sensitive text by itself. The opt-in boundary moved to exactly where the sensitive content lives instead of sitting in front of the whole feature. |
| Detection/matching trigger | Eager, inside the existing check pipeline; separate on-demand action after the check finishes | Eager, inside the existing check pipeline (same pass as extraction/verification) | Resolved 2026-08-04: the cost asymmetry is in artifact-building (GROBID's response is already fully fetched in one call), not in matching itself, which is cheap in-memory computation regardless of timing. Running it automatically mirrors how reference verification already runs automatically today, and avoids inventing a new "recheck"-style action this app doesn't currently have (checked directly against [check_runner.py](../../src/refcheck/webui/check_runner.py) — no such mechanism exists yet). |

### Scope

#### In Scope

- In-text marker detection, author-date and numbered families, English and German.
- Cross-validating marker-family choice against existing bibliography `StyleProfile` evidence.
- Extending GROBID Tier-1 parsing to read the `<body>` inline `<ref type="bibr">`
  elements already present in the TEI response the app already fetches.
- A Tier-0 regex fallback (DOCX, or GROBID unavailable/off), reusing `signals.py`.
- A shared structured-document-artifact / source-anchor layer over body text,
  coordinated with `plan-statistical-reporting-consistency.md` rather than duplicated.
- A matching engine (marker → bibliography entry, explicit ambiguous/unlocated
  state, no guessing), modeled on `parsing_match.py`'s fuzzy-matching pattern.
- A new session-scoped `CitationMatch` record type referencing `ReferenceResult.n`.
- UI surfacing: unused-reference / orphaned-citation flags, and a per-reference
  "cited N times in this manuscript" figure worded to avoid colliding with the
  existing OpenAlex-derived `ReferenceResult.citations` field.
- Snippet-default / expand-to-paragraph context viewer, session-only.
- A report-export toggle for including raw passage text, off by default.
- Synthetic per-style test fixtures extending the `citation_style_corpus.py` convention.

#### Out of Scope

- Any server-side or cross-session storage of full text or context passages — the
  project's own Phase B "Zitationskontext" stage, unchanged and still gated behind
  its DSGVO/DPO/DSFA prerequisite. This plan does not authorize or assume that
  sign-off.
- Claim verification (whether a citation actually supports the claim it's attached
  to) — project-plan.md's separate, higher-risk Phase B Stufe 3 module.
- Footnote/endnote citation styles (e.g. Chicago notes-bibliography), where the
  citation is a full note rather than a short marker — a different parsing problem.
- Fully solving superscript-only Vancouver numerals in phase one — tracked as a
  known coverage gap (see Open Questions), not silently promised.
- Inspecting MetaCheck's or scite Reference Check's internals, source, or fixtures
  — both are named overlapping competitors under this repo's clean-room policy.
- Batch or cross-manuscript indexing.

### Architecture Overview

This entire flow is wired into the existing check pipeline
(`webui/check_runner.py`'s `CheckRunner` → `gui/real_pipeline.run_real_pipeline`)
and runs automatically in the same pass as today's reference
extraction/verification — there is no separate trigger and no per-run opt-in for
detection/matching itself (see Design Decisions).

```text
extract_full_text(path)                                   (existing, document.py)
  ├─ bibliography slice → find_bibliography_section        (existing, unchanged)
  │     → split_bibliography_block → RawReferenceEntry[]   (existing, unchanged)
  └─ body slice (NEW) → structured document artifact
        with per-span source anchors                       (new, shared with the
                                                              statistical-reporting-
                                                              consistency plan)
              └─ marker detection (runs automatically, same pipeline pass)
                    ├─ Tier 1: GROBID <body> inline
                    │   <ref type="bibr" target="#bXX">     (new — data already
                    │   (if GROBID available)                arrives on the wire;
                    │                                        parse_grobid_tei just
                    │                                        never reads <body>)
                    └─ Tier 0: regex over signals.py
                        vocabulary (fallback / DOCX)
                          └─ matching engine
                              → CitationMatch[]
                                (marker ⇄ ReferenceResult.n,
                                 confidence, status,
                                 session-scoped anchor)
                                    ├─ webui/state.py: AppState (new fields:
                                    │     citation_matches, show_citation_context)
                                    ├─ webui/pages/references.py,
                                    │   webui/pages/manual_review.py (surfacing —
                                    │   status always visible; raw passage only
                                    │   when show_citation_context is enabled)
                                    └─ gui/report_builder.py / report_data.py
                                        (opt-in passage export, independent toggle)
```

The raw passage text and the structured match are different objects with different
lifetimes and different default visibility. The structured `CitationMatch` (marker
text, resolved `n`, confidence, status, position) is cheap, small, computed and
shown automatically, and safe to include in an export by default. The raw
snippet/paragraph text it points to is looked up on demand from the in-memory
document artifact, is never copied into `CitationMatch` itself, and is hidden from
the session UI entirely unless `AppState.show_citation_context` is explicitly
enabled — so there's exactly one place raw passage text can render from, and it's
off until a reviewer turns it on.

### Constraints

- `extract_references` (document.py) currently discards everything except the
  bibliography slice — `full_text` is a local variable never returned. This plan
  requires body text to survive, without changing the existing bibliography-only
  contract current callers rely on.
- GROBID already receives the entire PDF today for bibliography extraction via
  `processFulltextDocument`. Reusing that same response's `<body>` markup for
  citation matching introduces no new data recipient or transmission. Only the
  Tier 0 fallback needs to work with zero external calls — same as today.
- DOCX has no GROBID path at all (pre-existing, unrelated to this plan) — Tier 0
  must be a genuinely usable fallback, not a token one.
- GROBID splits some grouped citations into multiple adjacent `<ref>` tags with
  different targets (observed for "(Jonas 1966, 1968, 1979)"-shaped text per its
  public issue tracker). This happens to match the chosen one-`CitationMatch`-
  per-reference data model natively for Tier 1; Tier 0's regex path is what
  actually has to implement the split, since it detects a grouped marker as one
  span.
- `extraction/grobid.py`'s `extract_references_via_grobid` currently discards
  `ExtractedReference.index` (the real TEI `xml:id`, e.g. `"b16"`) and reassigns
  `RawReferenceEntry.index` by `enumerate(parsed, start=1)` — confirmed by reading
  the current implementation, not a hypothetical. A body citation's
  `target="#b16"` cannot be resolved to the right `ReferenceResult.n` through the
  current production adapter without first fixing this (see Design Decisions,
  GROBID target-identity preservation).
- Bare superscript Vancouver numerals frequently don't survive PDF-to-text
  extraction as distinguishable from surrounding body text at all. Resolved as a
  documented coverage gap that folds into "not detected" (lower recall, never a
  false positive) — no dedicated warning state planned for the initial release.
- Raw context passages must never appear in a log, error message, or crash report
  — the same handling standard `plan-parser-feedback-pipeline.md` sets for source
  PDFs.
- Must not be forced into `ReferenceResult` (see Design Decisions).
- Clean-room policy ([AGENTS.md](../../AGENTS.md)) applies: MetaCheck and scite
  Reference Check are named overlapping third-party implementations; this module
  must come from public standards/literature/this repo's own code only.

### Success Criteria

- Reference-checking output is byte-identical when citation detection/matching
  fails or its inputs are unavailable. Note there is no user-facing disable
  toggle (see Design Decisions, Activation), so the regression test for this
  criterion exercises the detection-failure / feature-absent path, not a
  settings flag.
- Every displayed match shows the marker text, resolved reference number (or an
  explicit ambiguous/unlocated state), confidence, and which tier (GROBID vs.
  regex) produced it.
- "No citations found for this reference" and "citation search did not run/failed"
  are visibly distinct states, never conflated.
- No raw passage text appears in the default export unless a user explicitly opts
  a specific passage in.
- Raw passage text never renders anywhere in the session UI until a reviewer
  explicitly enables the context-visibility setting; structured match status is
  unaffected by that setting.
- Nothing this feature produces outlives the session unless explicitly exported.
- Works, at reduced recall, with GROBID entirely absent, on both PDF and DOCX.

### Permitted Sources and Provenance

- This project's own [clean-room-development-policy.md](../clean-room-development-policy.md),
  [AGENTS.md](../../AGENTS.md), [project-plan.md](../project-plan.md), and current
  source code.
- GROBID Documentation, [*Grobid-service*](https://grobid.readthedocs.io/en/latest/Grobid-service/)
  (fetched directly; confirms `processFulltextDocument` returns body + bibliographical
  section together, but does not itself detail inline-citation markup).
- GROBID Documentation, [*TEI encoding of results*](https://grobid.readthedocs.io/en/latest/TEI-encoding-of-results/)
  and [*Bibliographical references* (training)](https://grobid.readthedocs.io/en/latest/training/Bibliographical-references/)
  — both fetched directly; **neither actually documents inline-citation markup**
  (the first covers TEI customization/schema tooling, the second covers annotating
  a reference in isolation, not linking it to body text). Recorded here so a later
  implementer doesn't waste time looking there again.
- GROBID's own test fixture,
  [`grobid-core/src/test/resources/xslt/sample2.tei.fulltext.xml`](https://github.com/kermitt2/grobid/blob/master/grobid-core/src/test/resources/xslt/sample2.tei.fulltext.xml)
  — fetched directly; the actual verified source for the `<ref type="bibr"
  coords="..." target="#bXX">` structure, including confirmed grouped-citation
  splitting into separate adjacent `<ref>` elements (e.g. "[40, 11, 48]" as three
  separate `target`s). Worth reusing directly as a Phase 3 test fixture.
- The [kermitt2/grobid issue tracker](https://github.com/kermitt2/grobid/issues) —
  a real bug report independently showing the same `target="#bXX"` pattern and the
  same grouped-citation-splitting behavior on a different document, corroborating
  the test fixture rather than resting on one sample alone.
- [grobid-client-python](https://github.com/grobidOrg/grobid-client-python) — public
  reference for how downstream tooling consumes GROBID's in-text citation
  offsets/targets.
- Lo, K. et al. (2020). [*S2ORC: The Semantic Scholar Open Research Corpus*](https://arxiv.org/pdf/1911.02782)
  — public reference for GROBID-based citation-linking accuracy figures.

Contributor exposure declaration: Claude Code (Sonnet 5) reviewed the GROBID public
documentation page above directly, and public web-search results describing
GROBID's TEI `<ref type="bibr">` output structure, to verify the Tier 1 approach
before recommending it. It did not inspect MetaCheck's or scite Reference Check's
source, internals, prompts, or non-public material.

### Open Questions

None remaining as of 2026-08-04 — all prior items resolved into Design Decisions
above, and the GROBID TEI structure verified directly against a primary source
(see Permitted Sources and Provenance).

## Implementation Plan

### Phase 1: Structured document artifact & source anchors

**Files to create:**
- `src/refcheck/extraction/document_artifact.py`
- `tests/test_document_artifact.py`

**Files to modify:**
- `src/refcheck/extraction/document.py` — retain body text alongside the existing
  bibliography-only extraction path, without changing `extract_references`'s
  current return type for existing callers.

**Steps:**
1. Define a `DocumentArtifact` (or similarly named) type carrying normalized body
   text plus per-span position/source-anchor information.
2. Change the internals of `extract_full_text`/`extract_references` so body text
   is retained rather than discarded once `find_bibliography_section` slices out
   the bibliography.
3. Add a source-anchor lookup: given a text span, resolve a stable position later
   consumers can use.
4. Shape the artifact with `plan-statistical-reporting-consistency.md`'s stated
   needs in mind (per-paragraph source spans, original-to-normalized mapping)
   even though this plan builds and ships it first, so that plan can adopt it
   later instead of building a divergent one.

**Depends on:** None — foundational.

### Phase 2: Tier-0 marker detection (regex)

**Files to create:**
- `src/refcheck/extraction/intext_signals.py`
- `tests/test_intext_signals.py`
- `tests/fixtures/intext_citations/*.json` + a loader mirroring
  `tests/citation_style_corpus.py`

**Files to modify:**
- None (new, pure module).

**Steps:**
1. Define marker regexes for author-date and numbered families, English and
   German, importing `YEAR`/`YEAR_PAREN_RE`/`NO_DATE_RE` from `signals.py` rather
   than redefining them.
2. Define exclusion heuristics for the known collision cases: parenthetical
   statistics, figure/table/equation cross-references, footnote markers.
3. Build synthetic per-style fixtures mirroring the existing corpus convention.
4. Cross-check marker-family choice against `compute_style_profile`'s bibliography
   evidence before committing to a parse strategy for a given document.

**Depends on:** Phase 1 (needs body text + spans to detect markers against).

### Phase 3: Tier-1 GROBID body-ref extraction

**Files to create:**
- `tests/test_grobid_citation_context.py`

**Files to modify:**
- `src/refcheck/benchmark/grobid_client.py` — parse `<body>` inline
  `<ref type="bibr">` elements alongside the existing `<biblStruct>` walk.
  (Production TEI parsing living under `benchmark/` is a pre-existing layering
  quirk — `extraction/grobid.py` already wraps this module — which this phase
  extends rather than introduces; relocating it is out of scope here.)
- `src/refcheck/extraction/grobid.py` — surface citation-context results alongside
  the existing `RawReferenceEntry` output, and stop discarding each entry's TEI
  `xml:id` when building `RawReferenceEntry` (see Design Decisions, GROBID
  target-identity preservation).

**Steps:**
1. Reuse GROBID's own `sample2.tei.fulltext.xml` test fixture (see Permitted
   Sources) as a starting point for this module's own tests — its `<ref
   type="bibr" target="#bXX">` structure, including grouped-citation splitting, is
   already verified directly against that primary source.
2. Factor `parse_grobid_tei`'s `ET.fromstring` call out into a private
   `_parse_tei_root(tei_xml)` helper it calls internally, with no change to its
   own signature or behavior.
3. Add `parse_grobid_citation_contexts(root)`, built on the same shared root, to
   extract inline refs with their target id and surrounding text — one
   `CitationMatch` per resolved reference (GROBID's own grouped-citation split
   already produces this shape natively; see Constraints).
4. Build an explicit TEI `xml:id` → `RawReferenceEntry.index` map in
   `extract_references_via_grobid` instead of relying on `enumerate` order to
   coincide with citation targets; add tests for non-sequential ids and a target
   with no matching bibliography id (must resolve to the matching engine's
   unlocated/ambiguous state, not a wrong or crashing lookup).
5. Fall back cleanly to Tier 0 on `GrobidUnavailableError` or zero results,
   consistent with the existing fallback pattern in `document.py`.

**Depends on:** Phase 1, Phase 2 (Tier 0 is what this tier falls back to).

### Phase 4: Matching engine

**Files to create:**
- `src/refcheck/extraction/citation_matching.py`
- `tests/test_citation_matching.py`

**Files to modify:**
- `src/refcheck/gui/real_pipeline.py` — invoke detection/matching automatically in
  the same pass as extraction/verification, and return the new result bundle
  below instead of a bare `list[ReferenceResult]` (see Design Decisions, Pipeline
  output contract).
- `src/refcheck/webui/check_runner.py` — change `CheckRunner.__init__`'s
  `on_finished` type from `Callable[[list[ReferenceResult]], None]` to accept the
  new result bundle, and forward it unchanged from `_run_real`.
- `src/refcheck/webui/pages/upload.py` — its `on_finished` handler (the one that
  currently does `state.results = results` and cleans up the uploaded file)
  unpacks the bundle into `state.results`, `state.citation_matches`, the
  document-artifact field, and a citation-run-status field.
- `tests/test_real_pipeline.py` — all 11 existing call sites consume
  `run_real_pipeline`'s bare-list return and break when it becomes a bundle;
  they must be updated in the same change, and the byte-identical regression
  test (see Success Criteria) compares the bundle's `references` field against
  today's output.

**Steps:**
1. Build fuzzy author-surname/year matching (numbered styles match by number/position
   instead), modeled on `parsing_match.py`'s normalize/similarity algorithm — not
   its 0.85 threshold value, which is benchmarked separately (see Design Decisions).
2. Represent each match as marker ⇄ `ReferenceResult.n` with confidence and an
   explicit ambiguous/unlocated state — never a guess. A detected grouped citation
   (e.g. "(Smith, 2020; Jones, 2019)") expands into one `CitationMatch` per
   resolved reference, all sharing the same source position.
3. Derive unused-reference and orphaned-citation flags from the same pass.
4. Benchmark matching thresholds against the Phase 2 synthetic fixtures — this is
   the threshold's actual source of truth, not an inherited constant.
5. Define a result-bundle type (e.g. `references`, `citation_matches`, the
   document artifact, and `citation_run_status` — one of "ok" / "not_run" /
   "failed", satisfying the Success Criteria's "no citations found" vs.
   "search failed/didn't run" distinction) and change `run_real_pipeline` to
   return it.
6. Wire the bundle through `CheckRunner` to `webui/pages/upload.py`'s
   `on_finished` unchanged — note that handler calls `_cleanup_upload` on the
   source file immediately, so the bundle must already carry everything this
   feature needs by the time it arrives; nothing can be fetched from the
   original file afterward.

**Depends on:** Phase 2 and/or Phase 3 (needs detected markers), the existing
verification pipeline's `ReferenceResult` list.

### Phase 5: UI surfacing and report export

**Files to create:**
- None anticipated; a new context-viewer component may be needed depending on
  `webui/components/` conventions discovered during implementation.

**Files to modify:**
- `src/refcheck/webui/state.py` — add session-scoped `citation_matches` and
  `show_citation_context` (bool, default `False`) fields to `AppState`.
- `src/refcheck/webui/pages/references.py`, `src/refcheck/webui/pages/manual_review.py`
  — surface unused/orphaned flags and the "cited N times in this manuscript" figure
  unconditionally; gate the context viewer behind `show_citation_context`.
- `src/refcheck/gui/report_builder.py`, `src/refcheck/gui/report_data.py` — opt-in
  passage export, independent of `show_citation_context`.

**Steps:**
1. Add the per-reference "cited N times in this manuscript" display, worded to
   avoid colliding with the existing OpenAlex-derived `citations` field — visible
   by default, since it's structured status, not raw text.
2. Add unused-reference / orphaned-citation flags to the relevant screens —
   visible by default, same reasoning.
3. Add the `show_citation_context` setting to `AppState`, off by default and reset
   to `False` on every new upload (consistent with how `AppState` already clears
   other per-check fields), with a visible control for a reviewer to enable it.
4. Add the snippet-default / expand-to-paragraph context viewer itself,
   session-only, rendering nothing unless `show_citation_context` is enabled.
5. Add an `export_included`-style opt-in toggle for including raw passage text in
   the exported report, off by default and independent of `show_citation_context`.

**Depends on:** Phase 4.

## Verification & Validation

- **Automated:** unit tests per detection regex against the synthetic fixture
  corpus (mirroring `citation_style_corpus.py`'s per-style/per-case convention);
  matching-engine tests for ambiguous, unlocated, and grouped-citation cases;
  source-anchor round-trip tests; GROBID body-ref parsing tests against recorded
  TEI fixtures; a regression test proving existing reference-checking output is
  byte-identical when citation detection/matching fails or its inputs are
  unavailable (the feature has no disable toggle — see Design Decisions,
  Activation — so the test exercises the failure/absence path).
- **Manual:** run against the real stress-test manuscripts already used for the
  bibliography pipeline to qualitatively check marker detection recall/precision;
  verify no raw passage text appears in an exported report by default; verify
  nothing survives process exit that wasn't explicitly exported.
- **Operational:** confirm the Tier-0-only (no GROBID) path works standalone;
  confirm the DOCX path (always Tier 0) works.

## Dependencies

- Phase 1's structured-document-artifact work — this plan builds it first;
  `plan-statistical-reporting-consistency.md` is expected to adopt it later
  rather than duplicating it.
- The existing `ReferenceResult` / verification pipeline output as the match target.
- GROBID's `processFulltextDocument` response (already fetched today) for Tier 1 —
  no new external dependency.
- `signals.py`'s shared year/date vocabulary.
- `style_profile.py`'s evidence-count output for cross-validation.

## Notes

- As of 2026-08-04, every Design Decision and Open Question from the original
  spec has been resolved through follow-up discussion and direct source
  verification (see the "Resolved 2026-08-04" entries throughout). The
  independent review pass ran 2026-08-05 and its findings are folded into this
  document; Phase 1 can begin.
- This plan targets Phase-A session-scoped behavior only. The project's own Phase B
  "Zitationskontext" (server-side full-text storage with a retention/deletion
  concept) remains explicitly out of scope and gated behind the DSGVO/DPO sign-off
  `project-plan.md` already calls a prerequisite; this plan doesn't authorize or
  assume that sign-off.
- Consider linking `project-plan.md`'s "Zitationskontext" bullet
  ([Umsetzung](../project-plan.md#umsetzung), item 4) to this document once it's
  reviewed, so the roadmap and this plan don't drift apart — not done here since it
  wasn't asked for and touches a shared roadmap doc.
- Phase 1 shipped two known limitations rather than silently absorbing them, both
  pinned by tests in `tests/test_document_artifact.py`:
  - **No page numbers yet.** `SourceAnchor`/`Paragraph` carry a `source_line` index
    into the original pre-normalization text, which is the original-to-normalized
    mapping both plans asked for, but not the reviewer-facing "page 7" locator
    `plan-statistical-reporting-consistency.md` ultimately wants. Getting there needs
    pymupdf4llm's `page_chunks=True`, whose concatenated output is not guaranteed
    byte-identical to the single-string `to_markdown()` the bibliography pipeline is
    tuned against — so it is its own change with its own regression check, not a
    rider on the change that introduced the layer. The types take a `page` field
    without their existing fields moving.
  - **Paragraph boundaries are approximate.** `body_text` is the output of
    `document.py`'s existing normalization chain, which merges a blank-line-separated
    pair whenever the preceding line doesn't end like a finished reference — correct
    for a bibliography split across a column break, but over body text it also joins a
    section heading to the prose beneath it. Detection and matching are unaffected
    (they work on offsets into intact text); a consumer treating `Paragraph` as
    document structure is. Normalizing body text differently was the alternative and
    was rejected: a second definition of "normalized text" is exactly the divergence
    `signals.py` exists to prevent.
- Phase 1's independent review pass ran 2026-08-08 (two reviewers, Claude Opus 5),
  the one the status table had been carrying as outstanding since 2026-08-05. The
  offset arithmetic came through clean — a 20,000-case fuzz over `from_lines`,
  `paragraph_at`, `anchor_for` and `snippet` found no violation of the `[start, end)`
  discipline at any boundary, and `extract_references`'s "unchanged for existing
  callers" promise was verified by running `d6cebaf^`'s module beside HEAD's over all
  16 PDF/DOCX fixtures. What both reviewers found independently was provenance:
  - **`source_line` pointed at the wrong raw line for 0 of 121 detected markers** —
    every one resolved to its *section heading*. Not the paragraph coarseness above,
    which was known and is real: one level below it. `_merge_mid_entry_paragraph_breaks`
    folds a heading into the prose beneath it and `SourceLine` could hold only one
    origin, so every character past a merge point claimed a raw line it did not come
    from. Fixed by giving `SourceLine` a `segments` list — one origin per contiguous
    run — which `concat_tag` accumulates at the merge sites, `_normalize_tagged_line`
    rebases through Markdown stripping, and `from_lines` lifts into `body_text`
    coordinates for `anchor_for` to resolve. Now 121 of 121. `SourceAnchor` keeps the
    paragraph-level answer as `paragraph_source_line`.
    The existing round-trip test could not catch this: it asserts a paragraph *starts
    with* its raw line, which a merge preserves by construction.
    `test_every_detected_marker_resolves_to_the_raw_line_it_is_printed_on` checks the
    marker against the raw line instead, and is the assertion that was missing.
    This also reaches the page-number limitation above: a page derived from the old
    index would have been the page the *section* started on.
  - **`_drop_repeated_isolated_lines` deleted real body text** — fixed in a second
    commit. Two isolated lines whose digit runs canonicalize alike were enough
    (`_MIN_REPEATS_TO_TREAT_AS_RUNNING_LINE` is 2), so identical table notes under two
    tables and two figure captions differing only in their number were both dropped;
    four ordinary paragraphs, two of them a repeated methods sentence, normalized to
    `""`. It failed toward a false "unused reference" — the error class this feature
    exists to report. Raising the count was not available (an existing test pins a
    genuine two-page footer being dropped), so the discriminator is shape: a running
    header is a label, and a label is not a sentence. A line with terminal punctuation
    and at least `_MIN_PROSE_WORDS` words is exempt, and is excluded from the candidate
    set entirely so it cannot count toward another line's repeats either.
    Two residuals are accepted and pinned by tests rather than hidden: a short
    numbered label (`Analysis 1`) has no terminal punctuation and still goes, and a
    footer that does read like a sentence now survives into the reference list where it
    may become one spurious entry — a visible row, against silently deleted text.
    Reference extraction is byte-identical across all 16 fixtures; the only body-text
    changes are in `corrupt_running_header.pdf` and `corrupt_two_column.pdf`, which
    still carry the pre-#52 repeated filler and now keep the paragraphs that were being
    deleted.
  - Still open, deliberately not folded into either change:
    ~~**A span straddling two paragraphs** anchors to the first
    and its `snippet` then excludes the marker it explains; reachable through the
    shipped detector on a grouped parenthetical split at a block boundary, and nothing
    asserts `snippet(a)` contains `body_text[a.start:a.end]`.~~ **Closed 2026-08-13** —
    see the entry at the end of these notes. ~~**`build_document_artifact`
    re-parses the PDF** rather than sharing `extract_full_text`'s extraction, which
    Phase 4 pays on every check once detection is unconditional.~~ **Closed by Phase 4
    itself**, which this list was never updated to say — see the Phase 4 note below
    ("Phase 1's `build_document_artifact` re-parses the PDF is gone"). `_extract` reads the
    source once and passes the text to `_artifact_from`; `build_document_artifact` survives
    as the standalone entry point and has no callers in `src/` left. Re-verified 2026-08-13
    by counting real `pymupdf4llm.to_markdown` invocations: **1 per extraction** on all
    three paths (`extract_document` under Tier 0 and Tier 1, and `extract_references`).
    Pinned by `test_the_pdf_is_parsed_once`, confirmed non-vacuous by reintroducing the
    second parse and watching it fail.
- Phase 2 departed from its own file list in one place and could not run one of its
  verification steps:
  - **`signals.py` was modified after all** (the phase said "Files to modify: None").
    `NO_DATE_RE` wraps its vocabulary in the parentheses a *bibliography* writes the
    date in; an in-text marker writes the same words bare, inside the citation's own
    parentheses ("(Doe, n.d.)"). The vocabulary was split out as `NO_DATE` and
    `NO_DATE_RE` rebuilt from it — no behaviour change, pinned by a test asserting the
    compiled pattern and flags are unchanged. The alternative was restating the
    no-date forms in `intext_signals.py`, i.e. the third independent definition of a
    shared concept that `signals.py` exists to prevent and that this plan's own
    Requirements forbid.
  - **The imports differ from the ones the phase named.** Step 1 listed `YEAR`,
    `YEAR_PAREN_RE` and `NO_DATE_RE`; the module imports `YEAR`, `NO_DATE` and
    `BRACKET_NUMBER_RE`. Same reason in both directions: the two `_RE` forms carry the
    bibliography's parentheses, and the numbered branch needs the bracket-number shape
    the notes-list exclusion is written against.
  - **The manual verification step has no material to run on.** Every manuscript in
    the repo — `tests/fixtures/synthetic/*.pdf` and the demo assets alike — is a
    bibliography fixture with a 343-character skeleton body ("Abstract … 1
    Introduction … 4 Discussion") and no in-text citations at all. Detection over them
    correctly returns nothing, which confirms no false positives on real extracted
    text but measures no recall. The corpus in `tests/fixtures/intext_citations/` is
    therefore the only evidence Phase 2 has, and it is synthetic text written
    alongside the detector, so it cannot independently falsify it. **Resolved by the
    next bullet on 2026-08-06** — the manuscripts now cite, and the verification step is
    a test rather than a manual one.
- **Done 2026-08-06 (deferred by decision on 2026-08-05): synthetic manuscripts that
  actually cite their references.** Run after Phase 2's review pass rather than inside
  it, because it regenerates committed fixture PDFs. What it found:
  - **Tier 0 detects 121 of 121 rendered markers across the five documents, and detects
    nothing else.** Both directions are asserted as equalities in
    `tests/test_intext_citation_recall.py`, not as thresholds. For IEEE and Vancouver
    the check is per-reference, not just per-marker: those styles number the
    bibliography by first citation and the plan cites every entry once in `.bib` order,
    so detected marker *n* is checked against manifest entry *n* — and the ordering that
    rests on is itself measured against the rendered bibliography, not assumed.
  - The 121 references are named by 93 markers, because the plan cycles four citation
    forms — narrative, parenthetical, page locator, and a two-key group. The group is
    what exercises the module's central invariant, one record per reference and one span
    per marker; a corpus of single-key citations cannot test it at all.
  - **The locator form found a real Tier-0 recall gap, now fixed.** A numbered marker
    carries its locator inside the brackets ("[3, p. 14]", "[15, Sec. 3]"), where the
    author-date family puts it inside the parentheses. The whole span failed the
    digits-and-separators group test, so *every* numbered citation given a page number
    went undetected — 7 of 30 in each numeric document. `_numeric_citations` now cuts the
    span at the locator, with three corpus cases in `ieee.json` including the counterpart
    that keeps the allowance honest ("[p. 14]" alone is not a marker).
  - The builder's undefined-key guard was checking for "There were undefined references",
    which is classic BibTeX's line and never appears in a biblatex log — so the only
    safety net for dropping `\nocite{*}` passed on exactly the document it was meant to
    catch. Verified against a build with a deliberately bad key; the string is
    "The following entry could not be found", and `pdflatex` still exits 0.
  - The `entry_count` baselines the deferral was about did not move — the concern was
    real but the boundaries were unaffected, and the whole suite passed unchanged.
  - **A style may drop a surname particle from the in-text form while keeping it in the
    bibliography.** Chicago renders `de Beauvoir` as "Beauvoir (2011)". The exclusions
    corpus already pins the opposite direction (a German narrative marker keeps its
    "von", because the detector reports the author run as written), so Phase 4's matcher
    has to tolerate the particle being present on either side and absent on the other.
  - **A style may also reorder the references inside a grouped marker.** The plan writes
    `\parencite{milgram1963,festinger1957}` and APA renders "(Festinger, 1957; Milgram,
    1963)". Which references a marker names is ground truth; the order it names them in
    is not, so Phase 4 cannot treat the detector's within-group order as citation order.
  - **`expected_families` narrows only two of the four bibliographies, and Chicago is not
    one of them.** A Chicago author-date bibliography yields *zero* author-date evidence:
    its years are bare ("Kuhn, Thomas S. 1962.") and none of the three counters the
    function consults — parenthesised years, comma-years, JSS author lines — matches that.
    All five of its counters are zero, so it takes the "no evidence either way" branch,
    which resolves upward to both families and happens to be the same branch as "evidence
    of both". Detection is exact there regardless, because the extra family finds nothing
    to detect. `bare_year_density` would separate it (1.39 against Vancouver's 1.07) but
    is not consulted, and that gap is small enough that using it is a real Phase 2
    decision rather than an oversight. Recorded, with the measured evidence pinned in
    `test_the_style_evidence_each_bibliography_offers_is_the_one_recorded`, rather than
    silently fixed.
  - The demo assets under `src/refcheck/assets/` were regenerated from the same builder,
    so the bundled demos now contain in-text citations for Phase 5 to surface.
  What was established while scoping it, and held:
  - The cause was one line. `synth/latex_builder.py`'s template ended with
    `\nocite{*}` — every reference registered with biblatex and none cited. It is now
    `\textcite`/`\parencite` calls inside the section prose, which biblatex renders in
    each style's real in-text form (APA "(Lord & Novick, 1968)", Chicago "(Kuhn 1962)",
    IEEE and Vancouver "[1]" — both bracketed, not the parenthesised "(1)" scoping
    expected of Vancouver) through the same maintained style packages the bibliographies
    already come from, rather than through marker text written by hand alongside the
    detector that has to find it. Dropping `\nocite{*}` means an uncited entry now leaves
    the bibliography entirely, so `plan_citations` covers every key and the builder fails
    on "There were undefined references".
  - The toolchain was present: TinyTeX with `pdflatex` and `biber` (TeX Live 2025).
  - The cited prose had to differ per section, and does — each section opens with its own
    sentence. The shared filler paragraph was in the PDF four times identically and
    `_drop_repeated_isolated_lines` (the running-header pass) deleted all four, which is
    the whole reason `body_text` was 343 characters; it is now 2.9–3.1k. That pass drops
    repeated isolated lines generally, not just here, and now has its own test
    (`test_repeated_paragraphs_are_dropped_from_body_text`) alongside a floor on the
    fixtures' body-text length, since a shared paragraph would otherwise pass every
    recall assertion by making both counts zero.
  - The point was the measurement, not the fixtures. The manifest's new `cited` array
    records which key each section cites, in which form, at which position.
- Phase 2 gates one pattern on the style cross-validation rather than running it
  unconditionally: a parenthesised bare numeral, "(1)". It is detected only when
  `expected_families` narrows to the numbered family alone — the bibliography is
  numbered and shows no author-date evidence. Even then a display equation's number is
  excluded, which is the collision that survives every cue-word check. The exclusion
  cannot be "alone at the end of its line": extraction wraps lines, so a real marker
  ends its line too, and the discriminator is what precedes it on that line — several
  words of prose ending in a word, versus a formula or nothing.
- Phase 2's review pass (2026-08-05, two independent reviewers) found four false-positive
  families and one denial-of-service shape, all fixed in the same PR: parenthesised year
  ranges read as narrative markers ("The Second World War (1939-1945)"), German
  determiner-plus-noun phrases (German capitalises every noun, so the structural test
  that keeps English prose out does not apply), seasons alongside months, and
  integer-bounded ranges in brackets. The denial-of-service shape was an author run whose
  particle list spelled "van der" both as one alternative and as two, which made a failing
  run exponential. What is *not* fixed, and is stated as a limit instead: an in-sentence
  enumeration in a numbered document ("...: (1) that x, (2) that y") — the colon before
  the first item is a usable cue, the later items are not distinguishable from markers.
- Superscript-only Vancouver numerals are a known, plausibly-unsolvable-in-phase-one
  coverage gap; document it rather than silently mismatching.
- Both existing plans in this repo (`docs/plans/plan-parser-feedback-pipeline.md`
  and `docs/plans/plan-statistical-reporting-consistency.md`)
  went through an independent review pass before their Implementation Plan
  sections were treated as final. This plan received that review pass on
  2026-08-05 (see Status table).
- Phase 3 departed from its own plan in three places, all recorded here rather than
  quietly:
  - **`parse_tei_root` is public, not the private `_parse_tei_root` step 2 named, and
    there is a third public function.** Step 3 specified
    `parse_grobid_citation_contexts(root)` — a root, not a string — which means a caller
    wanting both halves of one response needs a public way to *get* a root, and a
    root-taking bibliography walk to spend it on. So `parse_grobid_tei(tei_xml)` keeps
    its exact signature and behaviour for the two callers that only want references
    (`benchmark/ensemble.py` and the benchmark tests) and is now one line over
    `parse_grobid_references(root)`. The alternative — two string-taking public
    functions — parses the same XML twice on every check, which is the cost the
    "shared internal parse" decision existed to avoid.
  - **The TEI test material is authored here, not GROBID's `sample2.tei.fulltext.xml`.**
    Step 1 proposed reusing that file. The structure it was wanted for is already
    verified against a primary source and recorded in Constraints, and TEI is a public
    standard, so writing the fixtures locally gets the same coverage without vendoring a
    third-party file (and its attribution obligation) into this repo — and lets each
    fixture isolate one behaviour, which a real document cannot.
  - **Nothing is wired into `document.py` or the pipeline yet.** `extract_references`
    is untouched: `extract_references_via_grobid` is now the bibliography-only view of
    `extract_document_via_grobid`, same output, same fallback, one GROBID call. Carrying
    citations any further needs the result bundle that is Phase 4's step 5, so Tier 1
    ships unreferenced in the same way Tier 0 did.
- **Open, and Phase 4 has to answer it: a Tier-1 marker has no manuscript coordinates.**
  `CitationContext.start`/`end` index into the containing TEI paragraph, because TEI is
  GROBID's own rendering of the document and shares no offsets with a `DocumentArtifact`
  built from pymupdf4llm's. So Tier 1 knows exactly *which reference* a marker cites —
  the thing Tier 0 has to guess — and cannot by itself say *where on the page* it sits,
  which is the reverse of Tier 0's position. Matching one to the other needs a locator
  that finds the TEI marker text in the artifact's body text; until that exists, the two
  tiers are not interchangeable for the reviewer-facing locator, and the invariant that
  is asserted (`paragraph_text[start:end] == marker_text`) is deliberately the weaker one
  it can actually keep.
- Phase 3's independent review pass ran 2026-08-09 (two reviewers, Claude Opus 5). The
  offset arithmetic held: `paragraph_text[start:end] == marker_text` survived two
  independent fuzzers (30,000 and 4,000 generated TEI paragraphs, with `None` text,
  nested inline elements, whitespace-only refs and tails, `\r\n`, NBSP, `\u2028`,
  adjacent markers) with no violation, and `parse_grobid_tei`/`extract_references_via_grobid`
  were shown identical to `origin/master` by running both modules side by side over 17
  crafted inputs and 6 TEI documents — same values, same exception types and messages,
  same one HTTP call. Both reviewers converged on coverage instead, and disagreed about
  its extent, so it was re-measured directly against GROBID's own committed fulltext
  sample and its serializer source:
  - **The walk missed 6 of 87 markers.** `<text><body>` is not where all of a manuscript's
    prose lives. `<back><div type="annex">` — appendix text, which cites like any other
    section — is outside it, and so is a structured abstract, which GROBID serializes
    through the same code path as the body (`TEIFormatter.toTEITextPiece`) and therefore
    marks up with real `<ref type="bibr">`, under `teiHeader/profileDesc/abstract`. A
    reference cited only in an appendix or only in an abstract would have been reported
    as unused — a false accusation in the check this feature exists to add.
    Fixed by inverting the filter: `_citation_paragraphs` walks the whole document and
    excludes only `<listBibl>`/`<biblStruct>`, which is the docstring's actual argument
    (the reference list citing itself) rather than a proxy for it. This is robust to
    GROBID putting prose somewhere new, because a paragraph only ever produces records
    for the bibr refs it contains — a `<p>` in the publication statement yields nothing.
    Now 87 of 87 on the same sample, no bibliography contamination, invariant intact.
    Descent also stops at a `<p>`, which closes the nested-`<p>` double count one
    reviewer raised as reachable-in-principle.
  - **The same reviewer's footnote and figure-caption claims were judged unsupported. The
    caption one was correct, and the judgement was wrong.** Recorded because the way it
    was got wrong is the reusable part: the claim was checked against one sample document
    (which has two captions, neither citing) and against a second reviewer's reading of
    `Figure.java`, and both agreed. Neither is evidence of absence. `Figure.toTEI` appends
    citation markers straight onto the `<figDesc>` element — and renames that element to
    `<p>` inside a wrapping `<div>` when sentence segmentation is on, so which element
    holds a caption's marker is a property of the *deployment's config*, not of the
    document, and no single sample could have settled it. Found by a review on the
    implementing pull request after the pass had closed. The footnote half was correct: `TEIFormatter.toTEINote` wraps note
    content in a `<p>` and emits it inside `<body>` ("notes are still in the body").
  - **The walk no longer depends on knowing where markers go.** The caption miss was the
    third of its kind in one phase, all the same shape: an allow-list of places prose was
    expected to be, found incomplete only when someone went looking. `_citation_contexts`
    now claims a marker for the nearest element that holds it *directly* whenever no
    listed container applies, so an unanticipated tag yields its markers instead of
    swallowing them — which also covers the `<div>`-with-no-paragraph case one reviewer
    found in `TEIFormatter` and could not measure. The container list survives for passage
    quality, not coverage: a marker inside `<hi>` is found either way, but without the list
    the passage shown to a reviewer would be the `<hi>` rather than the sentence. The two
    properties are pinned by separate tests, because a mutation showed the coverage
    assertions alone left the list free to delete.
  - **Two mutations survived the original suite** — the pass's most useful finding, since
    both were assertions that looked adequate. Dropping the leading-whitespace offset
    adjustment left all 23 tests green: every fixture placed its marker after prose ending
    in a space, where the adjustment is zero by construction, so the branch was never
    reached. It needs a marker after "(" or a dash. Dropping the paragraph `rstrip` was
    unpinned outright. Both are now caught, along with 13 others.
  - **Four assertions could pass vacuously**, three being `== []` and one an `all()` over
    a possibly-empty list — which was the only guard on the `type="bibr"` filter. Each
    now carries a positive control in the same document.
  - **The TEI `xml:id` was still being discarded**, which the phase's own file list said
    to stop doing — the map was a local variable, so a caller holding only a reference
    list could not resolve a `<ref target="#bXX">` handed to it separately. Now
    `RawReferenceEntry.source_id`. Note this makes two entries that used to compare equal
    unequal when one carries an id; nothing in the app compares them structurally.
  - Two smaller ones: a `RecursionError` from the paragraph walk escaped the
    `GrobidUnavailableError` contract `document.py`'s fallback depends on (caught now,
    turning a crash back into a fallback), and the `rstrip` comment asserted something
    false — a recorded span *can* run one character past the trimmed length, and it is
    the caller's `strip` that makes it tight, not the property the comment claimed.
  - **`paragraph_text` is now out of both dataclasses' generated reprs.** The plan
    requires a raw passage never reach a log, an error message or a crash report, and a
    repr is how one gets there without anyone deciding to put it there — a failing
    assertion or a traceback holding one of these prints the passage. No path in `src/`
    does so today; this closes it by construction. Phase 1's `Paragraph` and
    `SourceAnchor` still take the weaker approach and are worth revisiting.
  - Recorded, not fixed: **Tier 1's grouped markers do not share one source position**,
    which the Design Decisions table says they should — GROBID emits one element per
    target with distinct adjacent spans, so Phase 4 merges them rather than Phase 3
    faking a shared span; the second element's `marker_text` also carries the separator
    (", [3]"), which matters if it is ever displayed raw. **Phase 3 step 5's zero-results
    and `ENGINE_ANCHOR` fallback is deferred with the wiring, not done** — "nothing is
    wired into `document.py`" is about call sites, and the fallback lives at the call
    site `extract_references` already has; going through both entry points today costs
    two GROBID calls, so Phase 4 re-plumbs `document.py` rather than adding a call.
- Phase 4 departed from its own file list in two places:
  - **`intext_signals.py` gained a public `parse_marker`**, which the phase did not name.
    Tier 1 needs it: a marker GROBID could not link arrives as text with no surroundings,
    and every exclusion in `detect_citations` reads a marker's surroundings. A bare "[3]"
    on its own is line-initial with nothing above it — the shape of a notes-list entry —
    so the detector correctly refuses it, and without a parse that skips the adjudication
    a reference cited only through unlinked markers is reported as unused. The alternative
    was letting Tier 1 call an orphan whatever GROBID failed to resolve, which is the false
    accusation this feature exists not to make.
  - **`document.py` gained `extract_document`**, and the pipeline calls it instead of
    `extract_references`. Step 5's bundle needs the body, the citations and the references
    from one read. What that saves is one PDF parse on the Tier 0 path, and nothing on the
    GROBID path, where reading the body is new work the pipeline did not previously do at
    all — `build_document_artifact` had no production caller before this phase. (The first
    version of this bullet claimed two GROBID calls and two PDF parses were being saved.
    Wrong on both halves: Phase 3 had already made `extract_references_via_grobid` a view
    onto a single call, and the pipeline never built an artifact. Found in the review pass;
    the measurement is in the third bullet below.) `extract_references` is unchanged in behaviour and still the
    cheaper path (it reads no body, and on the GROBID path never touches pymupdf4llm),
    which `tests/test_extract_document.py` checks by running the two side by side over
    eight fixtures rather than by arguing from shared code. This closes both of the items
    the earlier phases left for Phase 4: Phase 3 step 5's deferred fallback now lives at
    the call site, and Phase 1's "`build_document_artifact` re-parses the PDF" is gone.
- **The threshold benchmark's result is that the corpus cannot choose the threshold.**
  Step 4 called the synthetic fixtures the threshold's source of truth. They are not: the
  same 121 citations resolve identically at every threshold from 0.0 to 1.0, and only an
  impossible value above 1.0 changes anything.

  The first version of this bullet reported a comfortable margin instead — true-pair
  scores of 1.000 against a wrong-pair ceiling of 0.333 — and concluded that 0.80 "sits
  clear of the observed collision ceiling". The review pass showed that reading was wrong
  in a way worth recording, because it is the same mistake as Phase 3's `figDesc`: a
  number was taken to mean something it did not measure. The 0.333 is measured *after*
  `_year_agreement` has already dropped every pairing whose years disagree, so it
  describes the year gate. On names alone the corpus collides at 1.000 — it carries two
  Ricoeur entries with identical surnames and different years, and Barth against Barthes
  at 0.833, both at or above the threshold. The claim that the corpus contains "no two
  references with similar surnames" was false of the very document the finding came from.

  What the corpus actually establishes is that the year carries the discrimination here
  and names contribute none of it. So the threshold rests on an argument about what the
  corpus lacks — damaged names, pairs separable only by name — and the argument now lives
  with the constant. Both ceilings are pinned separately
  (`test_the_year_gate_is_what_separates_this_corpus_and_not_the_names`), and the
  flatness is checked across the whole range rather than a plausible band.
- **Measuring found a real matching failure that no hand-written fixture would have.**
  Chicago prints a rule instead of repeating an author across consecutive entries, and the
  rule is all that survives PDF extraction: the entry reads ". 1970. Freud and
  Philosophy...". Read on its own it matches nothing, so "(Ricoeur 1970; White 1973)" was
  reported as an orphaned citation — a manuscript accused of citing a work its own
  bibliography lists. A repeated-author entry now inherits the names above it, gated on the
  entry opening with the rule itself. The first version of that gate was "starts with
  something other than a letter" and this document claimed it made a wrong inheritance
  impossible; the review pass disproved that in one line — a title-first entry opens with a
  quotation mark, so an anonymous work listed under an author-first entry inherited that
  author, at full confidence.
- **The four match statuses are not a match/no-match boolean with extra steps.** ORPHANED
  is the finding (the marker names a reference the document does not carry); UNRESOLVED is
  its opposite (the marker could not be read at all, so it is evidence of nothing);
  AMBIGUOUS is a shortlist for the reviewer. An ambiguous marker's candidates keep those
  references off the unused list and count toward no citation total — the plan's "never a
  guess" cuts both ways, and a finding needs evidence as much as a match does.
- Recorded rather than fixed, and all four are visible in the code:
  - **A grouped Tier-1 marker still does not share one source position**, which the Design
    Decisions table asks for. It gets something better: GROBID emits one element per
    reference, each located separately in the manuscript, so a reviewer is sent to the
    member being reported rather than to the group. The counts and flags the decision was
    protecting are correct either way, since both tiers produce one record per reference.
  - **Tier 1's positions are a text search, not a mapping.** TEI shares no coordinates with
    a `DocumentArtifact`, so a marker is located by finding its own characters in the body
    text, forward from the last marker found. A marker that extraction rendered differently
    is reported unlocated with its reference still resolved — locating and resolving are
    separate questions and the failure of one must not suppress the other.
  - **A numbered marker resolves through the bibliography's printed numbers when it has
    them and through position otherwise.** Position alone assumes extraction dropped
    nothing, which is what a hard-to-parse reference list violates; GROBID's reconstructed
    entries carry no printed marker at all, so both paths are needed.
  - **The secondary surnames of a numbered-style entry are noisy.** Those styles have no
    date to cut the author region at, so it runs into the title and the split keeps a few
    title words as names. They are used only to break a tie between equally-scoring
    candidates, never to score, so the cost is bounded — and numbered markers do not
    consult names at all.
- **Nothing is surfaced in the UI yet.** `AppState` carries the matches, the run status and
  the artifact, and no screen reads them: rendering them, and the context viewer's
  visibility gate, are Phase 5. The bundle deliberately arrives complete, because
  `upload.py`'s handler deletes the uploaded file the moment it does and nothing can be
  fetched from the source afterwards.
- Phase 4's independent review pass ran 2026-08-09 (two reviewers, Claude Opus 5, one on
  the matching logic and one on the contracts and the claims), plus an invariant fuzz run
  alongside them. What held: 30,000 generated documents produced no record that
  contradicts itself — `reference_n` set exactly when the status is RESOLVED, `candidates`
  non-empty exactly when AMBIGUOUS, every anchor in bounds and covering its marker, no
  reference both cited and unused, and no crash. The byte-identical promise was verified
  against `b601a90` over 56 comparisons (8 PDFs, 2 DOCX, 4 failure cases × 4 engine
  settings) with no difference in any field, exception type or message. Both reviewers
  then found defects the suite did not, and the pass produced more real findings than any
  before it:
  - **A page range was read as an entry's publication year**, and vetoed the match. "…
    Journal of Tests, 12(3), 1990-1995." yields 1990, `_year_agreement` rejects a marker
    citing 2020, and the entry is reported both as an orphaned citation *and* as never
    cited — two false findings from one page range, in a shape continuous pagination
    produces constantly. Only a year read from where a date belongs may now contradict a
    marker; one scraped from an entry's tail can corroborate but not reject, and a year
    inside a numeric range is never a date. `_entry_years`' old docstring claimed the
    fallback was "a superset … [that] never rejects a real pairing", which was exactly
    backwards: a non-empty wrong set is a veto.
  - **A title-first entry inherited its neighbour's author, and resolved at confidence
    1.0.** The repeated-author gate was "starts with something other than a letter", and an
    anonymous work or an editorial opens with a quotation mark. This document had asserted
    the wrong-inheritance case was impossible. The gate now reads the rule itself.
  - **A short all-caps surname was deleted outright.** The rule that strips "Doll R"'s
    run-together initials cannot tell them from a two-letter surname, so "WU, Q." and
    "NG, K." — an ordinary house style — left the entry with no author at all, again
    producing an orphaned citation and an uncited reference together. The capitals rule may
    no longer be the one that empties a chunk.
  - **A bare-digit Tier 1 marker anchored inside a year.** A superscript numbering style
    gives GROBID a marker whose whole text is "1", and "1" occurs inside "2019": the
    reviewer-facing position landed four words from the marker it claimed to be. The
    locator now requires an occurrence not glued to a word or a number, and reports
    unlocated rather than wrong when there is none. A wrong position is the one thing a
    reviewer cannot check without re-reading the page.
  - **A partly numbered bibliography orphaned the entries that lost their number.** Two
    printed markers were enough to switch the positional fallback off for the whole list,
    so with "[1]", "[2]", "[4]" extracted and one number lost, "[3]" was reported as
    citing nothing. The map is now all-or-nothing.
  - **The pipeline broke a promise the function it calls still keeps.** `extract_document`
    built the artifact outside any guard, so a PDF GROBID could parse but pymupdf4llm could
    not open — encrypted, truncated — turned a complete reference check into a failed one.
    The plan's first Success Criterion covers exactly this ("or its inputs are
    unavailable"), and the `except Exception` around matching was one function too narrow.
    Body work now degrades to `artifact=None`, which the run status already reports as
    "the citation search did not run".
  - **The artifact leaked the manuscript through `repr`** — 13,788 characters of it,
    through `ExtractedDocument`, `CheckResult` and `AppState`. Phase 3 had recorded
    `Paragraph`/`SourceAnchor` as worth revisiting; Phase 4 is what put the whole body
    inside the two objects most likely to reach a debug print or a crash reporter. Now
    `field(repr=False)`, the same treatment `CitationContext.paragraph_text` already had.
  - **Eleven mutations survived the original suite**, including the one that matters most:
    disabling GROBID's own marker→entry link entirely left every test green, because every
    Tier 1 fixture made the marker's number equal the reference index. The tier's whole
    reason for existing — a TEI id is not a position — was unpinned. Fifteen mutations are
    now checked and all fifteen are caught.
  - Smaller, all fixed: a Chicago year opening an entry read as printed reference number
    1974; `reference_index` believed without checking it names a reference that exists
    (found independently by the fuzz); two redundant strips whose docstrings claimed they
    did something, verified dead and removed; and four weak assertions, including a
    `parse_marker` test that only checked its result was non-empty.
- Recorded, not fixed, and all four are judgement calls rather than defects:
  - ~~**0.80 absorbs a mistyped surname.** Smith/Smyth and Meyer/Meier score exactly 0.80,
    Fischer/Fisher 0.923, so "(Smyth, 2020)" against a bibliography carrying only Smith
    resolves rather than surfacing as an orphan. That runs against this feature's
    precision-over-recall stance and is taken deliberately: the same tolerance carries the
    far more common case of a name PDF extraction mangled, and a wrong orphan report is a
    false accusation where a wrong match is a missed one. Stated with the measured pairs in
    `SURNAME_MATCH_THRESHOLD`'s comment rather than left for someone to discover.~~
    **Closed 2026-08-13 (#62)** — the threshold was raised to 0.90, which sits in the gap
    between the worst pair of genuinely different names (Barth/Barthes, 0.833) and the
    best-damaged single name (Fischer/Fisher, 0.923), so "(Smyth, 2020)" now surfaces as
    an orphan. The trade the original wording defended was reversed rather than kept: a
    name damaged by more than roughly one character now fails to match, costing two false
    findings from one mangled name where 0.80 cost none. It is taken because diacritics
    are folded before comparison, which removes the commonest form of extraction damage
    from the question entirely. The measured pairs are asserted individually in
    `tests/test_citation_matching.py` because the recall corpus cannot see this constant
    at any value.
  - ~~**Tier selection is all-or-nothing on a single GROBID context.** One linked citation in
    a manuscript with fifty markers means Tier 0 never runs and forty-nine references look
    uncited. Not mixing tiers is right — mixing double-counts every marker they agree on —
    but switching on `len(citations) >= 1` is not what that argument supports, and no
    evidence available here says where the line should be.~~ **Closed 2026-08-12** — see
    the entry at the end of these notes. The reason no evidence said where the line should
    be is that there is no line: the tiers are separated by *which spans Tier 1 already
    answered for*, and the threshold is gone rather than tuned.
  - ~~**Zero matches with an `ok` status is a fourth state nobody named.** A document whose
    body extracted fine and whose markers detection missed reports every reference unused,
    and `unused_reference_numbers`' warning to gate on run status does not help because the
    status is `ok`. Phase 5 needs "no markers detected anywhere" as its own signal.~~
    **Closed in two steps.** Phase 5 named it `CITATIONS_NONE_DETECTED` (2026-08-11), which
    is what this item asked for. The whole-feature review then found the case the item did
    not anticipate: a run whose markers *were* detected but every one of which came back
    UNRESOLVED reports `ok` and flags the whole bibliography uncited — the identical false
    finding one step further along the pipeline, since UNRESOLVED is the status for
    declining to make a claim. `CITATIONS_NONE_MATCHED` closes that (2026-08-14, #64).
    ORPHANED deliberately does not count as declining: a marker is orphaned only after the
    index was consulted, so an all-orphaned run has read the list and may say what is not
    in it.
  - ~~**Tier 1 has no corpus-level measurement.**~~ **Closed 2026-08-11** — measured
    against a live `grobid/grobid:0.8.1` (the tag the Cloud Run demo pins; it reports
    `0.8.2-SNAPSHOT`), see `tests/test_tier1_grobid_live.py` and the paragraph below. The
    original wording is kept, below, because what it predicted was right: the tier that had
    never met real GROBID output was hiding a defect, and one measurement found it.

    > The 121/121 figure is Tier 0: the recall corpus pins GROBID off, and no GROBID
    > instance was reachable during the review. Tier 1 — the tier that runs in the deployed
    > product whenever GROBID is up — rests on hand-written TEI fixtures and the locator
    > has never met real GROBID output.
- PR #55 drew a further review (Codex, GPT-5) that found an eighth defect of the same
  family as the seven above, on the path where GROBID extracts the references but returns
  *zero* citation contexts — real whenever GROBID reads a bibliography without linking any
  body marker. Matching then falls to Tier 0 against GROBID's reconstructed entries, whose
  text carries no printed reference number, so `_reference_index` uses the positional
  fallback. Reproduced on a five-entry list with the third entry dropped: `[3]` resolved to
  the fourth printed entry **at confidence 1.0**, and `[5]` — sitting in the document —
  came back ORPHANED. One dropped entry, one confident wrong match and one false
  accusation. `_reference_index`'s own docstring had already conceded the premise ("the
  correct one whenever nothing was lost") without the code acting on it.
  - Fixed by flagging the fallback (`_ReferenceIndex.numbered`) rather than by plumbing
    extraction provenance as the reviewer suggested. Provenance answers "where did these
    entries come from", and the question that decides the outcome is "are these numbers the
    list's own" — which the Tier-0 path can also fail, since the all-or-nothing rule above
    abandons the whole printed map on one unreadable entry. The data-derived flag covers
    both; provenance would have covered one.
  - Against a positional list a miss is now UNRESOLVED, not ORPHANED (a number past the end
    is equally consistent with a dropped entry, and only one reading is the manuscript's
    fault), and a hit keeps RESOLVED but carries `_POSITIONAL_NUMBER_CONFIDENCE` = 0.5,
    deliberately below `SURNAME_MATCH_THRESHOLD` so a match resting on "the list is assumed
    complete" never outranks one a surname and a year corroborated. Refusing these markers
    outright was rejected: it would abandon numbered citations on exactly the path GROBID
    makes most common. Three mutations pin the new branches.
  - ~~**Still open:** where the list *is* positional and an entry was dropped, in-range
    markers remain silently off by one.~~ **Closed 2026-08-11** by
    `extraction/reference_list_audit.py`, and by exactly the route this bullet named: the
    printed numbers, from a reference-extraction change rather than a matching one. See
    the audit entry at the end of these notes.
- **Tier 1 measured against a live GROBID, 2026-08-11.** `grobid/grobid:0.8.1` (reporting
  `0.8.2-SNAPSHOT`), the five synthetic manuscripts, ground truth from the biblatex
  manifest. Harness: `tests/test_tier1_grobid_live.py`, which skips when no GROBID is
  reachable — so CI never runs it, and the numbers below have to be re-derived by hand
  against a stated version rather than watched by the suite.

  | | |
  |---|---|
  | citation contexts GROBID returned | 121 |
  | located in the manuscript | **121 (100%)** |
  | anchors overlapping a marker Tier 0 found independently | **121 (100%)** |
  | resolved | 111, of which 108 confirmed against the manifest |
  | resolved to a reference the manuscript does not cite | **0** |
  | unresolved | 5 |
  | orphaned | 5 — **all false accusations** |

  - **The locator holds.** This was the open item's actual worry: a `CitationContext` has
    TEI offsets that share no coordinate system with a `DocumentArtifact`, so Tier 1 finds
    its marker by searching the body text, and that search had only ever been given marker
    text this project wrote. It located every context GROBID produced, and every anchor
    landed on a span Tier 0 independently called a marker. `_is_free_standing`, added
    blind during the Phase 4 review, is doing its job on real output.
  - **The measurement found a defect, which is why it was worth running.** All five orphans
    are manuscripts being told they cited nothing when they cited correctly. Four are one
    cause: GROBID's reconstructed entry text carries **exactly one year**, and for a
    reprint or translation it is the original's, not the entry's own date slot. The APA
    fixture prints "Weber, M. (1930). … [Original work published 1905]" and the manuscript
    cites (Weber, 1930); GROBID keeps 1905 alone and `_year_agreement` vetoes the pairing.
    Chicago's humanities document supplies three more — Levinas 1969/1961, Adorno &
    Horkheimer 2002/1944, Eco 1989/1962 — because reprint-and-translation citation is what
    that literature does. The fifth is an entry GROBID reconstructed as bare "(1961)",
    having lost the author entirely.
  - The year veto is not wrong in general; its premise is. It assumes the entry text holds
    every year the entry printed, which is true of extracted text and false of a
    reconstruction. This is the same shape as the two defects above — a rule that is sound
    against one kind of evidence, applied to another kind that cannot support it — and the
    same consequence, a false accusation.
  - **Fixed 2026-08-11 by carrying the printed entry.** GROBID returns each entry's
    original string in a `<note type="raw_reference">` when the request asks for it
    (`includeRawCitations=1`, verified against GROBID's service documentation), so
    `call_grobid` now asks, `ExtractedReference.raw_reference` carries it, and
    `RawReferenceEntry.source_text` hands it to matching, which reads it in preference to
    the reconstruction (`citation_matching._entry_text`). The alternative — weakening the
    veto to a penalty for a single structured year — was rejected as treating the symptom:
    it would have left the lost-author entry unmatched and would have weakened a rule that
    is correct wherever the evidence is complete.
  - The reconstruction stays as `raw_text` rather than being replaced. It is the tidier
    string for display and for the verification query, and the printed one is unnormalised
    and can carry a fragment of the neighbouring entry. Two strings with different jobs,
    which is why the field is named for what it is rather than for being "better".
  - Re-measured on the same corpus and version: **orphans 5 → 0**, resolved 111 → 116,
    every resolved match placed in the manifest, still 0 naming an uncited reference and 0
    attributed to the wrong author. The 5 that remain
    unresolved are markers GROBID truncated at a page locator ("[15, p. 87", "9]") and
    linked to nothing; "cannot tell" is the right answer for those. Zero orphans is now
    asserted (`test_no_citation_is_reported_as_an_orphan`) rather than merely recorded —
    on this corpus every marker cites a real entry, so any orphan is a false accusation
    whatever a future GROBID does. Four mutations pin the new path.
  - It does **not** help the positional off-by-one above: GROBID strips the printed list
    number from the raw reference too (0 of 30 IEEE entries kept one), so a reconstructed
    numbered list is still numbered by position only. Still true of GROBID's output, and
    still the reason the off-by-one existed — what closed it was giving up on GROBID's two
    strings and reading the numbers off the bibliography section instead
    (`reference_list_audit`, at the end of these notes).
  - The first version of this harness reported some resolved matches as unconfirmed and
    **excluded them from the correctness assertion**, which PR #56's review (Codex, GPT-5)
    caught: the references whose identity is ever in doubt are precisely the ones GROBID
    damaged, so excluding them checked everything except what needed checking. The mapping
    is now total — a reference that cannot be placed fails the assertion instead of being
    skipped — and it maps to a *set* of manifest keys, because GROBID folded the Chicago
    bibliography's repeated-author entry into its predecessor and one reference genuinely
    carries both Ricoeur 1969 and Ricoeur 1970.
  - A second gap, found while checking the first: "names an entry the manuscript cites" is
    not identity, and a mutation mapping every reference to the same cited entry passed.
    Where a marker prints a surname the entry it resolves to must now be by that author
    (`test_an_author_date_marker_resolves_to_the_author_it_names`), which catches it.
    Numbered markers name no author and are left to GROBID's link and to the Tier-0 recall
    module, which pins marker→entry identity on this same corpus.
  - Also observed, and GROBID's behaviour rather than this project's: the counts do not
    match the manifest's 30 per document. Re-measured 2026-08-11 with the audit in place,
    which says what the counts alone could not: the Chicago list comes back 29 because one
    entry absorbed its repeated-author neighbour, and APA comes back 31 because one printed
    entry was split in two. Nothing was dropped outright on this corpus. Downstream can now
    tell — the audit reports both, and both are on the References screen and in the
    report.
- **Phase 5 shipped 2026-08-11**, and departed from its own file list twice, both recorded
  here rather than folded in silently:
  - **`src/refcheck/gui/citation_display.py` is new**, against the phase's "none
    anticipated". Two callers need the same answers — the screens and the exported report
    — and a wording that drifts between them is a wording the reader cannot trust. It is
    also the only way the layer gets tested: the NiceGUI pages had no harness at all, so a
    judgement made inside a `render()` is untested by construction.
  - **A fourth run state, `CITATIONS_NONE_DETECTED`**, which the phase did not ask for and
    could not have been written without. Phase 4 had already recorded the gap ("zero
    matches with an `ok` status is a fourth state nobody named"); Phase 5 is where it bites,
    because a search that ran cleanly and detected nothing satisfies
    `unused_reference_numbers` for *every* reference. Rendering that would have flagged a
    whole bibliography as uncited on the strength of having found nothing — the same
    false-accusation shape as the defects in Phases 4 and the live measurement, arriving
    this time through the UI rather than through the matcher. `citation_display` therefore
    withholds every per-reference claim unless the run status can support it, which is the
    rule `unused_reference_numbers` documents and cannot itself enforce.
  - Closes the Phase-4 open item above. Of the remaining three, the positional off-by-one
    was closed by the reference-list audit on 2026-08-11 (see the end of these notes); 0.80
    absorbing a mistyped surname and all-or-nothing tier selection are untouched and still
    open.
- What the surfacing says, and what it refuses to say:
  - The per-reference figure is labelled **"In text"**, not "Cited": OpenAlex's "Cited by"
    is already on the same detail panel, points the opposite way and differs by orders of
    magnitude. The plan called this collision out before either was rendered.
  - An **ambiguous** marker's candidates are never counted as citations and never reported
    as uncited, and their passages *are* offered to the reviewer — labelled "may name this
    reference". Whoever is resolving an ambiguity is exactly who needs to read around the
    marker; presenting it as confirmed would be the guess this feature refuses everywhere
    else.
  - **Orphaned** markers appear in the document headline rather than in any row, since an
    orphan's whole content is that there is no row for it. **Unresolved** markers are
    counted and deliberately kept out of the findings sentence — "cannot tell" is the
    honest answer for the five the live measurement leaves on the synthetic corpus, and it
    is not a defect in the manuscript.
  - "Cited 3 times" and three passages are **not** the same claim: locating and resolving
    are separate questions, so a match can be counted in the figure and have no anchor to
    show. `places_for` returns only the anchored ones.
- The context gate ended up in two places rather than one, which is the plan's decision
  read literally: `show_citation_context` guards the screen, `export_included
  ["citation_passages"]` guards the file, and neither reads the other. Showing a sentence
  in a session and writing it into a file that outlives the session are different acts.
  Both default off; the screen toggle also resets on every upload, because consent to read
  one manuscript's sentences is not consent to read the next one's. The on-switch sits
  where the passages would appear, so the choice is offered where its consequence is; the
  off-switch sits on the always-visible header, so a reviewer wanting the text off screen
  need not find the row they turned it on from.
- `DEFAULT_EXPORT_INCLUDED` moved into `report_builder` so `AppState` and the export screen
  stop each holding their own copy of the defaults. The copy that matters is whichever one
  `citation_passages` is False in, and the screen's old `.get(key, True)` fallback would
  have defaulted a missing passage key to *on*.
- **The project's first render tests** (`tests/test_citation_screens.py`). The pages build
  outside a client — `render()` only needs a slot — so the element tree can be walked and
  the labels read back. They assert presence and wording, not layout: that a reference
  nothing cites says so on its collapsed row, that no manuscript text appears until the
  gate is opened, and that the three statuses which cannot support a claim produce none.
- ~~Not done, and the next thing worth doing: nothing surfaces **where the reference list
  itself came back short**.~~ **Done 2026-08-11** — see the entry below, which closes this
  and the positional off-by-one together, because they turned out to be one problem: both
  are what happens when the extracted list is trusted to be the printed one.
- **The reference list is now checked against the list the document printed**
  (`extraction/reference_list_audit.py`, shipped 2026-08-11). The document is the evidence:
  `document.py` already isolates the bibliography text for the Tier 0 splitter, so on any
  check that reads the body the printed list is in hand alongside the extracted one. The
  audit aligns the two by token coverage and answers two questions with one comparison.
  - **What number does each entry print for itself.** This is the fix for the off-by-one,
    and it is a fix rather than a hedge. GROBID strips the printed marker from both of its
    strings, so `_reference_index` fell through to position on every numbered Tier-1
    bibliography — and, less obviously, on every numbered *Tier-0* one too, since
    `split_bibliography_block` strips the marker as well. Resolving a numbered marker
    through `audit.by_printed_number` removes the condition entirely: with the second of
    four entries dropped, the entry now in position 2 answers to "[3]", at confidence 1.0
    rather than the positional 0.5.
    `_POSITIONAL_NUMBER_CONFIDENCE` and the `numbered` flag stay, and still do their work
    wherever the printed numbers cannot be read — an unnumbered list, a DOCX, a document
    with no locatable bibliography.
  - **Whether the extracted list has the shape of the printed one**, reported as three
    different sentences because they are three different things: an entry covering two
    printed entries has absorbed one, an entry covering none is a fragment, and a printed
    entry nothing covers is missing from every figure on screen. A merged entry is entered
    under *both* of its numbers rather than being treated as a hole — it does carry both
    works — while the merge itself is reported separately, so nothing rests on the counts.
  - **It reports no total it did not read.** The printed count appears only where the list
    numbers itself; elsewhere the count would be the Tier 0 splitter's opinion, which is
    wrong by one on this project's own Chicago fixture (31 for 30). The structural findings
    stand there instead, because they come from the alignment, which that miscount does not
    change. This is the same rule the rest of the feature follows: a figure needs evidence,
    and a heuristic's opinion is not one.
  - **`read` and `complete` are separate, all the way out to the wording.** A list nothing
    could compare produces *no note at all* rather than a caveat — a caveat on every DOCX
    is one a reviewer stops reading before it means something — and a whole list says so
    quietly. What must never happen is the two rendering the same, which is the same
    absence-read-as-a-fact shape as `Cited by: 0` and `Retraction: none` in Phase 5.
  - **Measured against the live corpus** (`grobid/grobid:0.8.1`, five manuscripts). The
    audit reports exactly the two defects the manifest proves are there — the Chicago
    repeated-author merge and the APA split — and nothing on the three GROBID extracts
    cleanly. `test_the_audit_agrees_with_the_manifest_about_whether_the_list_came_out_whole`
    asserts both directions: a false alarm is the same false accusation the rest of this
    module is written against, and a miss leaves every count looking authoritative.
  - `tests/test_tier1_grobid_live.py` now goes through `extract_document` rather than
    assembling GROBID and the artifact itself, so what it measures is the path a check
    actually takes — the old fixture left the audit, the step that decides what a numbered
    marker means, outside everything it asserted.
  - **PR #58's review (Codex, GPT-5.6 Sol) found the first design of this wrong, and the
    fix is why the audit is passed to `match_citations` rather than stamped onto the
    entries.** The first version wrote each entry's numbers onto a
    `RawReferenceEntry.printed_numbers` field and left `_reference_index`'s existing
    all-or-nothing rule in place: one entry without a number abandons the whole map. That
    rule is right for the reading it was written for — a number missing from an *entry's
    own marker* is a number this project failed to read, and a hole in that map turns a
    marker into an orphaned citation. It is wrong for the audit's, and the difference is
    which list each is built by walking. Walking the *printed* list means every printed
    number is either mapped or in `missing`, so that map has no holes; an extracted entry
    under no number is a fragment, which is a **finding** rather than a gap. Treating one
    as the other meant a split entry discarded the map and reintroduced the shift: printed
    `[1] A`, `[2] B`, `[3] C` extracted as `A`, `B-first-half`, `B-fragment`, `C` resolved
    "[3]" to the fragment in position 3.
    - Passing the audit down instead of stamping fixes it and removes code: no field, no
      mutation of entries the caller owns, and no `__eq__` exclusion — which had been
      needed only because the stamped field made `extract_document` and
      `extract_references` disagree, against the first Success Criterion.
    - **A second defect of the same family fell out of verifying the first**, and is the
      more dangerous one: with an entry genuinely dropped, "[2]" came back **ORPHANED**.
      Reading the numbers off the page had made `numbered` true, and `numbered` was
      deciding two different questions — whether a *hit* is exact, and whether a *miss*
      proves the bibliography has no such entry. The audit is the first source that can
      answer yes to the first and no to the second, since it knows printed [2] exists and
      produced no entry. Split out as `_ReferenceIndex.exhaustive`: a marker citing an
      entry extraction lost is UNRESOLVED, which is what it was before this branch and
      what it must stay. Calling it orphaned accuses the manuscript of this project's own
      miss — the exact failure the whole feature is written against, and it would have
      shipped inside the change that closes it.
    - Three regressions pin the three outcomes: the split resolving past the fragment, the
      lost entry staying UNRESOLVED, and — so the fix does not flatten the true finding —
      a number past the end of a *whole* list still reporting as ORPHANED.
- **The in-session context gate was removed on request, 2026-08-11.** The Design Decisions
  row above ("Context-passage visibility & depth", resolved 2026-08-04) chose to hide
  quoted passages behind a `show_citation_context` switch even in-session; passages are now
  shown outright and the switch, and its `AppState` field, are gone. What stands either
  way: the manuscript is the reviewer's own upload and its text is already on the screen
  in the row above. What was given up: a shared screen or a live demo now shows the
  document's sentences without anyone choosing to. Recorded here rather than by rewriting
  the decision row, because the reasoning that was overruled is the part worth keeping.
  - **The export opt-in was deliberately not removed.** `export_included
    ["citation_passages"]` still defaults off. A file leaves the session, and reading a
    sentence in the app is not the same act as writing it to disk — that was always the
    argument for having two gates, and it is unaffected by dropping one of them.
  - Session-scoping is untouched and is what does the real work: passages are read from
    the artifact at the moment of drawing, never stored, never copied into a match.
- **Tier selection stopped being a switch, 2026-08-12** (`citation_matching.match_citations`
  / `_match_grobid`). Tier 0 now always runs; Tier 1 answers for the markers GROBID linked
  and Tier 0 answers for the rest, separated by **overlap** rather than by a decision about
  which tier owns the document.
  - **The open item asked the wrong question, which is why it had no answer.** It looked for
    the count at which `len(grobid_citations) >= 1` should have fired, and recorded that no
    available evidence said where the line was. There is no line. One linked context is not
    evidence that GROBID found the others, and no larger number is either — a manuscript
    where GROBID links forty-nine of fifty markers has the same defect once, and one where
    it links one of fifty has it forty-nine times. So the threshold was removed rather than
    tuned.
  - **What separated the tiers before was the document; what separates them now is the
    span.** The argument against mixing was always about double-counting, and it is real:
    run both over the whole body and every marker they agree on is counted twice. It became
    answerable because Tier 1 already has to locate its markers in the artifact
    (`_locate_marker`, Phase 4) to say where they are, which is the position problem the
    original objection said would have to be solved first. It was solved, in Phase 4, and
    the objection outlived it.
  - **Measured both halves against a live `grobid/grobid:0.8.1`, five manuscripts.**
    - *Safety:* all 121 contexts located and all 121 anchors landing on a span Tier 0 had
      independently called a marker, so the supplement added **0** matches on all five
      documents — 121 matches, 116 resolved, 0 orphaned, identical to the pre-change
      numbers. **That figure was measured against the first exclusion rule and no longer
      holds**; see the review entry below, which replaced the rule and expects a supplement
      on a clean document. What is asserted now is the invariant rather than the count
      (`test_no_marker_is_counted_twice_where_the_two_tiers_meet`): two matches may share a
      span, but they may not name the same reference from it, which is what would inflate a
      "cited N times" figure.
    - *The defect:* this corpus cannot exhibit it, because GROBID links every marker in all
      five documents. Constructed by withholding what GROBID returned — keep one context,
      drop the rest, which is exactly what the old switch could not tell apart from a
      document with one citation in it. Across the four multi-citation manuscripts, false
      "cited by nothing" findings went **116 → 1**:

      | document | uncited before | uncited after |
      |---|---|---|
      | APA 7 | 30 | 1 |
      | Chicago author-date | 28 | 0 |
      | Vancouver | 29 | 0 |
      | IEEE | 29 | 0 |

      The one remaining is a Tier-0 recall limit on the APA document, not a limit of the
      supplement.
  - **An unlocated context holds the whole supplement back.** A context that placed nowhere
    has claimed no span, so nothing can tell whether a Tier 0 detection is that same marker
    read a second time; the pass is skipped and the function returns what it always
    returned. Counting one citation twice is a wrong number where skipping is a missing one,
    and this feature's standing rule is that a figure needs evidence. Deliberately not a
    per-context exclusion by marker text: the contexts that fail to locate are the ones
    GROBID hands over truncated ("[15, p. 87"), whose text is precisely what will not match
    what Tier 0 read.
  - The supplement is labelled `ENGINE_ANCHOR`, because that is which tier found it. Tier
    1's link is GROBID's own resolution against the bibliography; a Tier 0 supplement is an
    inference from the marker's text, and labelling them alike would hide the difference
    from anything downstream that sorts or displays by tier.
  - `profile` now narrows the supplementary pass on the Tier 1 path, where it was
    previously documented as unused — the same style evidence that narrows marker families
    on the Tier 0 path applies to the same detection call.
  - `test_the_tiers_are_not_mixed` was the one test this changed rather than added, and it
    was pinning the defect: its document had a `(Doe, 2020)` marker that went unread
    because `[1]` happened to be linked. It is replaced by three that pin the new contract
    — the unlinked marker being read, one marker never producing two matches, and an
    unlocated context holding the pass back.
  - **PR #59's review (Codex, GPT-5) found the exclusion rule wrong, in the same shape as
    the defect it was fixing.** Overlap was applied per detection, but a grouped marker's
    Tier 0 members all carry the *group's* span — `detect_citations` reports "[1, 2]" as two
    detections over the same six characters. So a single linked member suppressed the rest
    of its own group: with body `Prior work [1, 2] shows this.` and only a context for "[1",
    reference 2 came back cited by nothing. Reproduced exactly as reported.
    - Fixed by excluding on the **reference** rather than the region
      (`_already_answered`): a supplement survives when it names a reference no overlapping
      Tier 1 match named. A detection Tier 0 could not resolve, or one resolving to a
      reference Tier 1 already reported at that span, is still dropped — keeping it would
      put a second record on one citation, and a duplicate is a wrong number where a drop
      is a silent one. A Tier 0 reading that *disagrees* with Tier 1 about the same span is
      also dropped: Tier 1's answer is GROBID's own resolution against the bibliography and
      this module has no evidence to overturn it.
    - **A consequence worth stating, because it moved a measured figure.** The rule also
      recovers markers GROBID hands over truncated at a page locator ("[15, p. 87") and
      links to nothing — Tier 1 reports UNRESOLVED, having named no reference, so Tier 0's
      reading of the same span is new information about a reference rather than a second
      opinion on one. On the live corpus those are exactly the 5 unresolved markers, so the
      supplement is now expected to add matches to a document GROBID reads whole, where the
      first rule added none. The cost is that such a marker produces two records — Tier 1's
      "cannot tell" and Tier 0's answer. Counts are unaffected (`citation_counts` takes
      RESOLVED only, and the reference is counted once), but a reviewer sees the marker
      twice. Accepted over suppressing GROBID's record, which would mean dropping a report
      on the strength of a tier this module rates lower.
    - **Re-measured against the live corpus, 2026-08-12** (`grobid/grobid:0.8.1`), once
      GROBID was reachable again. It improved the corpus rather than merely holding it:

      | | before | after |
      |---|---|---|
      | matches over the same 121 contexts | 121 | **126** |
      | resolved | 116 | **121** |
      | unresolved | 5 | 0 |
      | orphaned | 0 | 0 |

      The 5 new matches are the supplements, and they are exactly the 5 truncated markers —
      each resolved at confidence 1.0. **The reviewer's scenario turned out to be in
      GROBID's own output, not just constructible**: the Vancouver document prints "[8, 9]"
      and GROBID truncates its context to "9]", so both Tier 0 members carry the group's
      span and the region-based rule would have dropped reference 9. The review found a
      defect this corpus was already exercising.
    - `test_every_citation_context_is_located_in_the_manuscript` asserted
      `len(matches) == len(citations)`, which was a proxy for "one match per context" and
      is no longer true once a supplement exists. Narrowed to Tier 1's own matches with a
      one-sided bound, so it still fails if a context goes unplaced but no longer fails
      merely because Tier 0 found something. `test_a_marker_grobid_truncated_is_recovered_rather_than_left_unreadable`
      pins the new fact per-supplement rather than as a total.
- **A citation's context can no longer exclude the citation, 2026-08-13**
  (`document_artifact.context_bounds`, and the context viewer's `_passage_slice`). Closes
  the Phase 1 open item above.
  - **The defect.** `anchor_for` resolves a span straddling a block boundary to the first
    paragraph it overlaps — which is right, since no single paragraph contains such a span,
    so no other choice is better. But `snippet`, `sentence_bounds` and `paragraph_text` all
    clipped to that paragraph, cutting the anchor in two. Reproduced through the shipped
    detector, not by hand: "As several have shown (Doe, 2020;" ends one paragraph and
    "Roe, 2019) the effect is robust." begins the next, `detect_citations` reports one
    grouped marker across the boundary, and a reviewer checking the citation to **Roe 2019**
    was shown a passage ending at "(Doe, 2020;". The one thing the passage existed to
    contain was the one thing missing from it.
  - **The fix is a widening, not a loosening.** The rule the clip enforces is about a
    neighbouring paragraph *the anchor has nothing to do with* — a paragraph the marker
    itself runs into is not one. `context_bounds` returns the union of every paragraph the
    anchor overlaps, never narrower than the anchor, which is exactly the anchor's own
    paragraph for every span that does not straddle. Quoting less than the marker is the
    worse disclosure error of the two, because it shows a reviewer text that does not say
    what they were told it says.
  - **The UI needed the same fix and did not get it for free.** `_passage_slice` read
    `paragraphs[anchor.paragraph_index]` directly rather than going through the artifact,
    so the expand view kept cutting the marker in half after the artifact stopped — and
    once the collapsed depth covered both paragraphs and the expanded one did not, clicking
    "expand" made the passage *shrink*. The ellipsis test was measured against the anchor's
    paragraph too, so a straddling passage looked truncated at one end and whole at the
    other, both wrongly. Worth recording because the artifact-level fix looked complete and
    the suite stayed green: the consumer that bypassed the accessor was invisible to it.
  - **The missing assertion is now a property rather than a case.**
    `test_context_never_excludes_the_span_it_is_the_context_for` runs every detected marker
    in five documents through `snippet`, `sentence` and `paragraph_text`. The plan recorded
    that nothing asserted `snippet(a)` contains `body_text[a.start:a.end]`, and that absence
    is precisely why the straddling case went unnoticed — a single-case test would have left
    the same gap one shape further along.
  - **PR #60's review (Codex, GPT-5) caught the label the widening left behind.**
    `_depth_label` was fixed text — "full paragraph", "click for the paragraph" — while the
    expansion it describes now covers every paragraph a straddling marker runs into. In
    exactly the case the fix exists for, the UI understated what was on screen and promised
    the wrong thing on click. The same defect shape as the fix itself, one layer up: the
    passage and the words describing it disagreeing about what the reviewer is looking at.
    - Derived from the bounds rather than renamed to "full context", which was the
      review's other suggestion. Renaming is correct everywhere and specific nowhere, and
      the multi-paragraph case is rare — a reader is better told "paragraph" when a
      paragraph is exactly what they will get, and "all 2 paragraphs" when it is not.
- **The three standing decisions were taken 2026-08-13, and the list is now empty.**
  Recorded here because each had been carried in session notes rather than in this file,
  which is how the double-parse item came to be re-derived as open twice.
  - **`SURNAME_MATCH_THRESHOLD` raised 0.80 → 0.90.** The gap between 0.833 (Barth/Barthes,
    two different authors, both in this project's Chicago fixture) and 0.923 (Fischer/Fisher,
    Mueller/Muller, Shannon/Shanon — one name written twice) is the whole argument: below it
    are two different names, above it is one damaged name, and 0.80 sat under both groups so
    it could not tell them apart. At 0.80, "(Smyth, 2020)" resolved against a bibliography
    carrying only Smith, and Barth/Barthes were separable only by their years.
    - **The cost is the reverse trade, and is real.** A name damaged by more than roughly
      one character now fails to match, which reports the reference uncited *and* the
      citation orphaned — two false findings from one mangled name, where 0.80 produced
      none. Taken because diacritics are folded before comparison (Levinas/Lévinas is 1.000,
      not 0.9), which removes the commonest form of extraction damage from the question, and
      because what remains is typically a dropped letter, inside the 0.923 band.
    - **No test can move this number**, and that is the point worth remembering: the recall
      corpus resolves all 121 citations identically at every threshold from 0.0 to 1.0,
      because the year separates them. The suite was green before the change and after it.
      The pairs are therefore asserted individually — that the different-name pairs fall
      below the threshold, that the damaged-name pairs clear it, that the threshold sits in
      the gap, and that the scores themselves have not moved.
  - **OpenAlex keeps being asked on the direct-DOI path.** Skipping it to save budget means
    a retracted paper can go unflagged, which is the one error a manuscript-review tool must
    not make. The constraint is real — ~1,000 requests/day anonymously is ~30 full checks —
    but the answer is the free API key (10x), not fewer retraction checks. The runtime
    message already named `OPENALEX_API_KEY`; the README did not mention it at all, and now
    documents the budget, what silently degrades when it runs out, and where to get a key.
  - **The Europe PMC abstract/keyword fallback is dropped.** It appeared in no plan, no
    code and no doc — it existed only in a session summary, so it was never a decision this
    project had taken. The gap behind it is real (OpenAlex is the only source for abstract,
    topics and keywords, Crossref having been measured and dropped for both), but Europe PMC
    is biomedical-only and would serve one of the four target styles. If abstracts prove
    thin in practice, the item comes back with a measured miss rate rather than a hunch.

### Whole-feature review, and what closes this plan (2026-08-15 / 2026-08-16)

The per-phase reviews above each looked at one phase as it landed. This one looked at the
finished feature at once, against `ce560d4` (Claude Code, Fable 5, medium thinking). Nine
findings, every one confirmed by execution before being reported, all closed in #64. The
three that mattered most, because each was invisible to a green suite:

- **Tier 0 detection was quadratic in document length.** Every backwards cue search copied
  and re-scanned the whole prefix, so a manuscript with twice the markers cost four times
  the time: 78s on a 114 KB numbered review article, inside the check, before verification.
  Now 0.095s. No correctness test could see it — nothing raised, the check simply stalled.
- **Two false findings**, which this feature treats as the expensive direction: a gap in an
  entry-marker numbered list read as the author citing a reference that is in fact in their
  own list, and a run that resolved nothing reporting `ok` and flagging the whole
  bibliography uncited.
- **A constant with two documented properties had a test for one.**
  `_MISSING_YEAR_PENALTY` was perturbed downward when it was recorded as "covered", and
  down is the direction that fails loudly. Upward was silent, and at 0.99 a damaged name
  resolves against a dateless entry — the exact match the 0.90 threshold exists to prevent,
  reached through the other constant. Both edges are now asserted, and
  `tests/fixtures/intext_citations/meta.json`'s rule was corrected to say *both directions,
  once per documented property*.

The review's own fix drew a review (Codex, GPT-5.6) that found a behaviour regression in
it: the bounded cue window was bounded in characters, and none of these grammars bounds
word length, so a determiner phrase with long extracted tokens escaped the window and
emitted a marker the unbounded search had suppressed. A false positive, from a change whose
PR claimed behaviour preservation on a 209-text differential. The differential was real and
still wrong — every probe varied distance in ways that leave the grammar. The window is now
bounded in words, and the replacement differential generates the cue phrases themselves
(0 differences over 20,000 texts). Recorded here because the lesson generalises past this
feature: **a differential is only as good as the axes its generator moves.**

**Still open, and none of it blocks the demo:**

- **Page-number anchors.** Deferred by decision in Phase 1 and still deferred. A reviewer
  ultimately wants "page 7"; they currently get a line index.
- **Tier 1's grouped markers do not share one source position** (Phase 3's note).
- **Three areas the review did not examine, for budget**, and which no review has covered:
  `reference_list_audit`'s alignment algorithm, the tier0 splitter's gates, and the DOCX
  read path. Worth knowing before anyone treats "reviewed" as "reviewed everywhere" — the
  audit in particular decides what a numbered marker means, and is the thing standing
  between a dropped entry and a false orphan.
