# Project: Audio → Tabs & Sheet Music (working name: "TabScribe")

## Product
Mobile app. A user uploads or records audio and gets back editable sheet music and guitar tab, exportable as PDF, MusicXML, MIDI and Guitar Pro.
- v1 scope: **solo guitar or solo piano** recordings, max 5 min (free tier).
- Monetisation later: free tier with monthly quota; paid tier with longer clips, more jobs, priority queue.

## Tech stack (defaults — ask before changing)
- **Mobile:** Expo (React Native, TypeScript strict), expo-router, TanStack Query, alphaTab rendered in a WebView (renders both standard notation and tab).
- **API:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL 16.
- **Queue:** `JobQueue` interface. Redis Streams implementation for local dev, SQS for prod.
- **Object storage:** S3 (MinIO locally). Clients use presigned URLs only.
- **Auth:** managed provider issuing JWTs (default: AWS Cognito). The API only validates JWTs and never stores passwords.
- **ML pipeline:** Demucs (htdemucs) for source separation, Basic Pitch for audio→MIDI, librosa for beat and tempo, music21 for MusicXML, and a custom tab-fingering module (Viterbi over playable positions).
- **Infra:** Docker plus docker-compose locally; Terraform for AWS. API on ECS Fargate; GPU workers on an EC2 GPU autoscaling group or EKS + KEDA, scaled on queue depth.
- **Licences:** check every model and library licence before adding it. The app is commercial, so no non-commercial weights (for example, madmom's pretrained models are non-commercial).

## Architecture

```
Mobile ──► API (stateless) ──► Postgres (jobs, users, scores)
  │            │
  │            └──► Queue ──► cpu-worker (normalize, quantize, notation, tab)
  │                      └──► gpu-worker (separation, transcription)
  └──presigned PUT/GET──► S3 (audio + artifacts)
```

### Job flow
1. `POST /jobs` creates a job (`pending_upload`) and returns a presigned PUT URL.
2. The client uploads audio directly to S3. Audio never passes through the API.
3. `POST /jobs/{id}/submit` validates the upload (size, duration, format, quota) and enqueues the job.
4. Workers run the stages in order: `normalize → separate → transcribe → quantize → notation → tab`. Each stage reads and writes artifacts under `s3://…/users/{user_id}/jobs/{job_id}/{stage}/`.
5. Workers record job and stage status in Postgres. The client polls `GET /jobs/{id}` and also receives an Expo push notification on completion.
6. Outputs: MusicXML, MIDI and alphaTex. User edits are saved as new `score_versions`; originals are never overwritten.

## Scalability rules (non-negotiable)
- **Stateless API.** No local disk state and no in-memory sessions. Any instance can serve any request. API p95 latency target is under 200 ms.
- **All heavy work is async.** The API must never run ML inline.
- **Separate CPU and GPU queues and workers.** They autoscale independently on queue depth. GPU workers scale to zero when idle.
- **Idempotent stages.** Every stage can be re-run safely. Use retries with exponential backoff and a dead-letter queue. Set a max of 3 attempts per stage.
- **Deduplication cache.** Key results on `sha256(normalized_audio) + pipeline_version` and reuse them instead of recomputing.
- **Versioned pipeline.** Every result stores the `pipeline_version` that produced it, so model upgrades never silently change old results.
- **Quotas and rate limits.** Enforce per-user limits in Redis. Priority queue for the paid tier.
- **Tenant isolation.** Scope every DB query by `user_id`. Prefix every S3 key with the user ID. Presigned URLs expire in 15 minutes or less.
- **Lean database.** Postgres holds metadata only; blobs go to S3. Index `jobs(user_id, created_at)` and `jobs(status)`.
- **Observability.** Use structured JSON logs and OpenTelemetry traces, both carrying `job_id`. Track these metrics: queue depth, per-stage duration, failure rate and GPU utilisation.
- **12-factor config.** All configuration comes from environment variables. No secrets in the repo.

## Repo layout (monorepo)
```
apps/mobile/            Expo app
services/api/           FastAPI app
services/worker/        Queue consumer; thin wrapper around packages/pipeline
packages/pipeline/      Pure Python transcription library — NO infra dependencies
infra/terraform/
docs/adr/               Architecture decision records
docker-compose.yml
```
- `packages/pipeline` must run standalone, for example `python -m pipeline transcribe in.wav --out out/`, so model work can be iterated without the app or infra.

## Conventions
- Python: ruff, mypy --strict, pytest. TypeScript: strict mode, eslint.
- Pipeline tests are golden-file tests on short fixture clips. Track note-level F1 with `mir_eval` and fail CI on regressions.
- No new dependency without a one-line justification in the PR or commit.
- Make small, focused commits. Record architecture changes as an ADR in `docs/adr/` and update this file.
- Before writing code for a new phase, propose a plan and wait for approval.

## Build phases
1. **Pipeline CLI**: audio → MIDI → MusicXML → tab, plus fixtures and accuracy tests. No app, no infra.
2. **Backend**: API, workers, queue and local docker-compose, tested end to end via curl.
3. **Mobile app**: auth, record/upload, job status, alphaTab rendering, export.
4. **Editor**: note and fret corrections, with score versions.
5. **Production**: Terraform, autoscaling, monitoring, billing (RevenueCat for in-app subscriptions).

## Out of scope for v1
Full-band mixes, vocals and drums, advanced guitar techniques (bends, slides, hammer-ons), real-time transcription.
