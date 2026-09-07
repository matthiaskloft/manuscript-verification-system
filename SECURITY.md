# Security policy

## Reporting a vulnerability

Please report security issues privately, through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository (Security → Report a vulnerability), rather than by opening a
public issue.

OpenRefCheck is a research prototype maintained by one person, without a paid support
arrangement or a guaranteed response time. Expect a considered reply rather than a
fast one, and no bug bounty.

## Scope

The interesting boundary is the difference between the two ways OpenRefCheck runs.

**The desktop app** (`openrefcheck`) treats the person at the keyboard as trusted. It
writes reports to filesystem paths they choose, and reads documents they point it
at. That is the intended behaviour and not a vulnerability.

**A hosted instance** (`openrefcheck-web`) treats every visitor as untrusted. There it
accepts uploaded manuscripts, and the report is downloaded through the browser
rather than written to a server path. Anything that lets a visitor read another
visitor's manuscript, read or write server-side files, run code on the host, or
retain an upload past the deletion the UI promises is in scope.

Also in scope: manuscript content reaching a third party beyond the title, author,
and DOI fields sent to OpenAlex and Crossref for verification.

## Known limitations, by design

These are properties of the deployment rather than defects, and are documented in
[README.md](README.md) and
[docs/demo-deployment-decision.md](docs/demo-deployment-decision.md):

- **No authentication.** The app ships without a login. An instance meant for a
  restricted audience needs access control in front of it.
- **No rate limiting.** Abuse is bounded by the deployment's instance cap, not by
  the application.
- **Uploads are processed server-side.** A hosted instance necessarily sees the
  manuscripts uploaded to it. This is why demo mode says so on screen, and why the
  demo should be pointed at synthetic or already-public documents.
- **GROBID must not be public.** It is compute-heavy and unauthenticated; expose it
  only to the app's own service identity.

If you are deploying this for other people, read the "Before you expose it to other
people" section of the README and
[docs/eu-data-privacy-compliance.md](docs/eu-data-privacy-compliance.md) first.
