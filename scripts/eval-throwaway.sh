#!/bin/sh
# Measure a model against a throwaway openITCOCKPIT: bring one up, fill it,
# run the eval, remove it again. Nothing touches an installation you care about.
#
#   OITC_EVAL_BASE_URL=... OITC_EVAL_API_KEY=... \
#   ./scripts/eval-throwaway.sh --model <model> [--samples 3] [--write]
#
# Needs: docker with the compose plugin, a checkout of openITCOCKPIT-ce-docker
# (OITC_DOCKER_DIR, default ../openITCOCKPIT-ce-docker), and this package
# installed (pip install -e .).
#
# The instance is removed at the end, including its volumes, whether the eval
# passed or not. Set KEEP=1 to leave it running: the next run with KEEP=1 finds
# the test data still in place and starts asking within seconds.
set -eu

docker_dir="${OITC_DOCKER_DIR:-../openITCOCKPIT-ce-docker}"
keep="${KEEP:-0}"

if [ ! -f "$docker_dir/compose.yml" ] && [ ! -f "$docker_dir/docker-compose.yml" ]; then
    echo "No openITCOCKPIT compose file in $docker_dir - set OITC_DOCKER_DIR." >&2
    exit 2
fi

# The instance this script starts is the local compose stack, so a base URL
# pointing anywhere else means the environment still holds a real one - and the
# seed would write its 500 hosts into that.
case "${OITC_BASEURL:-}" in
    "" | http://127.0.0.1* | https://127.0.0.1* | http://localhost* | https://localhost*) ;;
    *)
        echo "OITC_BASEURL is $OITC_BASEURL, which is not the instance this script starts." >&2
        echo "Unset it, or set it to https://127.0.0.1. Otherwise the test data goes there." >&2
        exit 2
        ;;
esac

cleanup() {
    status=$?
    if [ "$keep" = "1" ]; then
        echo "KEEP=1: leaving the instance up at $OITC_BASEURL"
    else
        echo "--- removing the throwaway instance"
        (cd "$docker_dir" && docker compose down --volumes --remove-orphans >/dev/null 2>&1) || true
    fi
    exit $status
}
trap cleanup EXIT INT TERM

echo "--- starting openITCOCKPIT in $docker_dir"
(cd "$docker_dir" && docker compose up -d)

echo "--- waiting for it to answer"
: "${OITC_BASEURL:=https://127.0.0.1}"
export OITC_BASEURL OITC_VERIFY_TLS=false
until curl -sk --max-time 5 "$OITC_BASEURL/login" >/dev/null 2>&1; do sleep 5; done

if [ -z "${OITC_APIKEY:-}" ]; then
    echo "Set OITC_APIKEY to an API key of that instance (Profile -> API key)." >&2
    exit 2
fi

# Filling an empty instance takes minutes, so a kept one is reused as it is.
if curl -sk --max-time 20 -H "Authorization: X-OITC-API $OITC_APIKEY" \
        "$OITC_BASEURL/hosts/index.json?angular=true&filter%5BHosts.name%5D=scale-srv-001" 2>/dev/null \
        | grep -q 'scale-srv-001'; then
    echo "--- the test data is already there, keeping it"
else
    echo "--- filling it with the test data"
    python scripts/seed_scale_dataset.py
fi

echo "--- running the eval"
# This instance exists to be thrown away, so the tools that cannot be undone are
# allowed here - the plain command refuses them.
oitc-mcp-eval --yes --allow-deletes "$@"
