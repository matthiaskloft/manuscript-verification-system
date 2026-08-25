# EU Data, Privacy, and AI Compliance Requirements

_Discussion draft - last reviewed 22 July 2026_

> **Relation to [project-plan.md](project-plan.md#datenschutz-dsgvo):** `project-plan.md` already has its own, MVP-scoped "Datenschutz (DSGVO)" section covering Phase A (local app) and the Phase A→B transition gate. This document is the broader, longer-term checklist for the full institutional, multi-tenant service (Phase B and beyond) described in [open-stack-proposal.md](open-stack-proposal.md), including EU AI Act readiness that only becomes relevant once an LLM-based module (Stufe 3) is introduced. Treat the two documents as complementary, not duplicate: `project-plan.md` for what's required to ship the current MVP, this document for what's required before the full service vision goes into production.

## Status and scope

Compliance with applicable EU and national data-protection, privacy, cybersecurity, and AI law is a mandatory product requirement for the Manuscript Verification System.

This document is an engineering and governance checklist, not legal advice. Before production use, it must be reviewed and adapted by the hosting university's Data Protection Officer, legal counsel, information-security function, and relevant research-integrity or ethics governance.

The primary legal baseline is the [General Data Protection Regulation](https://eur-lex.europa.eu/eli/reg/2016/679/oj). Any AI-assisted component also requires an applicability and classification assessment under the [EU AI Act](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai). Applicable national laws, employment rules, confidentiality duties, institutional policies, contracts, and sector-specific requirements must be added for each deployment.

## Data in scope

Treat the following as potentially personal or confidential data:

- Author, reviewer, editor, and staff identities and contact details
- ORCID iDs, affiliations, employment information, and contribution statements
- Conflicts of interest, funding, ethics, and correspondence records
- Unpublished manuscript text, figures, tables, equations, supplements, data, and code
- Peer-review reports and editorial decisions
- Research-integrity findings, allegations, comments, overrides, and escalation records
- Authentication, access, usage, telemetry, and audit logs
- Information retrieved from external scholarly services and linked to identifiable people
- Special-category or highly sensitive information contained in manuscripts or case files

Unpublished manuscripts may also contain intellectual property, confidential research, security-sensitive information, or data subject to contractual restrictions even where the content is not personal data.

## GDPR principles

The architecture and institutional configuration must implement:

- **Lawfulness, fairness, and transparency:** define and document an appropriate lawful basis for every processing purpose and explain processing in clear language.
- **Purpose limitation:** do not reuse manuscripts or findings for unrelated analytics, product development, or model training without a separately assessed purpose and lawful basis.
- **Data minimization:** process and disclose only the content required for each check.
- **Accuracy:** distinguish verified facts, uncertain matches, automated inferences, and human decisions; provide correction and override mechanisms.
- **Storage limitation:** apply configurable retention schedules and verifiable deletion.
- **Integrity and confidentiality:** protect data against unauthorized access, loss, alteration, and disclosure.
- **Accountability:** retain evidence that these requirements are designed, configured, tested, and reviewed.

The European Commission summarizes these principles in its guidance on [what data organizations may process and under which conditions](https://commission.europa.eu/law/law-topic/data-protection/rules-business-and-organisations/principles-gdpr/overview-principles/what-data-can-we-process-and-under-which-conditions_en).

## Governance requirements

Before deployment, document:

- The data controller, joint controllers, processors, and subprocessors
- The purpose and lawful basis for each processing activity
- Categories of data subjects and personal data
- Data sources, recipients, storage locations, and transfer routes
- Retention and deletion schedules
- Data-subject request procedures
- Security measures and access roles
- External services and the exact fields disclosed to each
- Whether a Data Protection Impact Assessment is required
- Whether prior consultation with a supervisory authority is required
- Ownership of incident response, complaints, and regulatory communication

Maintain records of processing activities and version them when modules, purposes, recipients, or deployment architecture change.

## Data protection by design and default

- Keep manuscripts and detailed findings on university-controlled infrastructure by default.
- Send only identifiers or minimal bibliographic fields to external metadata APIs.
- Make every external integration independently configurable and disableable.
- Use local mirrors or caches where legally and technically appropriate.
- Separate tenants, journals, cases, and roles at the authorization and storage layers.
- Apply least-privilege access and time-limited administrative elevation.
- Encrypt data in transit and at rest using institutionally approved controls.
- Separate operational telemetry from manuscript content.
- Avoid placing manuscript text, author names, or case details in application logs.
- Pseudonymize benchmark and analytics data where possible.
- Provide secure deletion for originals, derived text, equation crops, embeddings, caches, reports, backups, and temporary files.
- Test backup restoration and ensure retention rules extend to backups.

## Data-subject transparency and rights

Provide appropriate notices explaining:

- Who operates the service and how to contact the controller and Data Protection Officer
- Why the data is processed and the applicable lawful basis
- What automated checks are performed
- Which external services receive data
- How long data and findings are retained
- Who can access reports and decisions
- Whether data leaves the EEA
- How people can exercise applicable access, correction, deletion, restriction, portability, and objection rights
- How to contest an automated finding or request human review

The system must support institutional response workflows without silently deleting evidence that must be retained for a lawful investigation or appeal. Conflicting legal and retention requirements must be resolved by institutional policy, not hard-coded globally.

## Human decision-making

Automated findings are decision support. They must not independently:

- Reject or accept a manuscript
- Accuse a person of misconduct or fraud
- Apply sanctions or block future submissions
- Determine employment, funding, reputation, or disciplinary outcomes
- Create an irreversible risk classification

Editors or authorized integrity staff must review material findings, see the underlying evidence and uncertainty, record their rationale, and be able to override the result. The institution must assess the applicability of GDPR rules on automated individual decision-making, including Article 22, for each workflow.

## External services and international transfers

For every API, hosted model, telemetry system, support tool, or cloud service:

- Record the provider, location, terms, privacy documentation, subprocessors, and retention behavior.
- Specify the exact fields transmitted and whether they contain personal or confidential data.
- Establish an Article 28 data-processing agreement where required.
- Determine whether data is transferred outside the EEA.
- Use an applicable adequacy decision or appropriate safeguards and complete required transfer assessments.
- Provide an institutional kill switch and a local fallback where feasible.

The European Commission notes that GDPR protection continues when data is transferred outside the EU and describes the available [international-transfer mechanisms](https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/obligations/what-rules-apply-if-my-organisation-transfers-data-outside-eu_en).

## AI Act readiness

The initial system should prefer deterministic rules and openly documented statistical or symbolic methods. Before adding an AI component:

- Record whether the project is the provider, deployer, importer, distributor, or user of the component.
- Define and constrain the intended purpose.
- Assess the AI Act risk classification and applicable dates with legal counsel.
- Document training-data and model provenance where available.
- Evaluate accuracy, robustness, cybersecurity, bias, and disciplinary performance.
- Provide logging and traceability from finding to model, prompt, configuration, and input context.
- Make uncertainty and known limitations visible.
- Establish meaningful human oversight and escalation.
- Meet applicable transparency obligations when users interact with AI or receive AI-generated content.
- Maintain AI-literacy measures for staff operating or interpreting the system.
- Monitor incidents, material changes, and model updates after deployment.

The European Commission identifies documentation, logging, human oversight, robustness, cybersecurity, and accuracy among the central requirements for regulated AI systems. Its [AI Act overview](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai) and [Article 50 transparency guidance](https://digital-strategy.ec.europa.eu/en/library/guidelines-transparency-obligations-providers-and-deployers-ai-systems) should be monitored for updates.

No manuscript, reviewer report, editorial correspondence, or integrity case may be used to train or fine-tune a model by default. Any exception requires a distinct purpose, legal assessment, governance approval, data minimization, documented provenance, retention rules, and appropriate notice or consent where applicable.

## Security and incident response

- Complete threat modeling before production deployment.
- Use institutionally managed identity, MFA where appropriate, secrets management, and vulnerability management.
- Isolate document parsers, OCR, code inspection, and third-party workers because manuscripts and attachments are untrusted input.
- Apply file-type validation, malware scanning, resource limits, timeouts, and sandboxing.
- Maintain immutable or tamper-evident audit events for access and decisions.
- Define detection, containment, investigation, recovery, and notification responsibilities.
- Support GDPR personal-data breach assessment and notification timelines.
- Test incident and disaster-recovery procedures periodically.

## Benchmarking and development data

- Use publicly licensed or institutionally authorized manuscripts.
- Maintain a legal-use and provenance record for every benchmark item.
- Separate natural manuscripts from deliberately perturbed test copies.
- Remove unnecessary direct identifiers from evaluation datasets.
- Restrict access to ground truth, integrity annotations, and sensitive cases.
- Do not publish manuscripts, annotations, or system outputs unless the legal basis and license permit it.
- Apply the same retention and deletion controls to benchmark artifacts as to production data.

## Minimum release gates

Production deployment requires documented approval or acceptance of:

- Data-flow and system-context diagrams
- Record of processing activities
- Privacy notice and user information
- Controller/processor and subprocessor arrangements
- Retention and deletion policy
- Data-subject request procedure
- DPIA screening and, where required, completed DPIA
- International-transfer assessment
- Security architecture, threat model, and penetration-test plan
- Incident and breach-response procedure
- AI Act applicability and classification assessment
- Human-review and appeal workflow
- External-service allowlist
- Institutional DPO, legal, and information-security review

Compliance is continuous. A new check, external data source, model, user group, purpose, or deployment region must trigger a change assessment rather than inherit approval automatically.
