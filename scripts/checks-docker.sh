#!/bin/sh
# Runs scripts/checks.sh inside the same image the Dockerfile is based on, so
# CI and local runs use identical Python and system libraries.
#
#   ./scripts/checks-docker.sh
#
set -eu

# The Dockerfile's first FROM line is the single source of truth for the Python
# version - do not duplicate it here.
base_image=$(awk '/^FROM /{print $2; exit}' Dockerfile)

if [ -z "$base_image" ]; then
    echo 'No FROM line found in Dockerfile' >&2
    exit 1
fi

echo "Using base image: $base_image"

# -u keeps caches and *.egg-info from being written into the workspace as root.
# HOME=/tmp gives pip a writable cache directory for that unprivileged user.
docker run --rm \
    -u "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "$PWD":/src -w /src \
    "$base_image" ./scripts/checks.sh