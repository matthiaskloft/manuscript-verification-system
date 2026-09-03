# Demo deployment decision

**Status:** Proposed — decision pending

**Last reviewed:** 2026-07-29

## Decision to make

Select a low-cost hosting arrangement for:

1. the NiceGUI demonstration application; and
2. a separately deployed GROBID backend.

This note concerns occasional demonstrations, not a production or
university-hosted service.

## Recommendation

Deploy both components as separate Google Cloud Run services in the same
European region, preferably `europe-west1` (Belgium) or `europe-west3`
(Frankfurt):

- expose the NiceGUI service to demo users;
- keep the GROBID service private and allow only the NiceGUI service account to
  invoke it;
- use request-based billing with zero minimum instances and a maximum of one
  instance per service.

Cloud Run is the strongest free-tier candidate because it can provide the
approximately 4 GB RAM recommended by GROBID for processing complete documents,
while scaling unused services to zero. Its request-based free tier currently
includes 180,000 vCPU-seconds, 360,000 GiB-seconds, and two million requests per
month. At 4 GiB, the memory allowance is equivalent to about 25 hours of active
GROBID time before accounting for the smaller NiceGUI service. A billing
account is nevertheless required, so this should be treated as a
cost-controlled deployment rather than a guarantee of a zero invoice.

Cloud Run supports public images from Docker Hub. The GROBID image can therefore
be deployed directly without retaining its large full image in a project-owned
Artifact Registry repository.

## Image tagging

Tag each `refcheck-web` image build with the short git commit SHA it was built
from, not just `:latest` — a mutable `:latest` gives no way to tell what code a
running revision actually has, and made an early deploy look "stuck" on a
pre-merge build. Push both tags; `:latest` stays a floating pointer to the
newest, and the SHA tag is what `gcloud run deploy` should reference so a
rollback is just redeploying an older SHA tag.

```bash
PROJECT=your-gcp-project     # scripts/deploy-web.ps1 takes these as parameters
REGION=europe-west3
TAG=$(git rev-parse --short HEAD)
docker build -f docker/nicegui/Dockerfile \
  -t $REGION-docker.pkg.dev/$PROJECT/refcheck/nicegui:$TAG \
  -t $REGION-docker.pkg.dev/$PROJECT/refcheck/nicegui:latest .
docker push $REGION-docker.pkg.dev/$PROJECT/refcheck/nicegui:$TAG
docker push $REGION-docker.pkg.dev/$PROJECT/refcheck/nicegui:latest

gcloud run deploy refcheck-web \
  --image=$REGION-docker.pkg.dev/$PROJECT/refcheck/nicegui:$TAG \
  --region=$REGION \
  --max-instances=1
```

> **Naming migration.** Everything in the codebase is now `openrefcheck`: the
> package, both console scripts, the environment variables (`OPENREFCHECK_*`), the
> temp directories, and the local AnyStyle image tag. The deploy script's defaults
> follow — it now targets the service `openrefcheck-web` and the Artifact Registry
> repository `openrefcheck`.
>
> **Cloud Run services and Artifact Registry repositories cannot be renamed.** Getting
> the deployed resources onto the new names means creating them and deleting the old
> ones, which **changes the public URL** — see "Renaming the deployed services" below.
> Until that is done, deploy with `-Service refcheck-web -Repository refcheck`, or set
> `OPENREFCHECK_RUN_SERVICE` / `OPENREFCHECK_AR_REPOSITORY`, to keep hitting the
> existing deployment.
>
> The `REFCHECK_*` variables are gone, not aliased. The currently deployed demo runs
> an image built from the legacy repository, which has its own copy of the old code and
> is unaffected. A service running *this* code and missing
> `OPENREFCHECK_DEPLOYMENT_MODE` does not fall back to local-mode copy either: the web
> entry point defaults to `demo` (`openrefcheck/app_web.py`).

## Proposed service configuration

| Setting | NiceGUI | GROBID |
| --- | --- | --- |
| CPU | 1 vCPU | 1 vCPU |
| Memory | 512 MiB to 1 GiB | 4 GiB |
| Minimum instances | 0 | 0 |
| Maximum instances | 1 | 1 |
| Concurrency | Low; one instance only | 1 |
| Request timeout | 3,600 seconds for WebSocket sessions | 300 seconds |
| Access | Public or restricted to demo participants | Private, service-to-service only |
| Container port | Cloud Run `PORT` | 8070 |
| Region | Same European region as GROBID | Same European region as NiceGUI |

