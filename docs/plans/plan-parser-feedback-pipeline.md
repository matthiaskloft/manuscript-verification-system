# Plan: Privacy-Preserving Parser Feedback Pipeline

**Created**: 2026-07-31  
**Author**: Codex (GPT-5.6)

## Status

| Phase | Status | Date | Notes |
|-------|--------|------|-------|
| Spec | DONE | 2026-07-31 | User constraint: source PDFs are never shared. |
| Plan | DONE | 2026-07-31 | Ready for review. |
| Phase 1: Local feedback capture and preview | TODO | | |
| Phase 2: Private intake API and queue | TODO | | |
| Phase 3: Sanitization, review, and approval workflow | TODO | | |
| Phase 4: Isolated parser agent and draft PR | TODO | | |
| Ship | TODO | | |

## Spec

### Summary

When a user rechecks references, the application should let them submit only
the reference-section Markdown and parser outputs for selected failing items.
The source PDF must never leave the user’s environment. Submitted cases are
stored privately, reviewed and sanitized, then optionally processed by the
parser-improvement workflow in an isolated worker that opens a draft GitHub PR.

### Requirements

- Provide a feedback action after a parser recheck, limited to failing items.
- Show the exact payload before submission, including Markdown and parser output.
- Never upload, persist, or transmit the source PDF.
- Include only the reference section, not the full extracted manuscript.
- Allow users to remove or edit individual lines/items before sending.
- Validate the payload client-side and server-side.
- Remove local paths, Zotero identifiers, account identifiers, and unrelated metadata.
- Store submissions in a private durable queue with explicit processing states.
- Record consent, parser version, failure category, and retention/deletion timestamps.
- Require human approval before any case becomes a public repository artifact.
- Run parser-agent work in an isolated, short-lived environment with no library access.
- Open draft PRs only; never merge automatically.
- Require regression tests and diagnostic evidence in generated PRs.
- Support deletion of raw submissions and retention of only approved sanitized fixtures.

### Design Decisions

| Decision | Options | Chosen | Rationale |
|----------|---------|--------|-----------|
| Data boundary | PDF; full extracted Markdown; reference Markdown only | Reference Markdown plus selected failing outputs | Meets the user’s explicit no-source constraint and minimizes disclosure. |
| Preview | Informational notice; editable exact payload | Editable exact payload | Users can verify precisely what leaves the app. |
| Intake | GitHub Issues; app-local queue; private API/database | Private API with durable database | Public repositories must not become the raw intake channel; containers may restart. |
| Deployment | Same app container; separate private services | Separate API, database, and worker containers/services | Limits permissions and isolates agent execution. |
| GCP runtime | Vertex Agent Engine; Cloud Run service/job; GKE | Cloud Run service plus Cloud Run Job | The feedback API is long-lived; parser work is finite and isolated. |
| Agent framework | No agent; repository-local skill runner; managed agent platform | Repository-local skill runner in a Cloud Run Job; optional ADK later | The existing parser-improvement skill is deterministic and repository-specific. |
| GitHub access | PAT; GitHub App; repository write token | Narrowly scoped GitHub App | Allows draft-PR creation with least privilege and revocation. |
| Publication gate | Automatic issue/PR; human-approved sanitized fixture | Human approval before publication | Markdown can still disclose unpublished work or identities. |
| Raw retention | Indefinite; delete immediately; time-limited | Time-limited with explicit deletion job | Enables review while limiting privacy exposure. |

### Scope

#### In Scope

- Feedback capture in the existing recheck flow.
- Exact preview, editing, consent, and submission status.
- Private feedback API and queue data model.
- Payload validation and sanitization.
- Admin review and approval state transitions.
- GCP deployment design using Cloud Run, Cloud SQL, Pub/Sub, Secret Manager,
  and optional private Cloud Storage.
- Isolated parser-improvement worker using approved Markdown and parser outputs.
- Draft PR creation, audit metadata, and failure reporting.
- Unit, integration, security, and end-to-end tests for the pipeline.

