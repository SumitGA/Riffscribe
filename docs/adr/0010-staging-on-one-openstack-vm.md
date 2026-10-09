# ADR-0010: Staging on one OpenStack VM

- Status: accepted
- Date: 2026-10-09 (amended the same day for the home lab: Cloudflare Tunnel, no block storage)
- Builds on: ADR-0002 (R2), ADR-0004 (OpenStack, CPU-only), ADR-0008 (Clerk), ADR-0009

## Context

Until now the backend ran only on the owner's laptop (`make stack`), and the phone reached it
over USB or the LAN. Testing the app needs a backend that is always up and reachable over
HTTPS from anywhere, and an app build that can be installed without a cable. Phase 5
(production: autoscaling, monitoring, billing) is further away; this is the smallest step
toward it that uses the same pieces.

The OpenStack cloud is the owner's home lab (Kolla), behind the home router:
- its public API endpoints sit behind Cloudflare's proxy, which doesn't forward OpenStack's
  ports, so tools reach the internal endpoints over the LAN instead;
- its floating IPs are LAN addresses, so the internet can't connect to a VM directly;
- it has no block storage service and no flavor of the size we want.

## Decision

- **One VM** (4 vCPU / 6 GB / 40 GB, Ubuntu 24.04), created with Terraform
  (`infra/terraform/staging`) through the `homelab-lan` clouds.yaml entry and the internal
  endpoints. Terraform also creates the VM's flavor, its own network and router (SNAT to the
  LAN), a LAN floating IP for SSH and deploys, and a security group that allows SSH from the LAN
  only. cloud-init installs Docker and unattended upgrades.
- **docker compose on the VM** (`infra/staging/compose.yml`): `cloudflared`, Caddy, the API, one
  worker, Postgres 16 and Valkey. Nothing publishes a port.
- **Public access through a Cloudflare Tunnel:** `cloudflared` connects out to Cloudflare, which
  serves `riffscribe-staging.sumitgautam.tech` with HTTPS and forwards requests down the
  tunnel to Caddy (plain HTTP, internal), which hides `/metrics` and proxies to the API. No
  router changes, works behind CGNAT, and the home IP stays private.
- **Postgres on the VM's root disk** (the lab has no block storage); the nightly backup to R2 is
  the safety net.
- **Object storage:** a Cloudflare R2 bucket (S3 API, ADR-0002). Clients get presigned URLs
  straight to R2; audio never passes through the tunnel or the API.
- **Auth:** the existing Clerk dev instance; the API validates its JWTs against the JWKS
  (`JWT_JWKS_URL`). Dev tokens (`JWT_DEV_SECRET`, TD-17) are never set on staging.
- **Images:** GitHub Actions builds the `api` and `worker` images on every green push to `main`
  and pushes them to GHCR tagged with the commit SHA. The VM pulls a given tag; it never builds.
- **Deploys:** from the LAN, `make deploy-staging STAGING_SSH=ubuntu@<LAN IP> TAG=<sha>` copies
  the compose files over SSH, pulls the images, runs migrations, then restarts the services.
  Secrets live only in `.env` on the VM (`infra/staging/.env.example` lists them).
- **Backups:** nightly `pg_dump` to R2 (`backups/` prefix, kept 14 days); the restore is
  documented in `docs/staging.md`.
- **App:** an EAS `staging` build profile bakes in the staging API URL and builds an APK for
  internal distribution (install from a link). EAS Update's `staging` channel ships JS-only
  changes without a rebuild. Push notifications go through Expo (`WORKER_NOTIFIER=expo`).

## Consequences

- An always-on backend for testing on real phones, with no cables, LAN IPs or laptop.
- The production path keeps the same images, settings and storage; Phase 5 adds more VMs or AWS
  around them rather than rewriting them.
- Staging depends on the home lab's power and internet, and on Cloudflare's tunnel. One VM is a
  single point of failure, losing it loses up to a day of database changes, and there is no
  monitoring beyond logs (TD-29).
- Terraform and deploys only work from the LAN (or a VPN into it).
- Terraform state is a local, git-ignored file for now (TD-30).
- Costs: R2 storage (free tier at this size) and electricity; the domain and tunnel are free.
