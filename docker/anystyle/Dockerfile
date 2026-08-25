# No official AnyStyle image exists (distributed as a Ruby gem, not a container) —
# see docs/project-plan.md, Tier 2. This wraps anystyle-cli + its pdftotext dependency
# so it's runnable the same way as the other tiers (docker run ... against a PDF).
FROM ruby:3.3-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN gem install anystyle-cli --no-document

WORKDIR /data
ENTRYPOINT ["anystyle"]
