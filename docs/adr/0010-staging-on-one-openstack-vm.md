# ADR-0010: Staging on one OpenStack VM

- Status: accepted
- Date: 2026-10-09
- Builds on: ADR-0002 (R2), ADR-0004 (OpenStack, CPU-only), ADR-0008 (Clerk), ADR-0009

## Context

Until now the backend ran only on the owner's laptop (`make stack`), and the phone reached it
over USB or the LAN. Testing the app needs a backend that is always up and reachable over
HTTPS from anywhere, and an app build that can be installed without a cable. Phase 5
(production: autoscaling, monitoring, billing) is further away; this is the smallest step
toward it that uses the same pieces.

## Decision

- **One VM** (4 vCPU / 8 GB, Ubuntu 24.04) on the owner's OpenStack cloud, created with
  Terraform (`infra/terraform/staging`): a firewall group allowing SSH from the owner's IP only
  plus 80/443 from anywhere, a floating IP, and a separate volume for Postgres data so the VM
  can be replaced without losing it. cloud-init installs Docker and unattended upgrades.
- **docker compose on the VM** (`infra/staging/compose.yml`): Caddy (reverse proxy, automatic
  HTTPS from Let's Encrypt), the API, one worker, Postgres 16 and Valkey. Only Caddy publishes
  ports; Postgres, Valkey and the metrics endpoints stay on the VM's internal network.
- **Hostname:** `api-staging.<owner's domain>`, one DNS A record to the floating IP.
- **Object storage:** a Cloudflare R2 bucket (S3 API, ADR-0002). Clients get presigned URLs
  straight to R2; audio never passes through the VM's API.
- **Auth:** the existing Clerk dev instance; the API validates its JWTs against the JWKS
  (`JWT_JWKS_URL`). Dev tokens (`JWT_DEV_SECRET`, TD-17) are never set on staging.
- **Images:** GitHub Actions builds the `api` and `worker` images on every push to `main` and
  pushes them to GHCR tagged with the commit SHA. The VM pulls a given tag; it never builds.
- **Deploys:** `make deploy-staging TAG=<sha>` copies the compose files over SSH, pulls the
  images, runs migrations, then restarts the services. Secrets live only in `.env` on the VM
  (`infra/staging/.env.example` lists them).
- **Backups:** nightly `pg_dump` to R2 (`backups/` prefix, kept 14 days); the restore is
  documented in `docs/staging.md` and tested once.
- **App:** an EAS `staging` build profile bakes in the staging API URL and builds an APK for
  internal distribution (install from a link). EAS Update's `staging` channel ships JS-only
  changes without a rebuild. Push notifications go through Expo (`WORKER_NOTIFIER=expo`).

## Consequences

- An always-on backend for testing on real phones, with no cables, LAN IPs or laptop.
- The production path keeps the same images, settings and storage; Phase 5 adds more VMs or AWS
  around them rather than rewriting them.
- One VM is a single point of failure, and staging has no monitoring beyond logs (TD-29).
- Terraform state is a local, git-ignored file for now (TD-30).
- Costs: the VM (owner's cloud), R2 storage (free tier at this size), a domain.
