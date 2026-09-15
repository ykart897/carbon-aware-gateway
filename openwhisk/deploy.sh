#!/usr/bin/env bash
# Optional single-host demo: four actions represent four regions.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
: "${OPENWHISK_AUTH:?Set OPENWHISK_AUTH to your own namespace credentials}"
OPENWHISK_HOST="${OPENWHISK_HOST:-http://127.0.0.1:3233}"
OW_IMAGE="${OW_IMAGE:-openwhisk/standalone:nightly}"
OW_CONTAINER="${OW_CONTAINER:-openwhisk-standalone}"
OW_PORT="${OW_PORT:-3233}"
for tool in docker curl wsk; do
  command -v "$tool" >/dev/null || { echo "Missing required command: $tool" >&2; exit 1; }
done
if docker container inspect "$OW_CONTAINER" >/dev/null 2>&1; then
  if [[ "$(docker inspect --format '{{.State.Running}}' "$OW_CONTAINER")" != true ]]; then
    echo "Existing container is stopped. Start it explicitly before deployment." >&2
    exit 1
  fi
  echo "Using existing container: $OW_CONTAINER"
else
  docker run -d --name "$OW_CONTAINER" -p "127.0.0.1:${OW_PORT}:3233" "$OW_IMAGE"
fi
ready=false
for ((attempt=0; attempt<30; attempt++)); do
  if curl --fail --silent --max-time 3 "$OPENWHISK_HOST/api/v1" | grep -q 'version'; then
    ready=true
    break
  fi
  sleep 2
done
if [[ "$ready" != true ]]; then
  echo "OpenWhisk did not become ready; no actions were deployed." >&2
  exit 1
fi
# Host and credentials are per-command; global CLI properties are never changed.
wsk_local() { wsk --apihost "$OPENWHISK_HOST" --auth "$OPENWHISK_AUTH" "$@"; }
deploy_action() {
  local region="$1" carbon="$2" latency="$3" energy="$4"
  wsk_local action update "carbon-worker-$region" "$SCRIPT_DIR/carbon_worker.py" \
    --kind python:3 --timeout 10000 \
    --param region "$region" --param base_carbon "$carbon" \
    --param base_latency "$latency" --param energy_source "$energy"
}
deploy_action DE 380 18 Mixed
deploy_action IE 115 48 'Wind dominant'
deploy_action FR 65 22 'Nuclear and wind'
deploy_action PL 655 32 'Coal dominant'
for region in DE IE FR PL; do
  wsk_local action invoke "carbon-worker-$region" --param action deployment_check --blocking --result
done
echo 'Four actions on one local OpenWhisk instance; not a multi-region deployment.'