Pin the GROBID version used by the existing benchmark
(`grobid/grobid:0.8.1`) initially. Changing versions or switching to the smaller
CRF-only image could change extraction quality and should follow a regression
benchmark. The CRF-only image is a possible optimization if cold-start time
proves unacceptable.

## Required application work

Before deployment:

- [x] add a minimal web-only container image that does not install the
      desktop-only native/pywebview dependencies — see
      [docker/nicegui/Dockerfile](../docker/nicegui/Dockerfile) and
      `openrefcheck.app_web:main` (the `openrefcheck-web` console script);
- [x] make NiceGUI listen on `0.0.0.0` and the Cloud Run `PORT` value rather
      than the prototype's native-only `127.0.0.1` default — done in
      `openrefcheck.app_web:main`;
- [x] configure `GROBID_URL` with the separate Cloud Run service URL (set at
      deploy time; `GROBID_URL` support already exists in
      `openrefcheck.extraction.grobid`);
- [x] attach a Google identity token to GROBID calls so that the backend does
      not need unauthenticated public access — see
      `openrefcheck.extraction.grobid._identity_token_header`, used by
      `is_grobid_available` and `extract_references_via_grobid`. Skipped for
      `localhost`/`127.0.0.1` (local dev, the native app's default). Requires
      the `refcheck-web` service's runtime service account to hold
      `roles/run.invoker` on `refcheck-grobid`:
      ```bash
      gcloud run services add-iam-policy-binding refcheck-grobid \
        --region=$REGION \
        --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
        --role="roles/run.invoker"
      ```
      (substitute `refcheck-web`'s actual runtime service account if it's not
      the default compute one; find it with
      `gcloud run services describe refcheck-web --region=$REGION --format='value(spec.template.spec.serviceAccountName)'`);
- [x] replace the current one-shot GROBID availability check with a visible
      starting state and retry behavior, because a scale-to-zero cold start can
      outlast the health-check timeout — see `openrefcheck.extraction.grobid`'s
      `wait_for_grobid` and `has_cold_start`, used by the Upload screen's engine
      status line. ("one-second" in the original wording was already stale: the
      health-check timeout has been 60s for a while. The defect was the *one
      shot*, not the timeout.) The screen probes once; only if that fails and
      the URL is non-local does it show "Starting GROBID — a first check after
      an idle period can take a minute…" and retry to a 180s deadline, then
      revise the line in place. A local URL still gets exactly one attempt, so a
      developer with no container running sees the fallback immediately.
      Deliberately limited to the status line: `extract_references` still uses
      the one-shot probe per extraction, because a check must not block for
      minutes — and by then the status line's wait has usually warmed the
      service.

      **Measured on the real deployment, 2026-08-16**, on the first request to
      `refcheck-web` revision `refcheck-web-00010-wrt` with `refcheck-grobid`
      scaled to zero:

      | T | Status line |
      | --- | --- |
      | 0s | `Checking…` — first probe issued |
      | 24s | still `Checking…` — Cloud Run is *holding* the request while the container starts |
      | 55s | `Starting GROBID — a first check after an idle period can take a minute…` |
      | 107s | `GROBID — reachable at https://refcheck-grobid-…` |

      This replaces the "roughly a minute" estimate above, which was low. Three
      things the measurement settles that guessing did not:

      - **A cold start really does outlast `_HEALTH_CHECK_TIMEOUT`.** Cloud Run
        held the first probe as expected, but GROBID's model load ran past the
        60s timeout, so the retry loop — not the held request — is what got the
        answer. Both halves of the mechanism were needed.
      - **Without the retry the demo would have been wrong for the whole
        session**, reporting "not reachable, falling back" from 60s onward while
        GROBID came up 47s later, and running every check on the built-in parser.
      - **180s is the right deadline, with less headroom than intended.** It is
        1.7× the observed 107s, not the 3× the estimate implied. A 120s deadline
        would have been marginal. Do not lower it without re-measuring, and
        re-measure if the GROBID image or its memory allocation changes;
- [x] limit upload size (50 MB) and hold uploads in temporary storage only,
      deleting them once they are no longer needed — see
      `openrefcheck/webui/pages/upload.py`.

      Both halves of this were weaker than an earlier version of this note
      claimed, and both are now as described.

      **The size limit is enforced twice, and only the second one counts.**
      `ui.upload`'s `max_file_size` is a Quasar prop: it constrains the browser's
      file picker and means nothing to a direct POST at the upload endpoint,
      which on this deployment is public and unauthenticated. `handle_upload`
      therefore re-checks `file.size()` server-side before staging anything.

      **Deletion covers every way a session ends, not just the happy one.** A
      finished check deletes its own upload, as it always did; a check that
      failed, was cancelled, or was simply abandoned used to leave the manuscript
      on the instance with nothing left to remove it. A per-client disconnect
      handler now deletes it when the browser session ends, and a sweep at
      process start clears anything a crash left behind. The demo's retention
      copy (`openrefcheck/gui/deployment.py`) states exactly those two events;
      "immediately after processing" was the overstatement it replaced;
- [x] create a billing budget and alerts, and retain `max-instances=1` as a
      hard cost and abuse control.

      Set a budget scoped **to the OpenRefCheck project alone**, at a token amount
      (e.g. €0.01) with alerts at 50 / 90 / 100 % of spend. At that amount every
      threshold fires on the first cent, which is the intent: this deployment is
      meant to sit inside the free tier, so *any* spend is the signal, and a
      tripwire is more useful than a budget.

      The pitfall worth recording, because it is easy to miss and silently wrong:
      a budget created from the Cloud console's default flow has **no project
      filter at all**. It covers the whole billing account, so if that account
      also bills other projects, their spend and OpenRefCheck's are pooled under one
      alert and neither figure means anything. Check the `projects` filter on any
      pre-existing budget before relying on it, and give each project its own.

      **A budget alerts; it does not cap.** The controls that actually bound the
      cost are `max-instances=1` and scale-to-zero. Confirm both services report
      `maxScale: 1`, and keep passing `--max-instances=1` on deploy so a later
      revision cannot quietly raise it (`scripts/deploy-web.ps1` does). Note also
      that unless a budget carries a `notificationsRule`, its alerts go only to
      the billing account's default admins; wiring one to Pub/Sub (and, if ever
      wanted, to a billing-disable function) is a separate decision with its own
      failure mode — it would take the demo offline mid-presentation.
