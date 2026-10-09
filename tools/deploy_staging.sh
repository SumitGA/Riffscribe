#!/bin/bash
# Deploy a commit to staging (ADR-0010): copy the stack files to the VM, pull that commit's
# images from GHCR, run migrations, then restart the services. Usage:
#
#   make deploy-staging STAGING_SSH=ubuntu@<VM IP> [TAG=<commit SHA>]
#
# TAG defaults to the latest commit on origin/main, whose images CI publishes once it's green.
# The VM must have /srv/riffscribe/stack/.env (from infra/staging/.env.example).
set -euo pipefail
: "${STAGING_SSH:?set STAGING_SSH=ubuntu@<VM IP>}"
TAG=${TAG:-$(git rev-parse origin/main)}
STACK=/srv/riffscribe/stack
here=$(cd "$(dirname "$0")/.." && pwd)

echo "deploying ${TAG} to ${STAGING_SSH}"
# shellcheck disable=SC2029  # STACK is ours and meant to expand here, before ssh
ssh "${STAGING_SSH}" "test -f ${STACK}/.env" \
  || { echo "no ${STACK}/.env on the VM: copy infra/staging/.env.example there and fill it in" >&2; exit 1; }
scp -q "${here}"/infra/staging/{compose.yml,Caddyfile,backup.sh,backup_to_r2.py} "${STAGING_SSH}:${STACK}/"
ssh "${STAGING_SSH}" bash -s -- "${TAG}" "${STACK}" <<'REMOTE'
set -euo pipefail
tag=$1 stack=$2
cd "${stack}"
echo "${tag}" > TAG
export TAG=${tag}
docker compose pull --quiet
docker compose run --rm migrate
docker compose up -d --remove-orphans --wait
echo "17 3 * * * ubuntu ${stack}/backup.sh >> ${stack}/backup.log 2>&1" \
  | sudo tee /etc/cron.d/riffscribe-backup >/dev/null
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
REMOTE
# shellcheck disable=SC2029
host=$(ssh "${STAGING_SSH}" "grep '^STAGING_HOST=' ${STACK}/.env | cut -d= -f2")
curl -fsS "https://${host}/readyz" >/dev/null && echo "https://${host} is up (${TAG})"
