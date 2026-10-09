#!/bin/bash
# Nightly Postgres backup to R2 (ADR-0010), run by cron on the VM (/etc/cron.d/riffscribe-backup,
# installed by `make deploy-staging`). The dump is written to the VM's disk first and only
# uploaded if pg_dump succeeded, so a failed dump never replaces a good one in R2.
set -euo pipefail
cd "$(dirname "$0")"
dump="$PWD/backup.dump"  # in the stack folder, which the ubuntu user owns
trap 'rm -f "$dump"' EXIT
r2() { docker compose run --rm -T --no-deps -v "$PWD/backup_to_r2.py:/backup_to_r2.py:ro" api python /backup_to_r2.py "$@"; }

docker compose exec -T postgres pg_dump -U riffscribe -d riffscribe --format=custom > "$dump"
r2 upload < "$dump"
r2 prune