- [ ] set `OPENALEX_API_KEY` on the `refcheck-web` service. That service runs an
      image built from the legacy repository and carries only `GROBID_URL` and the
      old `REFCHECK_DEPLOYMENT_MODE`, so every
      OpenAlex lookup runs on the anonymous daily budget (~$0.10/day, about 1,000
      requests) rather than the free keyed one (~$1/day). `verification.
      openalex_crossref` already reads the variable and only sets
      `pyalex.config.api_key` when it is present, so this is deployment
      configuration, not code. Crossref needs no key, but it and OpenAlex share
      the other half of this: `OPENREFCHECK_CONTACT_EMAIL` supplies the `mailto` that
      puts both in the polite pool, and is unset by default because a compiled-in
      address would make every deployment announce whoever built it (see
      `openrefcheck/contact.py`). Set it, to an address whoever runs the service
      owns, alongside `OPENALEX_API_KEY`.

NiceGUI uses Socket.IO. Cloud Run supports WebSockets, but each connection
remains subject to the configured request timeout, currently up to 60 minutes.
The client must therefore reconnect after a long session. Keeping the NiceGUI
service at one instance avoids distributing its in-memory UI state.

## Renaming the deployed services

Neither a Cloud Run service nor an Artifact Registry repository can be renamed in
place. Moving to `openrefcheck-web` / `openrefcheck-grobid` / `openrefcheck` means
creating new resources and deleting the old ones.

**This changes the public URL.** Cloud Run derives the hostname from the service name,
so `refcheck-web-*.a.run.app` stops existing and a new hostname appears. Anywhere the
old URL was published — a submission, a slide, a link someone saved — breaks. Decide
that before starting.

If a stable public URL matters, map a custom domain to the service instead and rename
underneath it. The domain then survives any future service rename, which is the actual
fix; the run.app hostname never was a stable address.

