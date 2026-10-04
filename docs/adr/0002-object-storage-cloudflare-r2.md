# ADR-0002: Cloudflare R2 instead of AWS S3 for object storage

- Status: accepted
- Date: 2026-10-04
- Supersedes: "Object storage: S3" in CLAUDE.md

## Context

Audio and artifacts must live in object storage reached through presigned URLs. Cost matters at
MVP stage. For this app the main S3 cost is egress (users downloading audio, PDFs, MusicXML),
not storage. The backend runs on self-hosted OpenStack VMs (ADR-0004), not AWS.

## Decision

Use **Cloudflare R2** in production, through the **S3 API** (boto3 with `S3_ENDPOINT_URL`).
Code stays provider-neutral: no Cloudflare-specific SDK calls.

- Free tier at time of writing: 10 GB-month storage, ~1M write and ~10M read operations/month,
  zero egress fees. Re-check pricing before launch.
- Lifecycle rule: delete intermediate artifacts (normalized audio, stems) after ~7 days; keep the
  original upload and final outputs.
- Store audio compressed (FLAC for normalized audio) rather than float WAV.
- Local dev: an S3-compatible server in docker-compose (MinIO, or SeaweedFS if MinIO's community
  edition is unsuitable; to be decided in Phase 2).

## Consequences

- Moving to S3, Backblaze B2 or another S3-compatible store later is a config change.
- R2 lacks some S3 features (e.g. some event notification types); the design must not depend on
  S3 event triggers. The API enqueues jobs explicitly on `POST /jobs/{id}/submit`, so this holds.
