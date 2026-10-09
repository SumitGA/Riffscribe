#!/bin/bash
# Deploy a commit to staging (ADR-0010): copy the stack files to the VM, pull that commit's
# images from GHCR, run migrations, then restart the services. Usage:
#
#   make deploy-staging STAGING_SSH=ubuntu@<VM IP> [TAG=<commit SHA>]
#
# TAG defaults to the latest commit on GitHub's main, whose images CI publishes once it's green.
# The VM must have /srv/riffscribe/stack/.env (from infra/staging/.env.example).
set -euo pipefail
: "${STAGING_SSH:?set STAGING_SSH=ubuntu@<VM IP>}"
TAG=${TAG:-$(git ls-remote https://github.com/SumitGA/Riffscribe.git refs/heads/main | cut -f1)}
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
# This script arrives on stdin, so every docker command reads /dev/null instead: `compose run`
# would otherwise swallow the rest of it.
# The commit goes into .env (TAG=), so plain `docker compose ...` on the VM uses it too.
if grep -q '^TAG=' .env; then sed -i "s/^TAG=.*/TAG=${tag}/" .env; else echo "TAG=${tag}" >> .env; fi
docker compose pull --quiet < /dev/null
docker compose run --rm -T migrate < /dev/null
docker compose up -d --remove-orphans --wait < /dev/null
echo "17 3 * * * ubuntu ${stack}/backup.sh >> ${stack}/backup.log 2>&1" \
  | sudo tee /etc/cron.d/riffscribe-backup >/dev/null
docker compose ps --format 'table {{.Service}}\t{{.Status}}' < /dev/null
REMOTE
# shellcheck disable=SC2029
host=$(ssh "${STAGING_SSH}" "grep '^STAGING_HOST=' ${STACK}/.env | cut -d= -f2")
curl -fsS "https://${host}/readyz" >/dev/null && echo "https://${host} is up (${TAG})"
