# Clean-room Development Policy

_Recommended project policy - 22 July 2026_

## Purpose

This policy allows the Manuscript Verification System to learn from lawful black-box evaluation of competing products while producing an original implementation. It applies to MetaCheck and to any other third-party system whose license or ownership is incompatible with the architecture or licensing model selected for this project.

The policy is a development and evidence-control procedure, not legal advice. The university's legal counsel or open-source compliance function must review material licensing decisions before production integration or release.

## Current clean-room baseline

As of 22 July 2026, the project documentation work has used MetaCheck's public website, public example report, package documentation and index, repository metadata and README, release information, changelog, and license information. It has not inspected, copied, cloned, or analyzed MetaCheck implementation files, tests, prompts, regular expressions, templates, or internal schemas.

Record any future change to this baseline in the project decision log before implementation work continues.

## Choose one route explicitly

For every third-party component, the project must record one of two routes:

1. **Independent clean-room implementation.** The project may evaluate observable behaviour, but implementation contributors must not access protected implementation material. This policy applies in full.
2. **Authorized licensed integration.** The project intentionally adopts, modifies, links to, wraps, or contributes to the component under its license. Legal and open-source compliance review must first establish the obligations for deployment, network use, source availability, notices, modifications, and interaction with other components.

The routes must not be mixed informally. Selecting clean-room implementation does not permit copying with renamed identifiers, translation to another language, close paraphrase, AI-assisted transformation, or reconstruction from source-derived pseudocode. Selecting licensed integration does not remove the license obligations.

## Roles and information barrier

Where feasible, use separate people for competitor evaluation and independent implementation.

### Evaluation team

The evaluation team may:

- Read public product descriptions, user documentation, published papers, standards, and license information.
- Operate a lawfully obtained release through its documented user interface or public API.
- Run the approved black-box benchmark and record inputs, observable outputs, performance, failures, and high-level capabilities.
- Produce behaviour-level requirements and benchmark statistics.

The evaluation team must not send implementation contributors:

- Third-party source code or excerpts.
- Source-derived algorithms, pseudocode, control flow, regular expressions, prompts, schemas, tests, fixtures, or implementation-specific naming.
- Close reproductions of report text, user-interface wording, or other expressive material.
- Instructions to reproduce undocumented internals.

### Implementation team

The implementation team may use the approved requirements, independently annotated benchmark corpus, primary standards, published research methods, and project-owned designs. It must create the architecture, algorithms, prompts, rules, tests, fixtures, wording, and user experience independently.

Implementation contributors must not browse, clone, fetch, decompile, or otherwise inspect third-party implementation repositories or distributed implementation files for a clean-room module. A contributor who has already had material exposure must disclose it before taking ownership of the overlapping module.

Small teams that cannot maintain full personnel separation must use a documented process barrier: one person records only behaviour-level observations, a second review removes source-derived detail, and implementation begins only from the approved requirements. Material exposure still disqualifies a contributor from independently implementing the affected module unless counsel approves a mitigation.

## Permitted sources for independent implementation

Use sources that describe facts, interfaces, standards, or scientific methods independently of the competitor, including:

- Laws, regulations, standards, and public specifications.
- Peer-reviewed papers and other primary scientific sources.
- Official documentation for independently selected dependencies and public APIs.
- Project-owned requirements, architecture decisions, and finding schemas.
- Independently created or properly licensed manuscripts, annotations, test cases, and controlled perturbations.
- Behaviour-level black-box observations approved under this policy.

Every implementation requirement should be traceable to at least one permitted source or an original project decision.

## Prohibited material and activities

For clean-room modules, do not:

- Copy, translate, transcompile, adapt, paraphrase, or port third-party code.
- Inspect or reuse third-party tests, fixtures, prompts, regular expressions, templates, internal schemas, comments, build files, or undocumented APIs.
- Reproduce distinctive report language, UI text, interaction design, or example data unless separately licensed or unavoidable for interoperability.
- Ask a person or AI system to summarize, explain, translate, port, or reimplement prohibited material.
- Paste or upload prohibited material to an AI assistant, code-completion system, issue, chat, or project document.
- Use generated output when its provenance is unclear or when the prompt was based on prohibited material.
- Treat public repository availability as permission to ignore its license.

