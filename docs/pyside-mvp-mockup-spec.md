# PySide6 MVP Mockup Spec — Reference Checker

Working spec for the mockup, derived from [project-plan.md](project-plan.md). Scope matches
the MVP: reference-list checking against OpenAlex/Crossref, no LLM, no citation network graph.

This spec was reconciled against the built mockup (`docs/gui_mockup/Reference Checker
Mockup.dc.html`) on 2026-07-28 — see "Reconciliation decisions" at the bottom for what changed
and why.

## Screens

### 1. Upload / New Check (includes Processing)
- Drag-and-drop zone + file picker (PDF/DOCX only)
- Shows file name, size, page count once loaded
- "Start Check" button (disabled until a file is loaded)
- Disclaimer banner — content depends on deployment mode (see below); rendered in the sidebar
  mode panel plus a persistent bottom "privacy & data flow" stripe, not a banner inside the
  drop zone
- Processing is **not a separate screen** — once "Start Check" runs, the right-hand "Loaded
  document" panel switches to a progress view in place: progress bar with stage labels
  (Extracting references → Querying OpenAlex/Crossref → Scoring), live counter ("N of M
  references processed"), and a Cancel button

**Deployment-mode variants for the disclaimer** (swappable copy slot, not separate screens —
Summary/References/Manual Review/Report are shared across modes):

- **Local desktop app** (Phase A target):
  > "This document stays on your device. Only title, author, and DOI are sent to
  > OpenAlex/Crossref for verification."

- **Hosted demo server** (for reviewers who can't/won't install the app locally): full working
  upload, same as local mode — no functional restriction.
  > ⚠️ **Demo deployment** — Uploaded documents are processed on this server, not on your own
  > device. Uploaded files are intended to be deleted immediately after processing — nothing
  > should persist past the request. Don't upload unpublished or confidential work.
  - "Try the synthetic example instead" link/button alongside real upload, not replacing it.
  - Retention policy is now decided (see "Open follow-up" below): delete immediately after
    processing. The blocker-styling requirement below applied only while the policy was
    undecided — now that it's resolved, the line renders as plain copy, not a blocker. **Note
    for whoever builds the actual hosted demo backend:** no server-side upload/deletion code
    exists yet anywhere in this codebase (see "Open follow-up") — this disclaimer states
    intended policy, not an implementation guarantee, until that backend enforces it.

- **Phase B production server** (university infrastructure, real institutional use — later,
  contingent on DSGVO sign-off per project-plan.md):
  > "This document is processed on the university's server ([hostname]), not sent to any
  > external service beyond OpenAlex/Crossref for reference verification. Full text is
  > retained per [retention policy] and deleted according to [deletion policy]."

### 2. Summary (results overview)
- Summary cards: verified count, duplicates, likely-hallucinated, needs-manual-review, avg.
  publication age, **retraction warnings** (Crossref retraction marker — cheap to compute from
  data already fetched during verification)
- Card set is user-configurable via a "choose metrics" picker; two reserved placeholder slots
  for future metrics are acceptable but must not ship as fake data
- Embedded matplotlib charts (`FigureCanvasQTAgg`): publication-age histogram, topic-breadth
  chart, and **citation-frequency-of-cited-sources chart** (distribution of `cited_by_count`
  across unique matched sources)
- "Export Report" button
- API-degradation warning banner (e.g. Crossref rate-limited) when any references end up
  `unchecked` rather than a definitive status — surfaces at the top of this screen

### 3. References (reference table)
- Sortable/filterable table of all references — columns: raw citation text, status badge +
  confidence score. Matched title/DOI is **not** a top-level column; it lives in the row's
  expandable detail (fold or side panel — implementation may choose either) alongside lookup
  metadata (source, queried time, cited-by count, retraction status)
- Status badges use a consistent color vocabulary, reused identically in Manual Review:
  green = verified, amber = needs review, red = suspected hallucination, gray = duplicate,
  blue-gray = not checked
- Filter/tab bar to slice the table by status
- "Export Report" button
- **Deferred to a later phase, not MVP**: in-text citation passage tracing (page/paragraph
  location of each in-text citation, highlighted excerpt, "open page in source document").
  This needs new extraction logic to locate in-text citations in the source PDF/DOCX, which
  does not exist yet. The mockup keeps this as a visible placeholder/mock-data section so the
  design isn't lost, but it must not be wired to real data or promised for Phase A delivery.

### 4. Manual Review Queue
- Table of only unresolved references: automated status, confidence, best candidate matches
  (selectable) if available
- Per-row actions: Confirm candidate / Correct manually (DOI/title/author/year form) / Mark
  not-findable / optional free-text comment
- Each action stamps a timestamp, visible in the row once acted on — needed so the report can
  separate automated vs. manual status with timestamps

### 5. Report Export
- Simple save dialog; shows what will be included (category scores, confidence values,
  manual-review audit trail, charts, API/check metadata)
- Export is templated HTML (Jinja2 + embedded matplotlib images) — no live preview needed in
  the PySide app
- Demo-mode exports are watermarked "SYNTHETIC EXAMPLE" when generated from the bundled
  synthetic manuscript

## Demo mode details (hosted showcase)

- Real upload stays enabled (per user decision — usability over restricting to synthetic-only)
- Additionally offers "Run synthetic example" — a bundled fake manuscript with pre-seeded
  references covering every status category (verified, duplicate, hallucinated, needs review),
  so the summary/table/charts always have something interesting to show regardless of what
  a visitor uploads
- Persistent, non-dismissible "Demo — synthetic data only" style banner adapts wording to
  clarify real uploads are also processed (not just synthetic), per the deployment-mode
  disclaimer above; retention line (see Screen 1) is now resolved copy, no longer a blocker

## Cross-cutting notes
- No citation-network graph anywhere in the mockup — explicitly deferred in the plan
- Single-window app with sidebar navigation across 5 destinations (Upload&Check → Manual
  review → References → Summary → Report export) — not multiple windows, simplifies
  PyInstaller packaging
- Status-badge color vocabulary must stay identical across Summary, References, and Manual
  Review

## Open follow-up (tracked separately)
- **Resolved (2026-07-29):** retention policy for files uploaded to the hosted demo server —
  delete immediately after processing, nothing persists past the request. Disclaimer copy and
  sidebar blocker styling updated accordingly (`src/openrefcheck/gui/deployment.py`,
  `src/openrefcheck/gui/sidebar.py`).
- **Still open:** no server-side upload-handling or deletion-enforcement code exists yet — the
  app is currently local-only, and "demo" mode is only a GUI copy variant. Whoever builds the
  actual hosted demo backend must implement immediate deletion to match this disclaimer, not
  just carry the copy forward.

## Reconciliation decisions (2026-07-28)

The mockup (built after this spec) diverged from it in several ways. Decisions made to
reconcile, recorded here so intent isn't lost:

- **Screen structure**: adopted the mockup's layout (Processing folded into Upload; Dashboard
  split into Summary + References) over the original spec's separate-Processing /
  single-Dashboard structure — better fits large reference lists and was already built.
- **Matched title/DOI column**: accepted the mockup's move of this into row detail rather than
  a top-level column.
- **In-text passage tracing**: cut from MVP scope (needs unbuilt extraction capability), but
  kept as a visual placeholder in the mockup rather than removed outright.
- **Retraction metric + citation-frequency chart**: kept, since both come from data already
  fetched during OpenAlex/Crossref verification.
- **Retention-TODO placeholder**: mockup had silently dropped it; restored and required to
  render as a visually distinct blocker in demo mode, per the original spec's "must not ship
  un-finalized" requirement.