#### Out of Scope

- Uploading or processing source PDFs in the feedback system.
- Giving the worker access to Zotero, user files, or full manuscript text.
- Automatic merging, release publishing, or production deployment from a PR.
- General-purpose autonomous coding agents unrelated to parser failures.
- Publicly searchable feedback history.
- Automatic inference of the user’s intended correction without confirmation.

### Architecture Overview

```text
NiceGUI recheck screen
  └─ local payload builder (reference Markdown + selected failures)
      └─ exact preview/edit/consent
          └─ HTTPS private feedback API (Cloud Run)
              ├─ validates and sanitizes
              ├─ writes encrypted case to Cloud SQL
              └─ publishes approved-work event to Pub/Sub
                  └─ Cloud Run Job / isolated worker
                      ├─ checks out repository at pinned commit
                      ├─ runs parser-improvement diagnostics and tests
                      ├─ creates regression fixture/test if justified
                      └─ opens signed draft PR through GitHub App
```

The raw case and the public artifact are separate records. The public artifact
contains only the approved fixture, parser output, expected behavior, and
regression test. It must not contain the raw submission, account information,
local paths, or source-document content outside the selected reference section.

### Constraints

- The source PDF is prohibited from the feedback request, storage, logs, and
  worker filesystem.
- User-visible preview must represent the serialized request exactly.
- The public repository may receive only reviewed, sanitized artifacts.
- Existing recheck behavior must remain unchanged when feedback is declined.
- The queue must survive app/container restarts and support retries without
  duplicate PRs.
- Secrets must be runtime-injected and never committed to the repository or
  container image.
- The worker must be pinned to a repository commit and have a bounded timeout.
- Retention defaults must be configurable by deployment environment.

### Open Questions

- Which deployment region and institutional data-residency requirements apply?
- Is authentication available for app users, or is anonymous rate-limited intake required?
- What is the browser-to-NiceGUI-to-feedback-API trust path, and what CSRF protection is required?
- Where exactly does the reference-section Markdown come from in the current recheck pipeline?
- Which concrete API framework, database driver, and migration mechanism will be adopted?
- Who receives admin-review access and GitHub App ownership?
- What Cloud KMS key ownership, rotation, and field-level encryption strategy is required?
- Should users receive a case-status link, or should status remain in-app only?
- Which model/provider, if any, is authorized for agent reasoning over submitted Markdown?
- Does the source-PDF prohibition include repository fixtures used by parser tests, or only user PDFs?

## Implementation Plan

### Phase 1: Local feedback capture and exact preview

**Files to create:**
- `src/openrefcheck/feedback/__init__.py`
- `src/openrefcheck/feedback/models.py`
- `src/openrefcheck/feedback/payload.py`
- `tests/test_feedback_payload.py`

**Files to modify:**
- `src/openrefcheck/webui/pages/references.py`
- `src/openrefcheck/webui/state.py`
- relevant existing UI tests or fixtures discovered during implementation

**Steps:**
1. Identify the recheck result model and define a stable failure-item DTO.
2. Build a local payload containing only the reference-section Markdown and
   user-selected failing outputs.
3. Add editable preview, item deselection, client-side validation, and consent.
4. Ensure source PDF paths, bytes, handles, and full-manuscript Markdown cannot
   enter the payload object.
5. Add tests for exact serialization, empty selections, oversized content,
   Unicode, malicious Markdown, and declined consent.

**Depends on:** None

### Phase 2: Private intake API and durable queue

**Files to create:**
- `src/openrefcheck/feedback/api.py`
- `src/openrefcheck/feedback/repository.py`
- `src/openrefcheck/feedback/migrations/001_feedback_cases.sql`
- `tests/test_feedback_api.py`
- `tests/test_feedback_repository.py`
- `docker/feedback/Dockerfile`
- deployment configuration documented in `docs/`

**Files to modify:**
- `src/openrefcheck/webui/pages/references.py`
- `src/openrefcheck/webui/state.py`
- `pyproject.toml` or dependency manifest if an API/database client is required
- `docker-compose.yml` if the repository has or adds a local development stack

