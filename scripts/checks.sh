#!/bin/sh
# Lint, type check and tests. Expects to run inside the image the Dockerfile is
# based on. Use scripts/checks-docker.sh to get that container for free.
set -eu

# Editable installs write egg-info into the source tree. On a reused CI
# workspace a leftover directory from an earlier run makes setuptools fail
# when it cannot update the timestamp, so start clean.
rm -rf src/*.egg-info

# The image ships no venv and we run as an unprivileged user, so build one in
# /tmp rather than writing into the image's site-packages.
python -m venv /tmp/venv
. /tmp/venv/bin/activate
pip install --quiet -e ".[dev]"

echo '--- ruff'
ruff check src tests

echo '--- mypy'
mypy

echo '--- pytest'
pytest -q --cov=openitcockpit_mcp