```bash
PROJECT=your-gcp-project
REGION=europe-west3

# 1. New Artifact Registry repository, then push the image to it.
gcloud artifacts repositories create openrefcheck \
  --repository-format=docker --location=$REGION --project=$PROJECT

# 2. New GROBID service (same public image, private).
gcloud run deploy openrefcheck-grobid \
  --image=grobid/grobid:0.8.1 --region=$REGION --project=$PROJECT \
  --memory=4Gi --port=8070 --max-instances=1 --no-allow-unauthenticated

# 3. New web service, pointed at the new GROBID and using the new variable names.
TAG=$(git rev-parse --short HEAD)
docker build -f docker/nicegui/Dockerfile \
  -t $REGION-docker.pkg.dev/$PROJECT/openrefcheck/nicegui:$TAG .
docker push $REGION-docker.pkg.dev/$PROJECT/openrefcheck/nicegui:$TAG

gcloud run deploy openrefcheck-web \
  --image=$REGION-docker.pkg.dev/$PROJECT/openrefcheck/nicegui:$TAG \
  --region=$REGION --project=$PROJECT --max-instances=1 \
  --set-env-vars OPENREFCHECK_DEPLOYMENT_MODE=demo,GROBID_URL=https://<new-grobid-url>

# 4. Re-grant the invoker binding — IAM does not follow a new service.
gcloud run services add-iam-policy-binding openrefcheck-grobid \
  --region=$REGION --project=$PROJECT \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/run.invoker"

# 5. Verify the new URL serves, and that the sidebar shows the DEMO disclaimer —
#    if it says the document stays on your device, the mode variable did not arrive.

# 6. Only then delete the old ones.
gcloud run services delete refcheck-web --region=$REGION --project=$PROJECT
gcloud run services delete refcheck-grobid --region=$REGION --project=$PROJECT
gcloud artifacts repositories delete refcheck --location=$REGION --project=$PROJECT
```

Step 5 is worth doing even though the web entry point defaults to `demo` when the
variable is missing: that default is a floor, not a substitute for setting the mode you
actually intend. A Phase B institutional deployment wants `prod`, and only an explicit
value gets it.

## Alternatives considered

### Render

Render is easy to use for the NiceGUI frontend, but its free web instance
currently provides only 512 MB RAM and 0.1 CPU. This is unsuitable for GROBID,
which recommends about 4 GB RAM for complete-document processing. Free services
also sleep after 15 minutes without inbound traffic. Splitting the deployment
between Render and Cloud Run would add operational complexity without a
meaningful advantage for this demo.

### Hugging Face Spaces

The free CPU Basic hardware would be technically attractive, with 2 vCPUs and
16 GB RAM. However, current Hugging Face policy requires a paid PRO, Team, or
Enterprise plan to create compute-backed Gradio or Docker Spaces. The hardware
may have a zero hourly rate, but this is no longer a fully free starting option.

### GitHub Codespaces

Codespaces can expose the NiceGUI and GROBID ports and includes limited free
monthly usage for personal accounts. It is suitable for a supervised,
short-lived presentation, but it is a temporary development environment rather
than a stable deployment. Public port visibility also resets when a codespace
or port is restarted.

### NiceGUI On Air

NiceGUI On Air is a free technology-preview tunnel and is convenient for a
one-hour presentation from a developer machine. It does not independently host
GROBID, so it does not meet the separate-backend objective. It remains a useful
fallback for a one-off live demo.

## Privacy and security conditions

Until authentication, deletion behavior, regional processing, provider terms,
and the project's data-protection requirements have been reviewed, the public
demo should accept only synthetic or already-public manuscripts.

The raw GROBID endpoint should not be made publicly invokable. An unauthenticated
compute-heavy endpoint creates both abuse and unexpected-cost risk. If public
GROBID access is temporarily unavoidable during initial setup, restrict it to
non-confidential test documents, retain the one-instance limit, and remove
public access immediately after testing.

## Open questions

- Is a Google Cloud billing account available for the demo project?
- Should access to the NiceGUI demo be public, Google-authenticated, or limited
  through a separate access layer?
- Is matching the existing full-image benchmark more important than reducing
  GROBID cold-start time with the CRF-only image?
- What cold-start delay is acceptable during a presentation?
- Which European region is acceptable under the project's eventual
  data-protection assessment?

## Sources

- [Cloud Run pricing](https://cloud.google.com/run/pricing)
- [Deploying container images to Cloud Run](https://docs.cloud.google.com/run/docs/deploying)
- [Cloud Run memory configuration](https://docs.cloud.google.com/run/docs/configuring/services/memory-limits)
- [Using WebSockets on Cloud Run](https://docs.cloud.google.com/run/docs/triggering/websockets)
- [GROBID Docker images and memory guidance](https://grobid.readthedocs.io/en/latest/Grobid-docker/)
- [Render free-tier limitations](https://render.com/docs/free)
- [Render instance specifications](https://render.com/docs/compute-plans)
- [Hugging Face Spaces overview](https://huggingface.co/docs/hub/spaces-overview)
- [GitHub Codespaces included usage](https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-included-usage)
- [NiceGUI configuration and deployment](https://nicegui.io/documentation/section_configuration_deployment)
