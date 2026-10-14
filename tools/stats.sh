#!/bin/bash
# How many people signed up (Clerk) and use the app (database), for one environment:
#   make stats ENV=prod      (or ENV=staging)
# Counts and dates only: no names or emails are printed.
set -euo pipefail
ENV=${ENV:-prod}
here=$(cd "$(dirname "$0")/.." && pwd)
SSH=${SSH:-ubuntu@$(terraform -chdir="${here}/infra/terraform/${ENV}" output -raw lan_ip)}
STACK=/srv/riffscribe/stack
echo "== ${ENV}"
# shellcheck disable=SC2029
ssh "${SSH}" "cd ${STACK} && docker compose exec -T api python -" < "${here}/tools/stats_clerk.py"
# shellcheck disable=SC2016,SC2029  # STACK expands here; $POSTGRES_* inside the container
ssh "${SSH}" "cd ${STACK} && docker compose exec -T postgres sh -c 'psql -U \$POSTGRES_USER -d \$POSTGRES_DB -P pager=off -x'" < "${here}/tools/stats.sql"