**Steps:**
1. Define the case schema and states: `received`, `sanitizing`, `needs_review`,
   `approved`, `rejected`, `processing`, `pr_opened`, `failed`, `deleted`.
2. Implement authenticated HTTPS submission with idempotency keys and rate limits.
3. Persist cases in PostgreSQL with encrypted sensitive fields and audit events.
4. Return a non-sensitive case identifier and status to the app.
5. Add retry-safe transitions and duplicate-submission handling.
6. Add local Docker Compose support for development without exposing database ports.

**Depends on:** Phase 1

### Phase 3: Sanitization, retention, and human review

**Files to create:**
- `src/openrefcheck/feedback/sanitize.py`
- `src/openrefcheck/feedback/review.py`
- `tests/test_feedback_sanitize.py`
- `tests/test_feedback_review.py`
- `docs/feedback-data-policy.md`

**Files to modify:**
- `src/openrefcheck/feedback/api.py`
- `src/openrefcheck/feedback/repository.py`
- `docs/eu-data-privacy-compliance.md` if the policy belongs there

**Steps:**
1. Enforce that submitted Markdown is reference-section content and apply size limits.
2. Detect and remove paths, Zotero keys, account IDs, hidden metadata, and
   unrelated extracted sections.
3. Provide an admin view showing raw case, proposed sanitized artifact, and a
   side-by-side diff before approval.
4. Require explicit approval to create a public fixture or trigger the worker.
5. Implement retention jobs, deletion confirmation, and audit logging.
6. Add tests proving PDFs and full-manuscript content are rejected and never logged.

**Depends on:** Phase 2

### Phase 4: Isolated parser worker and draft PR

**Files to create:**
- `src/openrefcheck/feedback/worker.py`
- `src/openrefcheck/feedback/github_app.py`
- `tests/test_feedback_worker.py`
- `tests/test_github_app.py`
- `docker/parser-feedback-worker/Dockerfile`
- `.github/` workflow or deployment manifests as selected during implementation
- `docs/parser-feedback-operations.md`

**Files to modify:**
- `src/openrefcheck/feedback/repository.py`
- `pyproject.toml` or dependency manifest for worker/GitHub clients
- CI configuration for fixture and parser regression checks

**Steps:**
1. Consume only approved sanitized cases from Pub/Sub or a durable claim table.
2. Build an isolated worktree from a pinned repository commit with a bounded
   filesystem, timeout, and no Zotero/PDF mounts.
3. Run the repository’s parser-improvement diagnostics and existing test suite.
4. Require the worker to produce a minimal regression fixture and test only when
   a reproducible parser defect is demonstrated.
5. Validate generated diffs for forbidden content before publication.
6. Create a signed draft PR through a least-privilege GitHub App and persist its URL.
7. Mark cases failed with actionable diagnostics; retry transient failures safely.

**Depends on:** Phase 3

## Verification & Validation

- **Automated:** unit tests for payload boundaries, sanitization, state transitions,
  idempotency, retention, and GitHub request formation.
- **Automated:** integration tests using a disposable PostgreSQL instance and a
  fake GitHub API; assert no PDF bytes or forbidden fields are sent.
- **Automated:** container image scan, dependency scan, secret scan, and CI tests
  on every worker change.
- **Automated:** end-to-end test from a synthetic recheck failure to a draft-PR
  request using only synthetic reference Markdown.
- **Manual:** inspect the exact user preview and serialized payload.
- **Manual:** attempt submission with a source-PDF path, PDF bytes, full manuscript,
  Zotero key, and prompt-injection text; confirm rejection or safe treatment.
- **Manual:** approve/reject/delete cases and verify audit history and retention.
- **Manual:** verify generated PR contains only approved fixture content, regression
  tests, diagnostic summary, and the required AI signature.
- **Operational:** verify backups, restore procedure, alerting, rate limits, and
  least-privilege IAM in the chosen GCP project.

## Dependencies

