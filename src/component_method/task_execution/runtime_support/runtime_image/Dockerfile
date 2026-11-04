FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash git ripgrep coreutils findutils \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /bin/bash repoagent

WORKDIR /testbed
USER 10001:10001
