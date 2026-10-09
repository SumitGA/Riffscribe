# Project: Audio → Tabs & Sheet Music ("Riffscribe"; code and infra names still say tabscribe)

## Product
Mobile app. A user uploads or records audio and gets back editable sheet music and guitar tab, exportable as PDF, MusicXML, MIDI and Guitar Pro.
- **Goal: upload a song and get tabs for the guitar parts in it** (strummed chords, lead and riffs, fingerpicking) (ADR-0009). Built in steps: **A** make solo guitar transcription good (chords, fingering, sound; current); **B** song mode (separate the guitar from a full mix); **C** several guitars in one song, distortion, techniques.
- Until song mode ships, uploads are **solo guitar or solo piano** recordings, max 5 min (free tier).
- **Personal use only** (ADR-0009): a transcription is private to its uploader. No public song pages, sharing links or catalogue; uploaded audio is deleted after processing; separated stems are never downloadable. Public sharing would need publisher licensing.
- Monetisation later: free tier with monthly quota; paid tier with longer clips, more jobs, priority queue.

## Tech stack (defaults — ask before changing)
- **Mobile:** Expo (React Native, TypeScript strict), expo-router, TanStack Query, alphaTab rendered in a WebView (renders both standard notation and tab).
- **API:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL 16.
- **Rust kernels:** CPU-bound algorithms we write ourselves (tab-fingering Viterbi first) are Rust, exposed to Python via PyO3 + maturin as `pipeline._tabcore`. Move code to Rust only when profiling shows our own Python is the bottleneck (ADR-0003).
- **Queue:** `JobQueue` interface. Redis Streams for local dev and the MVP (Valkey image locally, ADR-0007); SQS on the AWS scale-up path.
- **Object storage:** Cloudflare R2 through the S3 API (boto3 + `S3_ENDPOINT_URL`); SeaweedFS locally (ADR-0007). Clients use presigned URLs only. No provider-specific SDK calls (ADR-0002).
- **Auth:** Clerk (ADR-0008). The app signs in with `@clerk/expo` and Clerk's native sign-in screen (TD-22); the API only validates JWTs against the issuer's JWKS and never stores passwords. Locally, `make token` issues dev tokens signed with a throwaway secret (TD-17); `make api CLERK_ISSUER=https://<instance>.clerk.accounts.dev` accepts the app's Clerk sign-ins instead.
- **ML pipeline (CPU-only by default):** Basic Pitch for audio→MIDI: the model file is vendored in `pipeline/models/basic_pitch/` and run with ONNX Runtime; its pre/post-processing is ported in `pipeline/basic_pitch.py` (the `basic-pitch` package can't install on Python 3.12, see TD-11), our port of librosa's beat tracker for beat and tempo, fed by Basic Pitch onset activations (`pipeline/beats.py`; librosa itself is not a dependency, ADR-0005), our own MusicXML writer (`pipeline/musicxml.py`, ADR-0006; music21 is not a dependency), and a Rust tab-fingering module (Viterbi over playable positions). Demucs (htdemucs) source separation is an optional extra, off by default (`separate` is a passthrough).
- **Infra (MVP):** self-hosted OpenStack VMs, docker-compose (or k3s), CPU workers only, Postgres on a VM with nightly backups to R2, Terraform via the OpenStack provider (ADR-0004).
- **Infra (scale-up path):** AWS. API on ECS Fargate; GPU workers on an EC2 GPU autoscaling group or EKS + KEDA, scaled on queue depth.
- **Licences:** check every model and library licence before adding it. The app is commercial, so no non-commercial weights (for example, madmom's pretrained models are non-commercial).

## Architecture

```
Mobile ──► API (stateless) ──► Postgres (jobs, users, scores)
  │            │
  │            └──► Queue ──► cpu-worker (normalize, quantize, notation, tab)
  │                      └──► ml-worker (separation, transcription; CPU in the MVP, GPU later)
  └──presigned PUT/GET──► R2 / S3 API (audio + artifacts)
```

### Job flow
1. `POST /jobs` creates a job (`pending_upload`) and returns a presigned PUT URL.
2. The client uploads audio directly to object storage. Audio never passes through the API.
3. `POST /jobs/{id}/submit` checks the upload's size and type (one HEAD request) and the user's quota, then enqueues the job. Duration and format need the audio decoded, so the normalize stage checks them and fails the job without retrying.
4. Workers run the stages in order: `normalize → separate → transcribe → quantize → notation → tab`. Each stage reads and writes artifacts under `s3://…/users/{user_id}/jobs/{job_id}/{stage}/`.
5. Workers record job and stage status in Postgres. The client polls `GET /jobs/{id}` and also receives an Expo push notification on completion (`WORKER_NOTIFIER=expo`, TD-25; log-only by default). After `normalize`, an identical earlier job of the same user is reused instead of recomputed (dedup cache, TD-19).
6. Outputs: MusicXML (notation; for guitar also `tab.musicxml` with a TAB staff) and MIDI. alphaTex and Guitar Pro 7 are derived from the MusicXML by alphaTab's exporters (`AlphaTexExporter`, `Gp7Exporter`), so the pipeline doesn't write them. User edits are saved as new `score_versions`; originals are never overwritten.

## Scalability rules (non-negotiable)
- **Stateless API.** No local disk state and no in-memory sessions. Any instance can serve any request. API p95 latency target is under 200 ms.
- **All heavy work is async.** The API must never run ML inline.
- **Separate CPU and ML queues.** Keep them separate even while one CPU worker pool serves both (MVP), so GPU workers can be added by config. On the scale-up path they autoscale independently on queue depth and GPU workers scale to zero when idle.
- **Idempotent stages.** Every stage can be re-run safely. Use retries with exponential backoff and a dead-letter queue. Set a max of 3 attempts per stage.
- **Deduplication cache.** Key results on `sha256(normalized_audio) + pipeline_version` and reuse them instead of recomputing.
- **Versioned pipeline.** Every result stores the `pipeline_version` that produced it, so model upgrades never silently change old results.
- **Quotas and rate limits.** Enforce per-user limits in Redis. Priority queue for the paid tier.
- **Tenant isolation.** Scope every DB query by `user_id`. Prefix every object key with the user ID. Presigned URLs expire in 15 minutes or less.
- **Lean database.** Postgres holds metadata only; blobs go to object storage. Index `jobs(user_id, created_at)` and `jobs(status)`.
- **Observability.** Use structured JSON logs and OpenTelemetry traces, both carrying `job_id`. Track these metrics: queue depth, per-stage duration, failure rate and GPU utilisation. Metrics are Prometheus: API `/metrics` (queue depth, request latency) and worker `:9100` (TD-20).
- **12-factor config.** All configuration comes from environment variables. No secrets in the repo.

## Repo layout (monorepo)
```
apps/mobile/            Expo app
services/api/           FastAPI app
services/worker/        Queue consumer; thin wrapper around packages/pipeline
packages/platform/      Infra code shared by api and worker (settings, DB, storage, queue); imports as `tabscribe_platform`
packages/pipeline/      Transcription library — NO infra dependencies
  src/pipeline/           Python package (stages, runner, CLI)
  rust/                   Rust crate built into pipeline._tabcore (maturin)
tools/preview/           Dev-only page: `make view` renders out/ with alphaTab (notation + tab, playback, exports)
infra/terraform/
docs/adr/               Architecture decision records
docs/tech-debt/README.md  Deliberate trade-offs: concept, pros, cons, when to revisit
docker-compose.yml
pyproject.toml          uv workspace root + shared ruff/mypy/pytest config
```
- `packages/pipeline` must run standalone, for example `python -m pipeline transcribe in.wav --out out/`, so model work can be iterated without the app or infra.

## Conventions
- `make check` runs every CI check (lint, types, tests, Rust); `make help` lists all shortcuts. `make up` / `make down` start and stop the local Docker services.
- Backend locally: `make up && make migrate`, then `make api` and `make worker` (on the host, reloading), or `make stack` (both in Docker, the images we ship). `make e2e` runs the end-to-end check against either; `make token USER=alice` prints a dev JWT.
- Supported dev/CI platforms: Linux and Apple Silicon macOS (`[tool.uv] environments`); Intel Macs are excluded because Demucs pins numpy<2 there.
- Optional Demucs separation: `make setup-separation`, then `--separation`; its tests run with `make test-separation`, not in CI.
- Python: uv, ruff, mypy --strict, pytest. Rust: cargo fmt, clippy `-D warnings`, cargo test. TypeScript: strict mode, ESLint + Prettier, Jest with React Native Testing Library.
- Mobile (`apps/mobile`, Expo SDK 57): add packages with `npx expo install` (it picks SDK-compatible versions). Check the versioned Expo docs (docs.expo.dev/versions/v57.0.0) rather than memory; Expo changes between SDKs. `ios/` and `android/` are generated (Continuous Native Generation): never edit them, configure native behaviour in `app.json` and config plugins. Screens live in `src/app/` (expo-router); other code goes elsewhere in `src/`. The app needs a development build, not Expo Go (Clerk's native sign-in): `make mobile-ios` / `make mobile-android` build and install it (Android needs JDK 17, TD-23), then `make mobile` starts the dev server. A USB Android phone: `make mobile-usb` then `make mobile USB=1`; a phone on Wi-Fi: `HOST_IP=<LAN IP>`; `make mobile-check` runs the app's CI checks. Secrets never go in `EXPO_PUBLIC_*` variables (they're bundled into the app); `apps/mobile/.env.local` holds the Clerk publishable key (see `.env.example`). After API changes, `make api-types` regenerates the app's API types (TD-21).
- Every deliberate trade-off or piece of technical debt gets an entry in `docs/tech-debt/README.md` (concept, pros, cons, when to revisit) in the same commit.
- Pipeline tests are golden-file tests on short fixture clips. Track note-level F1 with `mir_eval` and fail CI on regressions: `make test-accuracy` scores GuitarSet excerpts and synthetic piano clips against `tests/accuracy_baseline.json` (`UPDATE_BASELINE=1` to accept new numbers in the same commit as the change).
- No new dependency without a one-line justification in the PR or commit.
- Make small, focused commits. Record architecture changes as an ADR in `docs/adr/` and update this file.
- Before writing code for a new phase, propose a plan and wait for approval.

## Build phases
1. **Pipeline CLI**: audio → MIDI → MusicXML → tab, plus fixtures and accuracy tests. No app, no infra.
2. **Backend**: API, workers, queue and local docker-compose, tested end to end (`make e2e`).
3. **Mobile app**: auth, record/upload, job status, alphaTab rendering, export.
4. **Editor**: note and fret corrections, with score versions.
5. **Production**: Terraform, autoscaling, monitoring, billing (RevenueCat for in-app subscriptions).

## Out of scope for now
Transcribing vocals, bass and drums; telling several guitars apart and guitar techniques (bends, slides, hammer-ons) until step C; real-time transcription; public sharing of transcriptions.
