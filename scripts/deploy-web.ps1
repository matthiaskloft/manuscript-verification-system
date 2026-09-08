# Build, tag, push, and redeploy the NiceGUI web image to Cloud Run in one step.
# See docs/demo-deployment-decision.md's "Image tagging" section for why SHA
# tags exist: a mutable :latest gives no way to tell what code a running
# revision actually has.
#
# Nothing here is specific to one Google Cloud project. Point it at your own by
# passing parameters or by exporting the matching environment variables — a fork
# deploying its own demo should not have to edit this file.
#
# Usage (from the repo root):
#   .\scripts\deploy-web.ps1 -Project my-project -Region europe-west3
#
# or:
#   $env:OPENREFCHECK_GCP_PROJECT = "my-project"
#   .\scripts\deploy-web.ps1
#
# Assumes `docker` and `gcloud` are already on PATH and authenticated
# (`gcloud auth login`, `gcloud auth configure-docker <region>-docker.pkg.dev`),
# and that the Artifact Registry repository named by -Repository exists in the
# project (`gcloud artifacts repositories create openrefcheck --repository-format=docker`).

[CmdletBinding()]
param(
    # The Google Cloud project to deploy into. Required — there is no default,
    # because a default would be somebody else's project.
    [string]$Project = $env:OPENREFCHECK_GCP_PROJECT,

    [string]$Region = $(if ($env:OPENREFCHECK_GCP_REGION) { $env:OPENREFCHECK_GCP_REGION } else { "europe-west3" }),

    # Artifact Registry repository name (not the full path — that is assembled below).
    [string]$Repository = $(if ($env:OPENREFCHECK_AR_REPOSITORY) { $env:OPENREFCHECK_AR_REPOSITORY } else { "openrefcheck" }),

    # The Cloud Run service receiving the new revision. Named for the system
    # rather than for this module: the service runs whatever the repository
    # builds, and reference checking is the first module of several. A service
    # name is also permanent — Cloud Run derives the hostname from it and cannot
    # rename in place — so it should not encode a part that is expected to move.
    [string]$Service = $(if ($env:OPENREFCHECK_RUN_SERVICE) { $env:OPENREFCHECK_RUN_SERVICE } else { "mvs-app" })
)

$ErrorActionPreference = "Stop"

if (-not $Project) {
    throw "No Google Cloud project. Pass -Project <id> or set OPENREFCHECK_GCP_PROJECT."
}

$Image = "$Region-docker.pkg.dev/$Project/$Repository/nicegui"
$Tag = (git rev-parse --short HEAD).Trim()

if (-not (git status --porcelain)) {
    Write-Host "Working tree clean, building $Tag" -ForegroundColor Cyan
} else {
    Write-Warning "Uncommitted changes present — the deployed image won't exactly match any commit. Continuing anyway."
}

docker build -f docker/nicegui/Dockerfile -t "${Image}:$Tag" -t "${Image}:latest" .
docker push "${Image}:$Tag"
docker push "${Image}:latest"

# --max-instances=1 is a cost and abuse control, not a performance setting: the demo
# upload endpoint is public, and one instance is the ceiling on what an abusive caller
# can spend. Passed on every deploy so a later revision cannot quietly raise it.
gcloud run deploy $Service `
    --image="${Image}:$Tag" `
    --region=$Region `
    --project=$Project `
    --max-instances=1

Write-Host "Deployed $Tag to $Service in $Project/$Region." -ForegroundColor Green
