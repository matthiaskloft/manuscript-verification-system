# Web-only image for the hosted demo (see docs/demo-deployment-decision.md).
# Deliberately does NOT install the "native" extra (pywebview) — the desktop
# entry point (openrefcheck.app:main) never runs in this container, only the web
# one (openrefcheck.app_web:main, registered as the "openrefcheck-web" console script).
FROM python:3.11-slim

WORKDIR /app

# Copied separately from src/ so `pip install .` is cached across source-only
# changes (pyproject.toml rarely changes between builds).
COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

# Cloud Run overrides PORT at runtime; 8080 is just the local-docker-run default.
ENV PORT=8080
EXPOSE 8080

# Cloud Run traffic never reaches GROBID directly (see demo-deployment-decision.md);
# set GROBID_URL to the private Cloud Run service URL at deploy time, e.g.:
#   --set-env-vars GROBID_URL=https://<your-grobid-service>-xxxxx.a.run.app
ENV OPENREFCHECK_DEPLOYMENT_MODE=demo

CMD ["openrefcheck-web"]