If interoperability requires observation or interface reproduction, obtain a specific legal review and document the exact boundary before work begins.

## Requirements and provenance records

Before implementing an overlapping capability, create an independent, reviewable specification that states:

- The user problem and intended decision-support outcome.
- Inputs, outputs, confidence, evidence, and failure states.
- Behaviour derived from standards or primary literature.
- Behaviour observed through black-box testing, described without implementation conjecture.
- Privacy, security, accessibility, and institutional-hosting constraints.
- Sources and licenses for datasets, dependencies, models, and other assets.

Each module must maintain a provenance record with at least:

- Module owner and reviewers.
- Implementation route: `clean-room` or `licensed integration`.
- Permitted sources used, including versions and access dates.
- Contributor exposure declarations.
- Dependencies and their licenses.
- Origin of tests, fixtures, prompts, and rule sets.
- Review date and unresolved compliance questions.

Use SPDX identifiers and machine-readable notices where practical, and adopt the [REUSE Specification](https://reuse.software/spec/) for repository-wide license and copyright metadata.

## Black-box benchmarking rules

Any comparative benchmark against a third-party system is permitted only as a black-box evaluation while the independent route remains under consideration.

- Use documented interfaces and a pinned, lawfully obtained release.
- Keep the benchmark runtime isolated from the implementation environment.
- Benchmark against independently annotated ground truth; never treat either system's output as truth.
- Record inputs, observable outputs, timings, resource use, errors, and operator-visible configuration.
- Do not inspect installed source or runtime internals to diagnose behaviour.
- Share aggregate metrics and behaviour-level findings with implementers, not raw third-party artifacts when those artifacts contain distinctive expressive content.
- Do not copy competitor-generated wording into project reports, training data, tests, or product output.

If the project later selects authorized licensed integration, place that work in an explicitly approved integration track and apply the component's license and notice requirements.

## Contributor and review controls

The contribution template and code review process should require contributors to confirm that:

- The contribution is original or all reused material is identified and compatible.
- No prohibited third-party material was used or supplied to an AI system.
- New dependencies and data sources have recorded licenses and provenance.
- Tests and fixtures are original, independently licensed, or clearly attributed.
- Any prior exposure to an overlapping implementation has been disclosed.

Reviewers should compare architecture and behaviour against the independent specification, not against competitor source. Similarity checks may be used as a final safeguard, but they do not replace provenance records and must not require importing competitor source into the development environment.

## Suspected contamination procedure

If prohibited material may have influenced a contribution:

1. Stop work on the affected module and do not merge or release it.
2. Quarantine the branch, generated artifacts, prompts, and communications without spreading the material further.
3. Record who was exposed, what material was involved, when exposure occurred, and which files may be affected.
4. Notify the project lead and university legal or open-source compliance contact.
5. Decide whether to remove the contribution, reimplement it from the independent specification using unexposed contributors, or switch formally to an authorized licensed-integration route.
6. Document the decision and complete a new provenance review before work resumes.

Do not attempt to cure copying merely by renaming, reformatting, translating, or asking an AI system to rewrite the material.

## Legal context and review points

The [EU Software Directive 2009/24/EC](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32009L0024) distinguishes protected expression from ideas and principles and contains specific rules on observing, studying, testing, and interoperability. Its application depends on the facts and the user's lawful rights; obtain counsel for edge cases.

MetaCheck is published under [AGPL-3.0-or-later](https://www.gnu.org/licenses/agpl-3.0.en.html). If the project adopts or modifies MetaCheck rather than independently implementing a capability, review network-source, distribution, notice, and combined-work implications. The [GNU license FAQ](https://www.gnu.org/licenses/gpl-faq.en.html) is useful background but is not a substitute for institution-specific legal advice.

Review this policy whenever the project changes its license, begins external service operation, adds an overlapping competitor-derived capability, accepts a substantial external contribution, or changes its AI development tooling.
