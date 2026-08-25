# Agent Instructions

## Clean-room development

- Follow [the clean-room development policy](docs/clean-room-development-policy.md) for MetaCheck and any other overlapping third-party implementation.
- Do not inspect, clone, fetch, quote, translate, summarize, or use competitor source code, tests, prompts, regular expressions, templates, fixtures, or internal schemas for an independently implemented module.
- Use public standards, primary literature, official API documentation, approved behaviour-level requirements, and independently created test material.
- Keep black-box evaluation outputs separate from implementation details. Do not infer or transmit competitor internals.
- Never provide prohibited third-party material to an AI system or ask an AI system to port, rewrite, or reconstruct it.
- Record module, dependency, data, prompt, test, and fixture provenance. Disclose prior exposure or licensing uncertainty before coding.
- Stop and quarantine affected work if contamination is suspected; escalate it to the project lead and university legal or open-source compliance contact.
- A licensed integration requires an explicit project decision and license review; public availability alone is not authorization to copy.