- Existing recheck result and reference-section extraction interfaces.
- A private deployment project with Cloud Run, Cloud SQL, Pub/Sub, Secret Manager,
  and appropriate logging/monitoring enabled.
- GitHub App installation limited to branch and draft-PR creation.
- A repository checkout available to the worker at a pinned revision.
- The parser-improvement skill and its diagnostic scripts included in the worker
  image or available from the checked-out repository.
- Data-protection review covering consent, retention, deletion, and region.

## Notes

- The initial deployment should use the balanced tier: private intake plus human
  approval before the worker and public PR.
- Vertex AI Agent Engine/ADK is optional. The first worker should use the existing
  deterministic parser-improvement workflow; introduce an agent framework only
  when tool orchestration or evaluation needs justify it.
- Raw submissions and public fixtures must have separate storage identifiers and
  separate access-control policies.

## Review Feedback

### Independent review: iteration 1

A fresh review agent compared this plan with the current repository and found
the following gaps. These are recorded as implementation prerequisites rather
than silently assumed decisions.

#### Blockers

- The repository is currently a local NiceGUI prototype. It has no feedback
  action, API, database abstraction, authentication layer, migration tooling,
  or deployment stack. The plan must select concrete technologies and file
  boundaries before implementation.
- The plan does not identify the existing source of reference-section Markdown
  or define a stable recheck-result/failure-item DTO. Phase 1 must first map the
  current extraction and result interfaces.
- “Authenticated HTTPS” is unresolved. The design must choose user identity or
  anonymous intake, then define browser-to-NiceGUI-to-API trust, CSRF protection,
  rate limiting, and case ownership.
- Cloud SQL field encryption is underspecified. The deployment design must name
  the KMS/key ownership, rotation, and field-level encryption approach.
- Retention and deletion currently omit database backups, Pub/Sub retries and
  dead-letter topics, logs/traces, worker disks, and GitHub PR artifacts.
- Cloud Run Jobs alone are not a complete hostile-input sandbox. The worker needs
  explicit filesystem, timeout, network-egress, dependency, and permission
  boundaries.

#### Warnings

- Pub/Sub messages should contain only opaque case IDs; raw Markdown and parser
  outputs must remain in the private database or private object storage.
- Sanitization cannot prove from text alone that content is only a reference
  section. The design needs provenance from the local extraction pipeline and/or
  an explicit user-confirmed allowlist, plus maximum sizes.
- Define worker network egress, pinned dependencies and image digests, the exact
  repository checkout contents, and handling that prevents user PDF bytes or
  paths from entering logs, diffs, fixtures, or PRs.
- The plan must clarify whether “never share the source PDF” prohibits only user
  PDFs or also repository test fixtures that happen to be PDFs.
- GitHub integration needs explicit App permissions, branch and PR idempotency,
  duplicate handling, and a commit/signature policy. The required AI signature
  must have a defined provenance and format.
- The state machine needs explicit `sanitization_failed`, review authorization,
  retry, cancellation, and deletion transitions, together with transition
  invariants and an audit-actor model.
- GCP deployment needs concrete region/data-residency, VPC/ingress, IAM service
  accounts, Cloud SQL connectivity, Pub/Sub authentication, logging, monitoring,
  and backup configuration.
- A public draft PR can disclose sanitized but unpublished research context. The
  public-artifact consent gate and threat model must be explicit, separate from
  consent to submit a private case.

#### Suggestions

- Add a pre-implementation architecture spike that maps current NiceGUI state,
  recheck results, and extraction boundaries before choosing API contracts.
- Add a synthetic-only staging environment that exercises the complete pipeline.
- Add a data-flow diagram showing every copy of raw and sanitized data,
  including backups and observability systems.
- Add operational runbooks for deletion requests, compromised credentials,
  failed workers, duplicate PRs, and rollback.

The plan is therefore reviewed in one iteration with 6 blockers, 8 warnings,
and 4 suggestions recorded. These findings must be resolved or explicitly
accepted before implementation starts.
