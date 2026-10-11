#!/bin/bash
# Deploy a commit to one environment (staging ADR-0010, production ADR-0012): copy the stack
# files to its VM, pull that commit's images from GHCR, run migrations, then restart the
# services. Usage:
#
#   make deploy ENV=staging [TAG=<commit SHA>] [SSH=ubuntu@<VM IP>]
#   make deploy ENV=prod    [TAG=<commit SHA>] [SSH=ubuntu@<VM IP>]
#
# SSH defaults to the VM Terraform created (infra/terraform/<env>, `terraform output lan_ip`).
# Staging's TAG defaults to the latest commit on GitHub's main, whose images CI publishes once
# it's green. Production's defaults to the commit running on staging: only what was tried
# there reaches users. The VM must have /srv/riffscribe/stack/.env (infra/stack/.env.example).
set -euo pipefail
ENV=${ENV:-staging}
case "${ENV}" in staging | prod) ;; *) echo "ENV must be staging or prod" >&2; exit 1 ;; esac
here=$(cd "$(dirname "$0")/.." && pwd)
STACK=/srv/riffscribe/stack
lan_ip() { echo "ubuntu@$(terraform -chdir="${here}/infra/terraform/$1" output -raw lan_ip)"; }
SSH=${SSH:-$(lan_ip "${ENV}")}
if [ -z "${TAG:-}" ]; then
  if [ "${ENV}" = prod ]; then
    # shellcheck disable=SC2029
    TAG=$(ssh "$(lan_ip staging)" "grep '^TAG=' ${STACK}/.env | cut -d= -f2")
  else
    TAG=$(git ls-remote https://github.com/SumitGA/Riffscribe.git refs/heads/main | cut -f1)
  fi
fi
echo "deploying ${TAG} to ${ENV} (${SSH})"
# shellcheck disable=SC2029  # STACK is ours and meant to expand here, before ssh
ssh "${SSH}" "test -f ${STACK}/.env" \
  || { echo "no ${STACK}/.env on the VM: copy infra/stack/.env.example there and fill it in" >&2; exit 1; }
scp -q "${here}"/infra/stack/{compose.yml,Caddyfile,backup.sh,backup_to_r2.py} "${SSH}:${STACK}/"
scp -q -r "${here}"/infra/site "${SSH}:${STACK}/"  # terms, privacy, delete-account pages
ssh "${SSH}" bash -s -- "${TAG}" "${STACK}" <<'REMOTE'
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
host=$(ssh "${SSH}" "grep -E '^(PUBLIC|STAGING)_HOST=' ${STACK}/.env | head -1 | cut -d= -f2")
curl -fsS "https://${host}/readyz" >/dev/null && echo "https://${host} is up (${TAG})"
