# ADR-0004: CPU-only MVP on self-hosted OpenStack VMs

- Status: accepted
- Date: 2026-10-04
- Amends: the AWS / GPU infra defaults in CLAUDE.md, which become the scale-up path

## Context

There is no GPU available, and the MVP backend will run on the owner's OpenStack VMs.
v1 inputs are solo guitar or solo piano, so source separation adds little.

## Decision

- **Pipeline is CPU-only by default.** `separate` is a passthrough; Demucs is an optional install
  extra (`pipeline[separation]`) and config flag. Basic Pitch runs on ONNX Runtime's CPU backend.
- A `python -m pipeline bench` command reports per-stage time and peak memory; CI fails on large
  regressions (about 20%).
- **Hosting (Phase 2):** docker-compose (or k3s for several nodes) on OpenStack VMs.
  - Queue: Redis Streams behind `JobQueue` (also the local implementation).
  - Separate logical queues for CPU stages and ML stages, served by one worker pool for now,
    so GPU workers can be added later by config.
  - Postgres on a VM with automated nightly `pg_dump` to R2 (ADR-0002) and a tested restore.
  - Terraform via the OpenStack provider.
  - Auth stays a managed JWT provider (Cognito by default), which works from any host.
- **Scale-up path:** AWS (ECS Fargate, SQS, GPU autoscaling) when load or paid features need it.

## Consequences

- Near-zero infra cost; no GPU spend.
- We operate the database, queue and backups ourselves (no managed failover).
- Transcription quality is capped at what runs well on CPU; Demucs stays available for testing.
- See `docs/tech-debt/README.md` (TD-1 to TD-4).
