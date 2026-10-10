# Technical debt and trade-offs

Every shortcut or trade-off we take on purpose is listed here. Each entry explains the
**concept** behind it, the **pros and cons**, and **when to revisit**. Taking on debt is fine
when it is deliberate, written down and has an exit plan; the danger is debt nobody remembers.

Formal decisions are in [`docs/adr/`](../adr/). This file is the plain-language companion.

| ID | Trade-off | Area | Revisit when |
|---|---|---|---|
| [TD-1](#td-1-cpu-only-pipeline-no-source-separation) | CPU-only pipeline, no source separation | Pipeline | Users upload noisy or mixed audio; accuracy plateaus |
| [TD-2](#td-2-self-hosted-vms-instead-of-managed-cloud) | Self-hosted VMs instead of managed cloud | Infra | Paying users, or an outage costs real money |
| [TD-3](#td-3-redis-streams-as-the-production-queue) | Redis Streams as the production queue | Infra | Job volume grows or a lost job becomes costly |
| [TD-4](#td-4-self-managed-postgres) | Self-managed Postgres | Infra | Any real user data exists |
| [TD-5](#td-5-two-languages-python--rust) | Two languages (Python + Rust) | Code | Adding contributors or more Rust modules |
| [TD-6](#td-6-cache-key-hashes-the-whole-config) | Cache key hashes the whole config | Pipeline | Config grows or re-runs get expensive |
| [TD-7](#td-7-stage-versions-are-bumped-by-hand) | Stage versions are bumped by hand | Pipeline | A stale-result bug slips past golden tests |
| [TD-8](#td-8-small-partly-synthetic-test-fixtures) | Small, partly synthetic test fixtures (Guitar-TECHS is the held-out guitar) | Testing | Before claiming accuracy numbers publicly |
| [TD-9](#td-9-ffmpeg-as-an-external-program) | ffmpeg as an external program | Pipeline | Building the production worker image |
| [TD-10](#td-10-our-own-loudness-meter-instead-of-pyloudnorm) | Our own loudness meter instead of pyloudnorm | Pipeline | If a standards-compliance issue is reported |
| [TD-11](#td-11-vendored-basic-pitch-model-and-ported-code) | Vendored Basic Pitch model and ported code | Pipeline / legal | Before launch (legal review); when upstream releases |
| [TD-12](#td-12-our-own-beat-tracker-port) | Our own beat tracker port | Pipeline | Tempo errors show up in the accuracy suite |
| [TD-13](#td-13-simple-rhythm-and-key-heuristics) | Simple rhythm and key heuristics | Pipeline | Users correct bar lines, triplets or keys often |
| [TD-14](#td-14-our-own-musicxml-writer) | Our own MusicXML writer | Pipeline | Notation needs grow (voices, meters) or renderers complain |
| [TD-15](#td-15-tab-fingering-by-cost-rules) | Tab fingering by cost rules and a learned position prior | Pipeline | Guitarists often move notes to other strings |
| [TD-16](#td-16-decoding-thresholds-tuned-on-guitarset) | Decoding thresholds tuned on GuitarSet | Pipeline | Real recordings disagree with the tuning set; piano data appears |
| [TD-17](#td-17-local-dev-token-issuer-instead-of-a-real-auth-provider) | Local dev token issuer instead of a real auth provider | Backend / security | First deployment (refuse `JWT_DEV_SECRET` outside local) |
| [TD-18](#td-18-simple-quotas-and-rate-limits) | Simple quotas and rate limits | Backend / billing | Billing (Phase 5), or users complain about lost quota |
| [TD-19](#td-19-dedup-cache-per-user-reused-after-normalize) | Dedup cache per user, reused after normalize | Backend / cost | Profiling shows many identical uploads across users |
| [TD-20](#td-20-observability-prometheus-metrics-and-a-minimal-trace) | Observability: Prometheus metrics and a minimal trace | Ops | First production deploy; GPU workers |
| [TD-21](#td-21-app-api-types-generated-from-a-committed-openapi-copy) | App API types generated from a committed OpenAPI copy | Mobile / API | openapi-typescript supports TypeScript 6; old app versions in the wild |
| [TD-22](#td-22-clerks-native-sign-in-screen) | Clerk's native sign-in screen | Mobile / auth | Paid Apple account (Apple sign-in); branding needs beyond Clerk's theme |
| [TD-23](#td-23-local-android-builds-jdk-17-and-a-slow-react-native-repository) | Local Android builds: JDK 17 and a slow React Native repository | Mobile / tooling | Moving builds to EAS or CI; React Native supports newer JDKs |
| [TD-24](#td-24-score-viewer-alphatab-in-a-webview-from-local-files) | Score viewer: alphaTab in a WebView from local files | Mobile | Long scores feel slow; editing (Phase 4) needs tighter integration |
| [TD-25](#td-25-push-notifications-through-expos-push-service) | Push notifications through Expo's push service | Backend / mobile | Many users (receipts, batching); dropping Expo |
| [TD-26](#td-26-chord-names-by-template-matching) | Chord names by template matching | Pipeline | Chord accuracy plateaus, or users need sus/dim/inversions |
| [TD-27](#td-27-synced-playback-from-the-phones-own-copy-of-the-take) | Synced playback from the phone's own copy of the take | Mobile / legal | Users want playback on other devices, or the retention policy changes |
| [TD-28](#td-28-guitar-sound-from-a-trimmed-musescore_general-font) | Guitar sound from a trimmed MuseScore_General font | Mobile / legal | Before a store release (notices screen); users want a better piano |
| [TD-29](#td-29-staging-is-one-vm-with-logs-only) | Staging is one VM with logs only | Infra | Real users, or staging downtime blocks work |
| [TD-30](#td-30-terraform-state-in-a-local-file) | Terraform state in a local file | Infra | A second person runs Terraform, or before production |
| [TD-31](#td-31-the-editor-shows-changes-after-saving) | The editor shows changes after saving | Mobile | Users find editing slow or confusing |
| [TD-32](#td-32-production-in-the-home-lab) | Production in the home lab | Infra / ops | The first paying customers, or any outage that costs users |

---

## TD-1: CPU-only pipeline, no source separation

**Concept.** *Source separation* splits a recording into instruments ("stems"): vocals, drums,
bass, guitar, piano. Demucs is a neural network that does this well, but it is large and slow
without a GPU. A *GPU* runs thousands of small calculations in parallel, which is what neural
networks need; a CPU runs a few fast ones at a time.

**What we did.** `separate` passes the audio through unchanged. Basic Pitch (a small model) does
transcription on CPU. Demucs is an optional extra we can switch on.

**Pros**
- No GPU bill; runs on any VM, including your OpenStack servers.
- v1 only accepts *solo* guitar or piano, so there is little to separate anyway.
- Smaller install (no CUDA, ~2 GB less) and faster cold starts.

**Cons**
- Background noise, a metronome or a second instrument goes straight into transcription and
  shows up as wrong notes.
- When we add full-band support (out of scope for v1), separation becomes mandatory and so does
  a GPU or much slower CPU jobs.

**Measured (commit 9, Apple Silicon CPU, `htdemucs_6s`).** Install: ~630 MB (torch). Model load
~16 s; separating 30 s of audio takes 12 s, so ~2 minutes for a 5-minute clip; peak memory
1.9 GB (the whole default pipeline peaks at 372 MB). On our synthetic solo guitar clip only 12 %
of the energy landed in the "guitar" stem and 75 % in "other": transcribing that stem would
have lost most of the notes. For v1's solo recordings, passthrough is the more accurate choice,
not just the cheaper one.

**Learned from a real recording with a background voice.** A voice under the guitar made the
transcription sloppy exactly where it spoke (Basic Pitch turns any pitched sound into notes).
Demucs's vocals stem located it in 4 places, only ~5 s (3 %) of a 3.5-minute song. Separating
the whole song fixed those bars but *added* notes in 63 of 135 other bars (separation artifacts)
and took 84 s / 3 GB, so separation should run only on stretches with a voice. Detecting those
cheaply is unsolved: Silero VAD (MIT, 2 MB) finds clear speech and never fires on GuitarSet, but
scored 0.000 on this quiet voice while plain guitar sometimes scored 0.75. Next candidates: voice
cues in Basic Pitch's pitch contours (glides, vibrato), or separation as a user choice.

**How to use it anyway.** `make setup-separation` (or `uv sync --group separation`) installs
Demucs; `--separation` turns it on per run; `make test-separation` runs its test. Without the
install, the stage fails with a message saying how to add it. Demucs pulls in `lameenc`
(LGPL-3.0, an MP3 encoder we never call), another reason to keep it out of the default install.

**Revisit when** many users upload noisy or mixed recordings, or the accuracy tests plateau.

---

## TD-2: Self-hosted VMs instead of managed cloud

**Concept.** *Managed* services (AWS ECS, SQS, RDS…) mean the provider runs, patches, backs up
and fails over the software for you; you pay for that. *Self-hosted* means you run the same kind
of software on your own machines. A *single point of failure* is any one component whose failure
takes the whole app down, for example one VM that runs both the database and the API.

**What we did.** The MVP backend runs with docker-compose on OpenStack VMs (ADR-0004). The code
stays cloud-neutral (S3 API, `JobQueue` interface, env-var config), so moving later is mostly
configuration.

**Pros**
- Close to zero cost while there are no users.
- Full control; no vendor lock-in.
- Same docker-compose file in dev and prod, so fewer surprises.

**Cons**
- You are the operations team: OS patches, disk full, certificates, monitoring, 3 a.m. restarts.
- No automatic scaling: a traffic spike queues jobs instead of adding workers.
- Single points of failure until we run at least two VMs for the API and workers.

**Revisit when** there are paying users, or when ops work starts eating feature time.

---

## TD-3: Redis Streams as the production queue

**Concept.** A *job queue* holds work items until a worker takes them. Important properties:
*durability* (jobs survive a crash), *at-least-once delivery* (a job may run twice, which is why
stages are idempotent) and a *dead-letter queue* (DLQ: where jobs go after failing 3 times so
they stop retrying). SQS gives these out of the box. Redis Streams gives the building blocks
(consumer groups, pending-entry lists), and we write the retry and DLQ logic ourselves.

**Pros**
- One Redis already serves quotas and rate limits, so there's one less system to run.
- Very fast, simple locally, free.
- Behind the `JobQueue` interface, so SQS can replace it without touching workers.

**Cons**
- Redis keeps data in memory. Without persistence (AOF with `fsync everysec`) a crash can lose
  the last second of jobs. With it, a full disk or memory still breaks the queue.
- Retry, back-off and DLQ handling are our code, so they're our bugs.
- Queue-depth autoscaling has to be built by hand.

**How it's built** (`tabscribe_platform/jobqueue.py`)
- One stream per queue and priority (`cpu`/`ml` × `high`/`normal`), one consumer group.
  Workers read `high` first.
- Streams have no delayed delivery, so retries wait in a sorted set scored by due time. A Lua
  script moves due messages into their streams, so two workers never both move one. That script
  touches keys it isn't passed, which **rules out Redis Cluster** (fine on one node).
- A message whose worker neither acks nor sends a heartbeat within the visibility timeout
  (`QUEUE_VISIBILITY_TIMEOUT_S`) is reclaimed with `XAUTOCLAIM` and counts as a failed
  attempt. After the last attempt it is handed to a worker once more, which fails the job and
  dead-letters it, so a message that crashes workers neither loops nor leaves its job `running`.
- Acked entries are deleted (`XDEL`), so stream length is the backlog.

**Revisit when** daily job volume grows, or a lost job means a refund.

---

## TD-4: Self-managed Postgres

**Concept.** A *backup* you have never restored is a hope, not a backup. *RPO* (recovery point
objective) is how much data you can afford to lose; *RTO* (recovery time objective) is how long
you can afford to be down. Managed databases give point-in-time recovery (RPO of minutes) and
automatic failover.

**What we will do (Phase 2).** Postgres in a container on a VM, nightly `pg_dump` uploaded to R2,
and a scripted restore we actually test.

**Pros**: free, simple, and Postgres only holds metadata (audio lives in R2), so it stays small.

**Cons**
- Nightly dumps mean an RPO of up to 24 hours: a disk failure could lose a day of jobs and edits.
- No failover; a VM outage is app downtime.

**Revisit when** real user edits exist. The cheap next step is WAL archiving (continuous
backup) with `pgBackRest` or `wal-g`, before paying for a managed database.

---

## TD-5: Two languages (Python + Rust)

**Concept.** Python is quick to write and has the music/ML libraries; it is slow for tight loops
written in Python itself. Rust compiles to fast native code with predictable memory use. *FFI*
(foreign function interface) is how one language calls another; *PyO3* lets Python call Rust as
if it were a normal module, and *maturin* builds both into one installable package.

Most of our heavy work already runs in native code that Python only calls (PyTorch, ONNX Runtime,
ffmpeg, numpy), so rewriting those parts in Rust gains almost nothing. Our own algorithms, like
the tab fingering search, are where Rust wins by 100× or more (ADR-0003).

**Pros**
- Big speed and memory wins exactly where our own code is hot.
- Rust's type system catches many bugs at compile time.
- Python stays where the ecosystem is (Basic Pitch, librosa, music21, mir_eval).

**Cons**
- Two toolchains, two linters and two test runners; slower CI and onboarding.
- The Python/Rust boundary must be kept small. Passing many tiny objects across it is slow, so
  we pass arrays.
- Debugging across the boundary is harder (a Rust panic surfaces as a Python exception).

**Rule:** move code to Rust only when profiling shows *our* Python code is the bottleneck.

---

## TD-6: Cache key hashes the whole config

**Concept.** A *cache key* is a fingerprint of everything that affects a result; if the
fingerprint matches, we reuse the stored result instead of recomputing. If the key misses
something that matters, you get a *stale cache* (wrong old result). If it includes things that
don't matter, you get *over-invalidation* (needless recomputation).

**What we did.** Each stage's key includes the *entire* `PipelineConfig` (ADR-0001).

**Pros**: it can never produce a stale result because of a forgotten config field. That's the
worse bug, because it's silent.

**Cons**: changing a field that only affects a late stage (e.g. guitar tuning, used only by
`tab`) also re-runs early stages like `transcribe`, which is the expensive one.

**Revisit when** users can re-run with different settings (Phase 4 editor) and the extra
transcription cost shows up. The fix: each stage declares the config fields it reads, and a test
checks that the declaration is complete.

---

## TD-7: Stage versions are bumped by hand

**Concept.** Each stage has a `version`. `pipeline_version` is derived from all of them, and old
results stay tied to the version that produced them, so model upgrades never silently change old
scores.

**Cons**: if someone changes a stage's behaviour and forgets to bump its version, cached results
from the old behaviour are reused under the same version.

**Mitigation**: golden-file tests fail when deterministic output changes, which prompts the bump.
Accuracy baselines record the `pipeline_version` too.

**Revisit when** a stale-result bug ever reaches users. Option: CI fails if a stage's source
files change without its version changing.

---

## TD-8: Small, partly synthetic test fixtures

**Concept.** *Fixtures* are fixed test inputs with known correct answers (*ground truth*).
*Overfitting to the test set* means tuning the system until it scores well on those few clips
without getting better in general. *Synthetic* audio (rendered from MIDI with a sample library)
is perfectly labelled but cleaner than real recordings.

**What we will do.** GuitarSet (CC BY 4.0) excerpts for guitar; synthesized plus self-recorded
clips for piano. We avoid MAESTRO because its licence is non-commercial.

**Pros**: commercial-safe, small enough for CI, perfect labels.

**Cons**
- Scores on clean or synthetic clips overstate real-world accuracy (phone mic, room echo).
- Few clips means a single clip can swing the average.

**What we have (commit 10).** 6 GuitarSet excerpts (20 s each, mic audio, 6 players, 5
styles, comp and solo; 4.1 MB, fetched by HTTP range requests from the Zenodo zips) and 2
synthesized piano clips. Baselines in `tests/accuracy_baseline.json`; CI fails if a metric drops
more than 0.02. Mean guitar note F1 is 0.76; piano (synthetic) 0.83, which flatters it.

**Held-out guitar (Step A5).** Basic Pitch trained on most of GuitarSet (TD-11), so GuitarSet
flatters it. 8 Guitar-TECHS excerpts (CC BY 4.0; electric guitar through a miked amp, 3 players;
4 solos and 4 chord recordings; 3.5 MB) are scored as their own suite (`mean guitar_techs` in
the report): note F1 0.74 and tab string accuracy 0.53 there, vs 0.82 and 0.82 on GuitarSet.
These are the numbers to quote. Their MIDI comes from a hexaphonic pickup whose offset from the
audio differs per recording (+30 or -35 ms), so `make_fixtures.py` measures it per file without
a transcription model. No beat or chord annotations, so those metrics stay GuitarSet-only, and
tuning scripts never use these clips.

**Revisit before** publishing accuracy claims. Grow a held-out set of real phone recordings that
is never used for tuning; add acoustic-guitar audio no model trained on.

---

## TD-9: ffmpeg as an external program

**Concept.** Phones record in compressed formats (m4a/AAC, mp3, ogg). Turning those into plain
samples is *decoding*, and ffmpeg can decode almost anything. You can use it in two ways:
*link* it as a library into our process (e.g. PyAV), or *run* the `ffmpeg` program and read its
output. Licences care about this difference: the LGPL lets commercial apps use a library if users
can swap it, and some ffmpeg builds are GPL (because of extra codecs), which would put
obligations on the code that links them.

**What we did.** `normalize` runs the `ffmpeg` program (`FFMPEG_BINARY` env var, default
`ffmpeg`), which writes raw samples to a temp file that we load in one allocation.

**Pros**
- Decodes every format users will send, with one well-tested tool.
- Running it as a separate program keeps a clean licence boundary; our code never links it.
- A crash or hang in a decoder can't take down the worker (there is a 120 s timeout).

**Cons**
- One more thing to install on every machine (dev, CI, the worker image).
- About 20–50 ms to start a process; irrelevant next to transcription time.
- **We must ship an LGPL build** (configured without `--enable-gpl` and `--enable-nonfree`) in
  the production image. Homebrew and Ubuntu packages are GPL builds; fine for dev and CI, which
  are not distributed.
- A file the user can't decode and an ffmpeg bug both look like "could not decode". We treat both
  as bad input (no retry).

**Production build (done in Phase 2).** The worker image compiles ffmpeg from a source tarball
pinned by version and sha256 (`Dockerfile`, stage `ffmpeg`). It is configured without
`--enable-gpl`/`--enable-nonfree`, with no external libraries and only the demuxers and decoders
for the upload types the API accepts (m4a/AAC, mp3, wav, flac, ogg/Vorbis/Opus, ALAC). The build
fails if its configuration ever contains `--enable-gpl` or `--enable-nonfree`; the image keeps
the configure line (`/usr/share/doc/ffmpeg/BUILDCONF`) and the LGPL text next to the binary.
`make e2e` decodes m4a and mp3 uploads with it.

**Revisit when** the API accepts a new upload type (add its demuxer and decoder), or before
launch for the legal review (LGPL notice in the app's licences screen, offer of source).

---

## TD-10: Our own loudness meter instead of pyloudnorm

**Concept.** *Loudness normalization* makes every recording equally loud, so later stages see
consistent levels. *LUFS* (ITU-R BS.1770) is the standard way to measure loudness the way ears
hear it: filter the audio (K-weighting), measure energy in 400 ms blocks, then ignore silent and
very quiet blocks (*gating*). pyloudnorm implements this, but it copies the whole recording into
several 64-bit arrays: about 260 MB of extra memory for a 5-minute clip.

**What we did.** `pipeline/loudness.py` implements the same algorithm (about 40 lines) and filters
the audio 2 seconds at a time. pyloudnorm stays as a *test oracle*: a test checks that both agree
within 0.05 LU on several signals and sample rates. Together with other changes, a 5-minute
normalize went from 614 MB to 178 MB peak memory, and 105 MB of that is Python and its libraries.

**Pros**
- Memory stays flat no matter how long the clip is, which means smaller, cheaper worker VMs.
- One less runtime dependency.

**Cons**
- Our code to maintain. The test against pyloudnorm protects us, but only for the signals it
  covers.
- Mono only (all we need; v1 downmixes everything to mono).

**Revisit when** someone reports loudness differences against a reference meter, or we need
multichannel.

---

## TD-11: Vendored Basic Pitch model and ported code

**Concept.** *Vendoring* means copying a third-party file into our repo instead of installing it
as a package. A *port* is a rewrite of someone else's code into our codebase, keeping its
behaviour. A *parity test* proves that the port still does what the original did, by comparing
outputs on the same inputs. *Training-data provenance* is about which data a model learned from:
a model's licence and the licences of its training data are separate questions.

**What we did.** The `basic-pitch` package (Spotify, Apache-2.0) can't be installed on Python
3.12: its last release pins a TensorFlow version that has no 3.12 builds. The model itself is a
230 KB ONNX file. We:
- copied `nmp.onnx`, its `LICENSE` and `NOTICE` into `pipeline/models/basic_pitch/`, unmodified;
- ported about 200 lines of pre/post-processing into `pipeline/basic_pitch.py`, dropping
  pitch bends (out of scope for v1) and the TensorFlow, librosa, pretty_midi and mir_eval
  dependencies;
- recorded the real package's outputs once, in a throwaway environment, and committed them as
  fixtures. Tests check model activations, note decoding and the full path against them.

**Pros**
- Stays on Python 3.12 with one small runtime dependency (`onnxruntime`) instead of TensorFlow
  (500 MB+).
- We control memory: batching 4 windows instead of 16 saved about 140 MB with no speed loss.
- The decoding loop is our code now, so we could move it to Rust (ADR-0003): on 5 minutes of
  guitar it went from 2.4 s and 145 MB to 32 ms and under 1 MB, with identical notes. Randomized
  tests check the Rust version against the Python port kept in `tests/basic_pitch_oracle.py`.

**Cons**
- We maintain the port. Upstream fixes must be copied by hand; the parity fixtures make that
  safe (re-record, then compare). Upstream has been quiet since August 2024.
- Apache-2.0 obligations: keep `LICENSE` and `NOTICE` with the model and in any distribution,
  and mark our modified code as changed (done in the module docstring).
- **Training-data caveat.** The weights are Apache-2.0, but Basic Pitch was trained partly on
  datasets licensed for research only (e.g. MedleyDB, iKala). Whether that affects commercial use
  of the weights is a legal question, not a technical one. Same grey area as Demucs (ADR-0004).

**Alternatives measured (Step A5 spike, 2026-10-09).** No released model with commercially
usable weights beats Basic Pitch on guitar on CPU today:
- *Kong et al. high-resolution piano model* (code Apache-2.0, weights CC BY 4.0, 172 MB), zero-shot
  on our GuitarSet clips: note F1 0.39-0.57 vs Basic Pitch 0.74-0.89, and 7.5 s vs 0.22 s of CPU
  per 20 s clip. A piano model needs adapting to guitar first.
- *Riley et al. guitar models* (ICASSP 2024; GAPS, ISMIR 2024: 88 % zero-shot / 91 % supervised
  note F1 on GuitarSet) are fine-tuned from Kong's model; their weights are not released.
- *MuScriptor* weights are CC BY-NC (no commercial use); *YourMT3* is GPL-3.0 and takes minutes
  of CPU per 30 s; *SynthTab* data is CC BY-NC; *FretNet / TabCNN* are research code trained on
  GuitarSet with no maintained weights.

**Our GuitarSet numbers flatter Basic Pitch.** Its paper trained on 648 of GuitarSet's 720
recordings (Table 1), so our test and tuning excerpts were very likely in its training data.
A fair comparison, and an honest accuracy number, needs guitar audio no candidate trained on:
Guitar-TECHS (electric guitar, CC BY 4.0, 2025) is one; the owner's own recordings are another.

**Revisit when**
- **Before launch:** get a legal opinion on the training-data question. A fallback is a model
  trained on commercially licensed data (ours or a vendor's).
- **When upstream releases** a version with Python 3.12 support or a better model: re-record the
  fixtures and diff.

---

## TD-12: Our own beat tracker port

**Concept.** *Tempo* is how many beats per minute (bpm) the music has; *beat tracking* finds
the moment of every beat. The classic method (Ellis, 2007) works on an *onset envelope*: a
signal that spikes whenever a new note starts. It finds the tempo by checking which repeat
distance makes the envelope line up with itself (*autocorrelation*), then picks beat times
with *dynamic programming*: the best chain of beats that lands on strong onsets while keeping
a steady spacing.

**What we did.** librosa implements this, but costs 281 MB to install, 30 s of compilation on
every fresh worker and up to 670 MB of memory (ADR-0005). We ported the same algorithm into
`pipeline/beats.py` and feed it from Basic Pitch's own onset detector, so the audio isn't
analysed twice. librosa's outputs are recorded once and the tests require identical results.

**Pros**
- 0.6 s and no memory spike for 5 minutes; no warm-up; nothing extra to install.
- Same results as the well-known library, provably (identical beat frames in tests).

**Cons**
- About 150 lines of ported code to maintain.
- Inherits librosa's limits: one tempo for the whole piece (no gradual speed-ups or rubato
  beyond what the beat chain absorbs), and *octave errors*: very fast music can be reported at
  half speed (175 bpm reads as 87.6) because of a built-in preference for tempos near 120.
- The envelope quality depends on Basic Pitch. A first version that summed raw activations got
  every test tempo wrong; a guard test now checks known tempos end to end.

**Measured (commit 10, `make test-accuracy`).** On 6 GuitarSet excerpts: mean beat F-measure
0.25, tempo right on 4 of 6. No timing bug: where the tracker locks on, beats land within ~0-30
ms of the annotations. The errors are the two classic failure modes:
- *Right tempo, wrong phase*: on bossa nova and jazz comping the beats sit ~0.3-0.4 of a beat
  off, because syncopated chords put the strongest attacks between beats.
- *Wrong metrical level*: funk at 114 bpm read as 152, a 100 bpm song as 140, piano arpeggios at
  72 as 144 (it follows the eighth notes).

**Revisit when**: now that the suite measures it, the beat tracker is the weakest stage. Options,
in order of effort: use bass-register onsets as downbeat/phase evidence; constrain tempo with
note-onset statistics; or a learned beat tracker with commercial-safe code *and* weights (check
both: madmom's models, for example, are non-commercial).

---

## TD-13: Simple rhythm and key heuristics

**Concept.** Turning beat times into sheet music needs more decisions:
- *Quantization*: snapping each note to the nearest grid position (here sixteenth notes, or
  eighth-note *triplets*, three per beat).
- *Meter*: how many beats per bar (4/4 = four).
- *Downbeat*: which beat starts a bar. Music often starts with a *pickup* (anacrusis): a few
  notes before the first full bar.
- *Key*: the scale the piece is in, which sets the key signature (sharps or flats).

**What we did (`pipeline/rhythm.py`).**
- 4/4 only.
- Each beat picks sixteenths or triplets: triplets only with at least two notes in the beat
  that fit triplets at least twice as well.
- The downbeat is the beat position (out of four) where the loudest on-beat notes land.
- Key: Krumhansl-Schmuckler, comparing how long each pitch class sounds with standard
  major/minor profiles.

**Pros**: simple, fast, explainable, and right on clear, steady playing (tests cover jitter,
tempo drift, triplets, pickups and keys).

**Cons**
- Waltzes (3/4), 6/8 and odd meters are notated in 4/4.
- Syncopated music, where the loudest notes are off the downbeat, can get its bar lines shifted.
- Swing, quintuplets and other tuplets are forced onto the sixteenth or triplet grid.
- Key detection can be fooled by harmonics that the transcription reports as extra notes, and
  can't tell relative keys apart well (C major vs A minor) on short clips.

**Learned from a real recording (fingerstyle guitar, 157 bpm).** The first version wrote 27 % of
onsets on odd sixteenths and the score was full of sixteenth rests and ties. Two causes, two fixes:
- *Human timing drift.* A sixteenth at 157 bpm is only 96 ms, so 20-40 ms of drift pushes
  eighths onto sixteenths. Each beat now uses the simplest grid that fits (quarters, then
  eighths) within 45 ms before trying sixteenths or triplets.
- *Strummed and rolled chords.* Strings hit a few ms apart (329 gaps under 35 ms in that
  recording, almost none between 50 and 96 ms) were split across sixteenths. Onsets chained by
  gaps of at most 35 ms, spanning at most 100 ms, are now one chord at the first string.
Together: sixteenth rests -38 %, sixteenths -14 %, dotted eighths -19 % on that recording; no
change in the accuracy suite. Tried and rejected: merging back-to-back notes of the same pitch
(GuitarSet showed they are mostly real repeated plucks; note F1 fell from 0.76 to as low as 0.67).

**Revisit when** users often correct bar lines, triplets or keys in the editor (Phase 4); those
corrections are the best training data for something smarter.

---

## TD-14: Our own MusicXML writer

**Concept.** *MusicXML* is the standard file format for sheet music; every notation program
(MuseScore, Sibelius, Finale, alphaTab) reads it. Writing it means making engraving decisions:
- *Ties* join two written notes into one longer sound, needed when a note crosses a bar line
  or a beat in a way no single note value can show.
- *Tuplets* (here triplets) squeeze three notes into the time of two, shown with a bracket.
- *Voices* let one staff show independent lines (a held bass note under a moving melody).
- *Beaming* groups eighth and sixteenth notes with horizontal bars.
- *Spelling* picks the name of a black key: F# or Gb, which should follow the key signature.

**What we did.** music21 cost 184 MB, wrote random ids (different bytes every run, which
breaks caching and golden tests), didn't write pickup bars and ignored the key when spelling
(ADR-0006). `pipeline/musicxml.py` writes the format directly: ties, triplets, rests, pickups,
key-aware spelling, guitar and piano staves. Randomized tests check that every bar adds up;
golden files pin the exact output.

**Pros**
- Byte-identical output, so caching and golden tests work; no dependency; milliseconds.
- Every decision is ours and visible in one file.

**Cons**
- **One voice per staff.** Notes starting together form a chord; a note held while others move
  is cut where the next chord starts (it still sounds right in our MIDI, but the score shows it
  shorter). Fine for melody-plus-chords, weak for fingerstyle guitar and real piano writing.
- **Piano hands split at middle C**, not by musical sense (a left-hand run above C4 jumps
  staves).
- **No beaming hints.** alphaTab and MuseScore beam by time signature, which is right for
  4/4; other programs may show flags.
- **No accidental marks written**; renderers derive them from pitch and key signature.

**Revisit when** the preview (step 8) or users show cut-off notes or awkward hand splits, or
when Phase 4 editing needs multiple voices.

---

## TD-15: Tab fingering by cost rules

**Concept.** On a guitar the same note can usually be played in several places (E4 is the open
high string, or fret 5 on the B string, fret 9 on G, fret 14 on D...). *Tab* writes down which
string and fret to use. A good choice keeps chords playable (one note per string, fingers not
stretched past ~4 frets) and keeps the hand from jumping around. The *Viterbi algorithm* finds
the best sequence of choices for the whole piece at once, instead of greedily note by note:
each chord gets candidate fingerings with a comfort cost, moving the hand between chords has a
cost, and Viterbi finds the cheapest path through all of them.

**What we did.** `rust/tab.rs` models the fretting hand: a *hand position* is the fret under
the index finger, which reaches that fret and the next 4 without moving. Viterbi runs over
(fingering, hand position) pairs, so a melody inside one box costs nothing and only shifting
the hand is charged (a fixed cost per shift plus a cost per fret). Fingerings also pay for
finger span (heavily beyond 4 frets) and for each note's *position prior*: `-log P(string |
pitch)`, counted from the fingerings GuitarSet players used (`pipeline/models/tab_prior`, from
the tuning excerpts only). At most 64 candidate fingerings per chord (a *beam*), so 5 minutes
take well under a second. Notes that can't be played (below the lowest string, or more notes
than strings) are left out of the tab but stay in the notation, and the stage reports how many.
Tunings: standard and drop D; capo 0-12. Weights were grid-searched on the pipeline's own
transcriptions of 48 GuitarSet tuning excerpts (`tests/tuning/tune_tab.py`).

**Pros**
- Matches how guitarists play: solos stay in one box, chords use common shapes, and a stray
  transcribed note can't drag the whole solo up the neck (it did before the prior).
- Fast, deterministic, and every rule is a named weight, tuned against data.
- No new dependency or model: the prior is a 50-row table of counts.

**Cons**
- The prior comes from GuitarSet's six players, and the test clips are by the same six, so
  the held-out numbers are somewhat optimistic for other players and styles.
- It doesn't know techniques or style: slides, hammer-ons and bends are out of scope for v1.
- Hand movement ignores time: a jump across the neck costs the same with a whole bar to move
  as with a sixteenth note.
- Drop D and capo reuse the standard-tuning prior by string and fret (approximate).
- Only six-string guitar, two tunings.

**Measured (Step A3).** Of the notes we transcribe correctly, our string matches the player's
on 82 % of the test clips' notes on average (was 35 % with the earlier hand-free, low-position
costs): 80-98 % on comping, 55-88 % on solos. On annotated (perfect) notes the hand-free model
reached only 27 % on solos, so the fingering model, not just transcription, was the problem.

**Revisit when** users often move notes to other strings in the editor (Phase 4): those edits
are exactly the data to fit the weights to, or to train a model.

**Related decision.** The pipeline writes tab as MusicXML (a notation staff plus a TAB staff).
alphaTex and Guitar Pro 7 files are produced from it by alphaTab's built-in exporters in the
app, so we don't maintain writers for them and don't need PyGuitarPro (LGPL-3).

---

## TD-16: Decoding thresholds tuned on GuitarSet

**Concept.** The model outputs, for every 12 ms, how likely each pitch is sounding and starting.
*Decoding* turns that into notes with thresholds (how strong a start must be, how strong a held
note must stay, how short a note may be). *Tuning* searches for the thresholds that score best on
recordings with known answers. To avoid fooling ourselves, the search uses one set of clips (the
*tuning set*) and the result is judged on different clips (the *held-out test set*).

**What we did.** `tests/tuning/tune_decoding.py` searched ~800 combinations on 24 GuitarSet
excerpts (cached, not committed) and judged the winner on the 6 committed test clips: note F1
0.761 -> 0.818, wrong notes 27 % -> 19.5 %, found notes 81 % -> 84 %.

A first winner used *fixed* thresholds. On a real phone recording it deleted 61 % of the notes,
because that recording's activations were weaker (99th percentile 0.62 vs 0.69-0.81 on GuitarSet).
So activations are now scaled to a reference level per recording before decoding (`level_gain`),
making thresholds relative. That scored best on GuitarSet too, and on the phone recording removed
7 % of notes, mostly extra notes stacked on real ones.

**Pros**: measurable, repeatable (`make` the tuning set, run the script), and it improves every
bar at once instead of patching symptoms.

**Cons**
- 24 tuning clips from one dataset (6 players, one guitar setup). Other guitars, rooms and
  phones may want different values; level normalization covers loudness, not tone.
- Piano still uses Basic Pitch's defaults: there is no commercially usable real piano set yet.
- Tab string accuracy moved from 0.38 to 0.35 (a different set of notes is now found and scored).

**Tried and rejected (Step A5, 2026-10-09): chord-guided strum completion.** Adding chord tones
of the recognized chord (TD-26) where Basic Pitch's activations show them at a strum, but too
weakly to decode, raised recall on comp clips by up to 0.10 but cost more precision: F1 fell
everywhere when the tone only had to be present (ringing notes from the previous strum count),
and when it had to rise at the strum, the best setting gained 0.005 on the tuning clips and lost
0.08 on the held-out Guitar-TECHS chords. Where Basic Pitch misses a strummed note there is
little evidence of it left to recover; a better note model is the fix (TD-11).

**Revisit when** user recordings with corrections exist (Phase 4): they are the right tuning set.

---

## TD-17: Local dev token issuer instead of a real auth provider

**Concept.** The API trusts *JWTs* (signed JSON tokens saying who the user is) issued by a
managed provider; it never sees passwords. In production the provider (Clerk, ADR-0008) signs
tokens with a private RSA key and publishes the public half as a *JWKS*; the API checks the
signature against it (RS256). Locally, `make token USER=alice` signs tokens with a shared
throwaway secret (HS256) and the API is configured with the same secret (`JWT_DEV_SECRET`).

**Pros**
- No provider account, network access or sign-up flow needed to work on or test the backend.
- The checks after the signature (issuer, expiry, audience, subject rules) are the same code in
  both modes, and the RS256/JWKS path has its own unit tests with a generated key.
- Each mode accepts only its own algorithm and exactly one mode can be configured, so an HS256
  token is rejected by a production API.

**Cons**
- The production key path (JWKS fetch, caching, key rotation) isn't exercised end to end until a
  real provider is wired up.
- Anyone with the dev secret can mint tokens for any user. Fine locally; a deployment that set
  `JWT_DEV_SECRET` by mistake would have no real auth.

**Revisit when** the first deployment: add a startup check that refuses `JWT_DEV_SECRET` outside
local environments. (Phase 3 wired up Clerk: `make api CLERK_ISSUER=...` runs the JWKS path
against a real provider, which answers the first con.)

---

## TD-18: Simple quotas and rate limits

**Concept.** A *quota* caps how much a user may use per period (here: jobs per calendar month);
a *rate limit* caps how fast they may make requests (here: new jobs per minute). Both are
counters in Redis, so every API instance sees the same numbers (`services/api/src/api/limits.py`).

**Pros**
- Two Redis commands per check; no tables, no background jobs.
- Counters expire on their own, and the month is the calendar month in UTC, which is easy to
  explain to users.

**Cons**
- One tier only: `FREE_JOBS_PER_MONTH` for everyone. Paid plans (more jobs, longer clips,
  `Priority.HIGH`) need a plan stored per user.
- A job counts when it is submitted, even if the pipeline then fails on it (for example, the
  normalize stage finds it's longer than 5 minutes). Refunding those is left out.
- The rate limit is a fixed window, so a burst at a minute boundary can reach twice the limit.
- Redis is the only record of usage. If its data is lost, this month's counts reset to zero.
  Postgres has the jobs, so they could be rebuilt from it.

**Revisit when** billing arrives (Phase 5, RevenueCat): store the plan on the user, refund quota
for jobs that fail for our reasons, and keep usage in Postgres if it has to be auditable.

---

## TD-19: Dedup cache per user, reused after normalize

**Concept.** A *dedup cache* recognises work already done and reuses its result. The key is a
hash of the normalized audio samples, the pipeline version and the job's options, so a re-encoded
copy of a recording still matches, while a model upgrade or a different capo doesn't
(`services/worker/src/worker/dedup.py`). When `normalize` finishes, the worker looks the key up;
on a hit it copies the earlier job's files inside object storage and marks the later stages
`cached`.

**Pros**
- A repeat upload costs one decode instead of a full transcription, and finishes in seconds.
- The copy happens inside the bucket (S3 CopyObject); no audio passes through the worker.
- If the earlier job's files are gone (deleted, or removed by a lifecycle rule), the worker just
  runs the stages, so the cache can never fail a job.

**Cons**
- **Per user only.** The key includes the user ID, because CLAUDE.md requires every query to be
  scoped by user and every object to live under its owner's prefix. Two users uploading the same
  file both pay for a full run. Sharing across users would be a deliberate exception to tenant
  isolation, and it would let a user infer someone else uploaded the same audio (from how fast
  the job finishes).
- Normalize always runs first, since the key needs the decoded audio; hashing the raw upload
  would skip it but would miss re-encoded copies.
- Each hit stores a second copy of the result files rather than pointing at the first job's.
  Pointing would save storage but tie one job's files to another job's lifetime.

**Revisit when** storage costs grow, or metrics show many identical uploads across users.

---

## TD-20: Observability: Prometheus metrics and a minimal trace

**Concept.** *Logs* say what happened, *traces* show one request's path through the services
with timings, and *metrics* are numbers over time for dashboards, alerts and autoscaling. Every
log line is JSON with `job_id`, `stage`, `attempt`, `trace_id` and `span_id`. A job is one
OpenTelemetry trace: the API's submit request, then one span per stage, passed along in the
queue message. Metrics are Prometheus counters, histograms and gauges: queue depth (API
`/metrics`), stage durations and outcomes (worker, port 9100) and API latency.

**Pros**
- Prometheus is pull-based and needs nothing else running: point a Prometheus at the
  endpoints. Traces go to any OTLP collector only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- The pipeline's own logs get the job's fields without depending on any of this (context
  variables are read by the log formatter).
- Queue depth is read from Redis at scrape time, so it is right on every instance.

**Cons**
- Two systems: OpenTelemetry for traces, `prometheus_client` for metrics. OpenTelemetry metrics
  would unify them but need a collector even for the MVP.
- Spans cover requests and stages only. Postgres, Redis and S3 calls aren't traced yet (their
  instrumentation packages would add that).
- The API serves `/metrics` on its public port. It holds no user data, but the ingress must not
  route it (or it moves to a separate port).
- Logs go to stderr; shipping and keeping them (Loki, CloudWatch) is the deployment's job.
- No GPU utilisation metric: MVP workers are CPU-only. GPU workers should run NVIDIA's DCGM
  exporter next to them.
- Every API instance reports the same queue depth, so dashboards must use `max`, not `sum`.

**Revisit when** the first production deploy (dashboards, alerts, ingress rules) and when GPU
workers arrive (DCGM, queue-depth autoscaling with KEDA).

## TD-21: App API types generated from a committed OpenAPI copy

**Concept.** The app's request and response types are generated from the API's OpenAPI schema,
not written by hand. `make api-types` writes the schema to `apps/mobile/src/api/openapi.json`
(committed) and `openapi-typescript` turns it into `schema.d.ts`; `openapi-fetch` checks every
call's path, parameters and body against those types. An API test fails when the committed
schema is stale, and `make mobile-check` fails when `schema.d.ts` doesn't match it.

**Pros**
- An API change that breaks the app breaks the build, not a user's phone.
- The app needs no running API or Python to build: CI's mobile job reads the committed copy.
- `openapi-fetch` is a few kB; its one dependency holds only types.

**Cons**
- One more step after API changes (`make api-types`), and generated files in review diffs.
- `openapi-typescript` 7 declares a peer of TypeScript 5 while the app is on TypeScript 6
  (Expo SDK 57). An npm `overrides` entry gives it our TypeScript; generation works, but the
  combination isn't one its authors test.
- Types aren't runtime checks: a deployed API that drifts from the schema (an older server)
  isn't caught until a field is missing.

**Revisit when** openapi-typescript supports TypeScript 6 (drop the override), or when old app
versions in the wild need a versioned API (generate per API version).

## TD-22: Clerk's native sign-in screen

**Concept.** Sign-in and sign-up are Clerk's prebuilt native screen (`AuthView` from
`@clerk/expo/native`, built on Clerk's iOS and Android SDKs) rather than screens we build. It
covers email + password with email verification, password reset, Google, and Apple on iOS, as
switched on in the Clerk dashboard. The session lives in the Keychain / Keystore
(`expo-secure-store`), and the API client sends Clerk's short-lived session token on every call.

**Pros**
- Little code: no forms, verification-code screens, reset flows or error states of our own.
- Native Google and Apple sign-in (system sheets, no browser), and new Clerk features (passkeys,
  MFA) arrive with SDK updates.
- Clerk maintains the security-sensitive parts.

**Cons**
- **Minimum iOS 17**, set by Clerk's config plugin (Expo SDK 57 otherwise allows older).
- **No Expo Go.** The app needs a development build (`make mobile-ios`, `make mobile-android`),
  which needs Xcode and Android Studio. Push notifications need one anyway.
- **Look is limited** to Clerk's dashboard branding and the plugin's `theme` colours.
- **Sign in with Apple is off** (`appleSignIn: false` in `app.json`) until there's a paid Apple
  Developer account: the entitlement can't be signed without one. Don't enable Apple in the Clerk
  dashboard until then; the button would appear and fail. App Store guideline 4.8 requires it
  before an iOS release that offers Google.
- Locally the API accepts either dev tokens or Clerk tokens, not both (`CLERK_ISSUER`, TD-17), so
  `make e2e` and the app can't share one running API.
- **First-time Google sign-up fails on Android phones with no Google account.** Clerk then
  falls back to Google in a browser, and its Android SDK (1.1.11) returns from the browser
  without turning the sign-in into a sign-up: no user is created and the screen starts over.
  With a Google account on the phone (nearly every Android phone) the native picker is used and
  sign-up works (tested 2026-10-08). Report to Clerk; retest when `@clerk/expo` updates its SDK.
- Ties the app's sign-in screen to Clerk. The API side stays provider-neutral (plain JWKS).

**Revisit when** the Apple Developer account exists (set `appleSignIn` to true, register the iOS
app in Clerk, enable Apple), or when design needs more than Clerk's theming (build our own screens
on `useSignIn`/`useSignUp`; the API doesn't change).

## TD-23: Local Android builds: JDK 17 and a slow React Native repository

**Concept.** `make mobile-android` compiles the development build on this Mac with Gradle. React
Native 0.86 supports JDK 17; Android Studio ships JDK 25, whose native-access warnings make the
Android Gradle plugin fail CMake steps (`react-native-worklets`). The Makefile picks JDK 17 with
`/usr/libexec/java_home -v 17` (Temurin 17 in `~/Library/Java/JavaVirtualMachines`). React
Native's own Maven repository (`repo.reactnative.dev`, which Maven Central redirects to) was very
slow from our network (about 58 KB/s, with resets) for its 279 MB and 112 MB debug libraries;
Gradle can't resume downloads, so they were fetched once with `curl -C -` and served through a
one-off `--init-script`. They're in Gradle's cache now.

**Pros**
- No cloud build service or account; a rebuild takes minutes once the cache is warm, and
  JavaScript changes reach the phone in seconds through Metro without rebuilding.

**Cons**
- Each developer machine needs Android Studio, JDK 17 and ~15 GB of SDK, NDK and caches.
- A fresh cache on a slow network repeats the download problem.

**Revisit when** builds move to EAS Build or CI (Phase 5), or React Native supports newer JDKs.

## TD-24: Score viewer: alphaTab in a WebView from local files

**Concept.** alphaTab (MPL-2.0) is a web library, so the app runs it in a WebView. Its script,
music font (Bravura, SIL OFL) and soundfont (Sonivox, Apache-2.0) ship inside the app (about
2.8 MB, copied from the npm package on install by `scripts/viewer-assets.js`) and are laid out in
the cache on first use, so the page loads them by relative `file://` URLs. The app downloads the
score's MusicXML (presigned GET) and hands it to the page; playback controls live in the page
because audio may only start from a tap inside it.

**Pros**
- The same renderer and exporters as the preview page (`make view`) and, later, the editor.
- Works offline; nothing loads from a CDN, so no third-party request sees what users open.

**Cons**
- The WebView may read local files (`allowFileAccessFromFileURLs`,
  `allowUniversalAccessFromFileURLs`). It only ever loads our own page, but those flags must
  never be combined with remote content.
- Workers and AudioWorklets can't load from `file://`, so rendering runs on the page's main
  thread and audio uses the older ScriptProcessor path: long scores render more slowly.
- PDF export prints the off-screen, black-on-white rendering of the score as HTML. alphaTab
  positions each system absolutely, so the printer splits pages at fixed heights: a system can
  be cut across a page break in longer scores. Proper engraving-quality PDFs would come from a
  layout that knows page sizes (alphaTab's print layout, or MuseScore server-side).

**Revisit when** long scores feel slow (serve the page from a local HTTP origin so workers run),
or Phase 4's editor needs tighter app/page integration.

## TD-25: Push notifications through Expo's push service

**Concept.** Phones receive notifications from Apple (APNs) and Google (FCM). Expo's push
service sits in front of both: the app gets one *Expo push token* per install, registers it with
our API (`PUT /me/push-tokens`), and the worker sends "your score is ready" to Expo, which
forwards it (`WORKER_NOTIFIER=expo`). The app asks for permission the first time the user sends
a transcription; Account has an on/off switch; sign-out removes the device's token.

**Pros**
- One HTTP call for iOS and Android; no APNs or FCM code on our side, and no new Python
  dependency (standard-library HTTP).
- Notification failures are logged and never affect the job. Devices Expo reports as gone are
  forgotten.

**Cons**
- A third party sees notification text (the take's name). Expo's service is free; it is one
  more service to depend on.
- Needs setup outside the repo: an Expo project (`npx eas-cli@latest init` writes its ID to `app.json`), and
  for Android a Firebase project with its FCM key uploaded to Expo. Until then the app hides
  the option (push "unavailable").
- Only Expo's *tickets* are checked. Some failures (e.g. an uninstalled app) arrive later as
  *receipts*, which we don't fetch yet, so dead tokens can linger until a later send fails.
- Sent from the worker, inline, after the job is acknowledged: a slow Expo call delays that
  worker's next stage by up to its 10 s timeout.

**Revisit when** users have many devices or notifications fail silently (fetch receipts in a
small periodic task, send from a queue), or if we move off Expo (APNs/FCM directly).

## TD-26: Chord names by template matching

**Concept.** Chord names (shown above the staff) come from the note model's frame activations,
not from a dedicated chord model. Per half beat, the activations are folded onto the 12 pitch
classes; each of 60 chords (12 roots x major, minor, 7, maj7, m7) is scored by how well its
notes match, plus a bonus when its root is in the bass, and a Viterbi pass picks the sequence
with a penalty for changing chord (`pipeline/chords.py`). It runs in the quantize stage, which
already has the beats. Settings were grid-searched on 24 GuitarSet comp excerpts that are not
test clips (`tests/tuning/tune_chords.py`).

**Pros**
- No new model, dependency or licence; a few milliseconds per song, on CPU.
- Works from what Basic Pitch hears even when it drops notes from a strum (a weak note still
  adds to the chroma), which is where note-level transcription fails on strummed chords.
- Measured: major/minor accuracy 0.76 on the tuning clips and 0.89 on the held-out test clips
  (`chord_majmin` in `make test-accuracy`).

**Cons**
- Small vocabulary: no sus, dim, aug, 6, 9 or slash chords; a sus2 is named as its nearest
  triad or seventh. No inversions (the bass only helps pick the root).
- Chord changes only on half beats, so it depends on the beat tracker (TD-12).
- Tuned on GuitarSet's clean mic recordings of six players; phone recordings and other styles
  may score lower. Piano uses the same settings untuned.

**Revisit when** chord accuracy plateaus or users ask for richer chords: try a learned chord
model (licence-checked, CPU cost measured) or a bigger vocabulary with inversions, scored by
the same metric.

## TD-27: Synced playback from the phone's own copy of the take

**Concept.** The score can play the user's own recording instead of the synthesized guitar,
with the cursor following the real timing. The pipeline writes `sync.json` (when each bar
starts in the uploaded audio); the app keeps its own copy of every take it sends
(`src/audio/takes.ts`, in the app's documents, deleted with the job) and hands both to
alphaTab as a *backing track* with one *sync point* per bar. The server keeps no audio for
this, in line with ADR-0009 (uploaded audio is deleted after processing).

**Pros**
- No new storage, bandwidth or retention questions on the server; nothing changes legally.
- Real sound with no new model or soundfont; the cursor stays on the bar being played even
  when the player speeds up or slows down (checked in Chrome: seeking to 5 points of a GuitarSet
  take lands the cursor in the bar sync.json predicts, 5 of 5).

**Cons**
- Only on the phone that sent the take. Another phone, a reinstall, or takes sent before
  this change play the synthesized sound.
- The takes use space on the phone (about 1 MB per minute) until the job is deleted.
- One sync point per bar: within a bar, timing is interpolated linearly.
- A bar that starts before the recording does (a pickup extrapolated before the first beat)
  is clamped to 0 ms, so that bar is slightly squeezed.
- Speed changes and the metronome are reset when switching between recording and synth (the
  page starts a fresh player).

**Revisit when** users want playback on other devices (then keep a compressed playback copy
on the server for the transcription's lifetime, which needs an ADR-0009 amendment), or when
per-beat sync is needed for tight passages.

## TD-28: Guitar sound from a trimmed MuseScore_General font

**Concept.** Synthesized playback draws instruments from a *soundfont*: recorded samples
plus how to play them. alphaTab ships Sonivox (1.3 MB, General MIDI); its guitar sounded
thin. The owner compared renders of our transcriptions and preferred **MuseScore_General**
(MIT; FluidR3 by Frank Wen and others). The full font is 40 MB, 15 MB of it piano, so
`tools/soundfont/trim_sf3.py` keeps only its guitars (GM 24-30) and the metronome click: 2.1 MB
(`apps/mobile/assets/soundfont/`, with its licence and attribution). The viewer loads Sonivox
first and MuseScore's guitars on top; alphaTab uses the last font that has a preset.

**Pros**
- Better guitar sound for 2.1 MB more in the app, and no new code dependency. Samples are copied
  as they are (Ogg Vorbis inside SF3), so the trim loses no quality and can be re-run.
- MuseScore's guitar plays at about a quarter of Sonivox's level (peak 0.41 vs 1.6 on a strummed
  excerpt), so guitar playback no longer clips.

**Cons**
- Piano and everything else stay on Sonivox, which can still clip on dense chords.
- ~~The app has no third-party notices screen yet.~~ Done: Account > Acknowledgements lists this
  font, Bravura, Sonivox, Basic Pitch and every npm package the app ships, with their licence
  texts (`scripts/licenses.js` generates them; `make mobile-check` fails when they're stale).
- alphaTab only plays mono samples from a font; this one is mono, a stereo font would play
  silence.

**Revisit when** piano users ask for a better piano (MuseScore's is 15 MB: offer it as a
download rather than bundle it).

## TD-29: Staging is one VM with logs only

**Concept.** *High availability* means a service survives the loss of a machine; it needs at
least two of everything plus a load balancer. *Observability* is being able to see what the
system does: metrics, dashboards, alerts.

**What we did (ADR-0010).** Staging runs every service on one VM in the owner's home-lab
OpenStack, with docker compose, reachable from the internet only through a Cloudflare Tunnel.
The lab has no block storage, so Postgres lives on the VM's disk and is dumped to R2 nightly.
The API (`/metrics`) and
worker (`:9100`) still expose Prometheus metrics, but only inside the VM; nothing collects them.
Logs are JSON in `docker compose logs`.

**Pros**
- Cheap, quick to set up and easy to understand; the same images and settings as production.
- Audio and scores live in R2, so a lost VM loses no files.

**Cons**
- Any VM problem takes staging down until it is fixed or replaced.
- Losing the VM's disk loses database changes since the last nightly backup (up to a day):
  jobs, score versions and push tokens made since then.
- It depends on the home lab's power and internet connection, and on Cloudflare's tunnel.
- Nobody is alerted when something breaks; queue depth and failure rate are only visible by
  asking the VM.
- One worker: two long transcriptions queue behind each other.

**Revisit when** real users depend on it (Phase 5: Prometheus + Grafana or a hosted service,
alerts on failure rate and queue depth, two VMs or managed hosting), or when staging downtime
starts blocking work.

## TD-30: Terraform state in a local file

**Concept.** Terraform remembers what it created in a *state* file and compares it with the code
on every run. Teams keep it in a shared *remote backend* (an S3 bucket, Terraform Cloud) with
locking, so two people can't change the same infrastructure at once.

**What we did.** `infra/terraform/staging` keeps its state in a local, git-ignored
`terraform.tfstate` on the owner's machine.

**Pros**
- Nothing to set up first; fine for one person and one environment.

**Cons**
- The state exists on one laptop: lose it and Terraform no longer knows the VM, volume and IP it
  made (they keep running, but have to be imported or deleted by hand).
- No locking; two runs at once can corrupt it.
- The state file holds resource details (IPs, IDs), so it must never be committed.

**Revisit when** a second person runs Terraform, or before production: move it to an S3 backend
on R2 (`backend "s3"` with R2's endpoint) with a lock.

## TD-31: The editor shows changes after saving

**Concept.** An editor can show a change *optimistically* (redraw at once, assuming the server
will agree) or *after the server confirms it*. Optimistic feels instant but needs the client
to apply every operation exactly like the server, or the two drift apart.

**What we did (ADR-0011).** Edit mode collects pending changes (a count, undo, cancel) and
keeps the score on screen as it was; Save sends them, the worker renders the new version in
a second or two, and the app then shows it. Each note has at most one pending change, so every
operation refers to the note as it appears on screen.

**Pros**
- One implementation of each operation (`pipeline/edits.py`), with the server's checks
  (impossible frets, collisions) applied before anything is shown.
- Simple, robust app code; what you see is always a real, saved version.

**Cons**
- You don't see a change until you save: fixing ten notes means remembering what you changed
  (the bar shows how many).
- Two changes to one note collapse into the last (e.g. a pitch change then a string change
  needs the string chosen with the pitch).
- Each save is a round trip through the queue.

**Revisit when** users edit a lot at once: apply simple operations (string/fret, delete) to
alphaTab's model locally and redraw, keeping the server as the judge on save.

## TD-32: Production in the home lab

**Concept.** Where real users' requests and data live. A rented server or cloud has redundant
power and networking and someone on call; a home lab has neither, but costs nothing extra.

**What we did (ADR-0012).** Production runs like staging, on its own small VM (2 vCPU / 3 GB)
in the home lab behind a Cloudflare Tunnel, with nightly database backups to R2 and an
external uptime check that emails the owner.

**Pros**
- No hosting bill before there is revenue; the same, already-tested setup as staging.
- The tunnel keeps the home's address private and needs no open ports.

**Cons**
- A power cut, an internet outage or a lab reboot takes production down; nothing fails over.
- Users' data (accounts, scores) is stored in the owner's home; backups are nightly, so a lost
  VM can lose up to a day of changes.
- One worker on 2 vCPUs: transcriptions queue behind each other and take about twice as long
  as on staging.
- The lab is nearly full; growing production means shrinking staging or other VMs.

**Revisit when** there are paying customers (move production to a rented VM or the AWS path in
CLAUDE.md, with managed Postgres and point-in-time recovery), or as soon as an outage costs
users something.
