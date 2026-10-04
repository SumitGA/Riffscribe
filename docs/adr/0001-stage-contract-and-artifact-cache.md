# ADR-0001: Pipeline stage contract and artifact cache

- Status: accepted
- Date: 2026-10-04

## Context

The pipeline runs `normalize → separate → transcribe → quantize → notation → tab`.
CLAUDE.md requires every stage to be idempotent and re-runnable, every result to carry the
`pipeline_version` that produced it, and `packages/pipeline` to have no infra dependencies.
Workers (Phase 2) will retry failed stages, so a stage must never leave half-written output.

## Decision

**Stage contract.** A stage is a class with:

| Member | Meaning |
|---|---|
| `name` | `StageName` (`normalize`, `separate`, …) |
| `version` | String; bump whenever the stage's output for the same input can change |
| `requires` | The upstream output types it reads (e.g. `NormalizedAudio`) |
| `applies(cfg)` | `False` to skip (e.g. `tab` for piano) |
| `run(inputs, ctx) -> StageOutput` | Reads typed inputs, writes files via `ctx`, returns a typed Pydantic model |

Inputs and outputs are frozen Pydantic models. Files are referenced by `ArtifactRef`
(path relative to the work dir + sha256), never by absolute path, so a work dir can be moved
to/from object storage unchanged.

**Work dir layout** mirrors the object-storage layout `…/jobs/{job_id}/{stage}/`:

```
workdir/
  source/   manifest.json  <original upload>
  normalize/manifest.json  audio.wav
  transcribe/manifest.json notes.json  raw.mid
  …
```

**Cache key.** `sha256(canonical JSON of {stage, stage version, full PipelineConfig, upstream outputs})`.
Upstream outputs include their artifacts' sha256, so a change anywhere upstream changes every
downstream key automatically.

**Cache hit** = `manifest.json` exists, its `cache_key` matches, and every listed artifact exists
with a matching sha256. Otherwise the stage re-runs.

**Atomic writes.** A stage writes into `workdir/.tmp-{stage}-{uuid}/`; on success the runner
writes `manifest.json` and renames the temp dir over `workdir/{stage}/`. A crash leaves at worst
a stray temp dir, which is ignored and cleaned on the next run.

**Pipeline version** = `{package version}+{8-char hash of every (stage name, stage version)}`, so
bumping any stage version changes `pipeline_version` without a manual step.
The dedup key from CLAUDE.md is `sha256(normalized PCM) + pipeline_version`.

## Consequences

- Re-running is always safe and cheap; `--force` / `--from-stage` override the cache.
- Hashing the *whole* config over-invalidates (changing the guitar tuning re-runs `transcribe`).
  Accepted for correctness; see `docs/tech-debt/README.md` (TD-6).
- Correctness depends on developers bumping `version` when stage behaviour changes; golden tests
  catch most misses.
