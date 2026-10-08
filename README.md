# Riffscribe

Record or upload a solo guitar or piano take on your phone and get back editable sheet music and
guitar tab, which you can play back and export as PDF, Guitar Pro, MusicXML and MIDI.

(The code and infrastructure still use the working name `tabscribe`.)

## How it works

```
Phone app ──► API ──► Postgres (jobs, users, scores)
  │            │
  │            └──► Queue ──► worker: normalize → separate → transcribe → quantize → notation → tab
  └── uploads and downloads straight to object storage (presigned URLs)
```

The app uploads audio directly to object storage and asks the API to transcribe it. A worker runs
the pipeline (Basic Pitch for notes, our own beat tracker and MusicXML writer, a Rust tab
fingering stage) and the app shows the result with alphaTab. [CLAUDE.md](CLAUDE.md) has the full
architecture, rules and conventions; [docs/adr](docs/adr) the decisions behind it; and
[docs/tech-debt](docs/tech-debt/README.md) every deliberate trade-off with its pros and cons.

## Repository

| Path | What |
|---|---|
| `apps/mobile` | The Expo (React Native) app. [Its README](apps/mobile/README.md) covers running it on a phone. |
| `services/api` | FastAPI: jobs, uploads, quotas, push tokens. |
| `services/worker` | Queue consumer that runs the pipeline and sends notifications. |
| `packages/pipeline` | The transcription library and CLI; runs without any of the services. |
| `packages/platform` | Shared settings, database models and migrations, storage, queue. |
| `tools/preview` | `make view`: a local page that renders a pipeline output with alphaTab. |
| `infra/` | Terraform (Phase 5). |

## Quick start

Requirements: macOS on Apple Silicon or Linux, [uv](https://docs.astral.sh/uv/), Rust, Node 20+,
Docker. `make help` lists every shortcut.

```sh
make setup                     # Python packages, the Rust extension, the app's npm packages
make check                     # everything CI runs: lint, types, tests, Rust, the app
```

**Transcribe a file, no services needed:**

```sh
make run FILE=~/Music/riff.m4a INSTRUMENT=guitar   # writes out/
make view                                          # notation + tab with playback, in the browser
```

**The backend:**

```sh
make up && make migrate        # Postgres, Valkey (Redis) and SeaweedFS (S3) in Docker
make api                       # the API on :8000, reloading on changes
make worker                    # a worker serving both queues
make token USER=alice          # a dev access token for curl
make e2e                       # upload, transcribe, download: the whole flow
```

`make stack` runs the API and a worker in Docker instead (the images we ship).

**The app:** see [apps/mobile/README.md](apps/mobile/README.md).

## Status

Phases 1 (pipeline), 2 (backend) and 3 (mobile app) are built; transcription quality has known
gaps listed in the tech-debt log. Next: a staging environment (OpenStack, Cloudflare R2, EAS
builds, Google Play internal testing), then the editor (Phase 4) and production (Phase 5).
