# CPU sandbox for the ipp_to_vsipl scenario.
#
# The agent gets this image with the task workspace at /workspace and jvsip
# mounted read-only at /opt/vsipl (VSIPL_ROOT=/opt/vsipl).  Network is off at
# run time; everything needed is installed here or already in the workspace.
#
#   docker build -f env/Dockerfile.ipp -t migration/ipp:cpu .
#
# The agent runs as uid 10001 with no passwd entry, so the image deliberately
# does not depend on a named user.  python3 is for the shared judge harness
# (also run in this image, as uid 10001).
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        binutils \
        cmake \
        ninja-build \
        pkg-config \
        python3 \
        python3-yaml \
        file \
    && rm -rf /var/lib/apt/lists/*

# Sanity: gcc 13 and cmake are the versions the task expects.
RUN gcc --version | head -1 && cmake --version | head -1 && python3 --version

WORKDIR /workspace