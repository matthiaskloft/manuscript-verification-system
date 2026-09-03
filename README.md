# OpenRefCheck

OpenRefCheck is a [NiceGUI](https://nicegui.io/) app that checks a manuscript's
references. It extracts the reference list from a PDF or DOCX, verifies each entry
against [OpenAlex](https://openalex.org/) and [Crossref](https://www.crossref.org/),
and flags entries that cannot be found, are incomplete, are duplicated, or have been
retracted. It also matches in-text citations back to the reference list, so orphaned
citations and never-cited entries become visible, and exports the result as a
self-contained HTML report.

It runs two ways from the same code: as a local desktop app, where the manuscript
never leaves the machine, and as a web server, which is what the hosted demo uses.

Background: [docs/project-plan.md](docs/project-plan.md). Reference extraction can
optionally use [GROBID](https://grobid.readthedocs.io/); without it a built-in
extractor handles the job at lower accuracy.

## Requirements

- Python >= 3.11
- (Optional) [Docker](https://www.docker.com/), to run GROBID locally for
  higher-quality reference extraction

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows Git Bash: source .venv/Scripts/activate
pip install -e ".[dev,native]"
```

`pyproject.toml` is the source of truth for dependencies.
[requirements.txt](requirements.txt) is a fully pinned snapshot of one resolved
install, for reproducing exact versions; it is captured on Linux/CPython 3.11 and
pins platform-specific wheels, so install from `pyproject.toml` on Windows.

The `native` extra (pywebview) is only needed for the desktop entry point. The web
entry point does not require it.

## Running the desktop app

```bash
openrefcheck
```

Opens a native desktop window. Equivalently: `python -m openrefcheck.app`.

## Running the web app

```bash
openrefcheck-web
```

Serves the same app over HTTP on `0.0.0.0` and the `PORT` env var (default `8080`).
This is what [docker/nicegui/Dockerfile](docker/nicegui/Dockerfile) runs:

```bash
docker build -f docker/nicegui/Dockerfile -t openrefcheck-web .
docker run --rm -p 8080:8080 -e GROBID_URL=http://host.docker.internal:8070 openrefcheck-web
```

The two entry points differ in one way that matters beyond the window: the desktop
app can write a report to a filesystem path you choose, and the web app cannot —
there it downloads through your browser instead. That is deliberate. On a server the
path would name the *server's* filesystem, so honouring it would be both useless to
you and a way for any visitor to write files on the host.

## Configuration

All configuration is environment variables. None are required to run.

| Variable | Purpose | Default |
| --- | --- | --- |
| `OPENREFCHECK_CONTACT_EMAIL` | Contact address sent to OpenAlex and Crossref to enter their "polite pool" (faster, more reliable service). See below. | unset (anonymous) |
| `OPENALEX_API_KEY` | Free OpenAlex key; raises the daily budget from ~1,000 to ~10,000 requests (see below) | unset (anonymous) |
| `GROBID_URL` | Base URL of a running GROBID instance | `http://localhost:8070` |
| `OPENREFCHECK_DEPLOYMENT_MODE` | Which disclaimer the UI shows: `local`, `demo`, or `prod` | `local` |
| `OPENREFCHECK_DEV` | Enables development-only UI affordances (`1`/`true`/`yes`) | unset |
| `OPENREFCHECK_NATIVE_DEBUG` | Opens the native window's devtools (right-click → Inspect, or F12) for diagnosing a native-only rendering issue | unset |

### Contact address

OpenAlex and Crossref both run a "polite pool": callers who identify themselves with
a contact address get faster and more reliable service than anonymous ones. OpenRefCheck
sends one only if you set it:

```bash
export OPENREFCHECK_CONTACT_EMAIL=you@example.org
```

There is deliberately no default. The address is transmitted to a third party on
every reference lookup, so a compiled-in one would mean every fork and every
self-hosted deployment announcing whoever built the software, and attributing that
traffic to someone with no control over it. Unset simply means the anonymous pool:
slower, and entirely functional.

Set it to an address **you** own before running anything at volume.

### OpenAlex daily budget

OpenAlex meters callers against a **daily budget** rather than a request rate. An
anonymous caller gets $0.10/day — about **1,000 requests**. A check asks OpenAlex
once per reference, so roughly **30 full checks a day** exhaust it.

When the budget runs out nothing fails: the check still completes and the reference
verdicts are unchanged. What disappears is everything only OpenAlex supplies —
abstracts, topics, keywords, and its citation counts — and a retraction that Crossref
has not recorded stops being caught. The app says so on screen rather than showing
empty fields, but the degradation is silent if you are not reading the message.

A **free** API key raises the budget tenfold, to 10,000 requests/day. Get one at
[openalex.org/settings/api](https://openalex.org/settings/api) and set it:

```bash
export OPENALEX_API_KEY=your-key-here
```

Recommended for any real use. There is no paid tier involved and no account cost.

## Optional: running GROBID locally

Reference extraction falls back to a built-in extractor when GROBID is unavailable.
To enable GROBID-based extraction:

```bash
docker run --rm -p 8070:8070 grobid/grobid:0.8.1
```

The app looks for GROBID at `http://localhost:8070` by default; override with
`GROBID_URL`. [docker/anystyle/Dockerfile](docker/anystyle/Dockerfile) packages the
AnyStyle CLI used by the extraction benchmarks.

## Deploying your own instance

OpenRefCheck is deployable by anyone; nothing in the repository is tied to a particular
cloud account. [docs/demo-deployment-decision.md](docs/demo-deployment-decision.md)
records the reasoning behind the reference deployment (two Google Cloud Run services
— the app, and a private GROBID backend it alone may invoke) along with the service
sizing, cold-start measurements, and cost controls.

[scripts/deploy-web.ps1](scripts/deploy-web.ps1) builds, tags, pushes, and redeploys
in one step against **your** project:

```powershell
.\scripts\deploy-web.ps1 -Project my-gcp-project -Region europe-west3
```

or set `OPENREFCHECK_GCP_PROJECT` and run it with no arguments. It needs `docker` and
`gcloud` on PATH and authenticated.

Nothing about the app requires Cloud Run — the container is an ordinary web server
and will run on any host that can serve one.

### Before you expose it to other people

The hosted configuration processes other people's manuscripts, which raises
questions a local install does not. Read
[docs/eu-data-privacy-compliance.md](docs/eu-data-privacy-compliance.md) before
running a public instance, and at minimum:

- **Decide whether it should be public at all.** There is no authentication in
  front of the app. Put one there, or restrict access at the network level, if the
  instance is not meant for anyone who finds the URL.
- **Keep GROBID private.** It is compute-heavy and unauthenticated by default; the
  reference deployment makes it invokable only by the app's service account.
- **Cap the instance count.** `--max-instances=1` is the ceiling on what an abusive
  caller can spend. A billing budget alerts, it does not cap.
- **Set `OPENREFCHECK_DEPLOYMENT_MODE=demo`** so visitors see the disclaimer describing
  server-side processing, rather than the local-processing one.
- **Check the retention copy still matches the code.** Demo mode tells visitors
  their upload is deleted when the check finishes and when they close the tab; that
  is what `openrefcheck/webui/pages/upload.py` does today, and the promise is only as
  true as that module.

Uploads are held in a private temporary directory, capped at 50 MB (enforced
server-side, not only in the browser), deleted when a check completes or the browser
session ends, and swept at process start if a crash left anything behind.

## Tests

```bash
pytest
```

No test contacts an external service: extraction runs against synthetic fixtures and
the OpenAlex/Crossref clients are stubbed. The live-GROBID tests do probe `GROBID_URL`,
which defaults to localhost and skips when nothing answers.

## Benchmark scripts

Scripts under [scripts/](scripts) build synthetic benchmarks and evaluate
extraction/verification quality (e.g. `run_grobid_benchmark.py`,
`run_ensemble_benchmark.py`). Install the `benchmark` extra if needed:

```bash
pip install -e ".[benchmark]"
```

Benchmarks that call OpenAlex or Crossref honour `OPENREFCHECK_CONTACT_EMAIL` in the
same way the app does.

### Renamed from `REFCHECK_*`

These variables were `REFCHECK_*` before the package was renamed. The old names still
work and emit a `DeprecationWarning` naming the new one, so an existing deployment does
not break the moment the code updates — which matters most for
`OPENREFCHECK_DEPLOYMENT_MODE`: unset, it falls back to `local`, whose disclaimer tells
visitors their document never left their device. Set the new names and the fallback
becomes dead code.

## Security

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## License

[GNU Affero General Public License v3.0](LICENSE).

AGPL rather than a permissive license for one specific reason: OpenRefCheck is meant to
be run as a service, and the AGPL is the license that carries the obligation across
that boundary. Anyone who runs a modified version for other people to use has to
offer those users its source. Fork it, deploy it, build on it — improvements to a
tool the scientific community relies on should come back to the community.
