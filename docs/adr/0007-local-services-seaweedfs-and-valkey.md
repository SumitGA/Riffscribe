# ADR-0007: Local services: SeaweedFS for S3, Valkey for Redis

- Status: accepted
- Date: 2026-10-05
- Completes: the "MinIO or SeaweedFS, to be decided in Phase 2" note in ADR-0002

## Context

Phase 2 runs the backend locally with docker-compose: Postgres, a Redis-compatible server
(queue, quotas, rate limits) and an S3-compatible server standing in for Cloudflare R2. Every
component must have a licence we can use commercially, and must keep working in a few years.

- **MinIO**, the usual choice, moved its community edition to source-only in late 2025: no more
  published binaries or Docker images, and the admin console was removed earlier. It is AGPL-3.0.
- **Redis** changed licence from BSD to RSALv2/SSPL in 7.4, then added AGPL-3.0 in 8.0. Using it
  unmodified as an internal component is allowed, but each change needs re-checking.

## Decision

- **S3 locally: SeaweedFS** (`chrislusf/seaweedfs`, Apache-2.0), single container
  (`weed server -s3`), image tag pinned. A one-shot `seaweedfs-init` service creates the bucket.
  Dev credentials live in `infra/local/seaweedfs-s3.json`; they are throwaway, not secrets.
- **Redis locally: Valkey** (`valkey/valkey`, BSD-3), the Linux Foundation fork of Redis 7.2.
  Same wire protocol and Streams commands, so the code uses the plain `redis` Python client and
  `REDIS_URL`; nothing in the code names Valkey. Production may run either.
- Production object storage stays Cloudflare R2 (ADR-0002). Code talks to both through the S3
  API only; services and clients may use different S3 hostnames (`S3_ENDPOINT_URL` vs
  `S3_PUBLIC_ENDPOINT_URL`) because presigned URLs embed the host they were signed for.

## Consequences

- Fully permissive local stack; no image that may disappear.
- SeaweedFS is not R2: S3 edge cases (presigned-URL headers, multipart limits, error codes) can
  differ. The end-to-end test runs against SeaweedFS; a smoke test against a real R2 bucket is
  needed before launch.
- If we ever need a Redis 8-only feature, switching the image is a one-line change.
