# Performance notes

A running log of what I measured, what I found and what I changed, newest first. Each entry
keeps the raw numbers so later changes can be compared against them.

## How to measure

The worker logs one line per stage (`"stage succeeded"`, with `duration_s` for the whole
message) and the pipeline logs one line per stage it runs or finds cached (`"stage done"`,
with `duration_s` for the compute alone). From those two:

- compute = the pipeline's `duration_s` for the stage that `ran`
- overhead = the worker's `duration_s` minus compute (storage transfers, database writes,
  queueing the next stage)
- gap = the time between one stage's "stage succeeded" and the next one's start (its
  timestamp minus its `duration_s`): time the job spent waiting in a queue

```sh
ssh ubuntu@<vm> 'cd /srv/riffscribe/stack && sudo docker compose logs worker --since 15m --no-color \
  | grep -E "\"stage |job succeeded"'
```

Staging has a faster CPU than production, so compare compute only on the same machine.
Overhead and gaps don't depend on the CPU: both VMs reach R2 over the same home-lab
connection.

## 2026-11: the wait before Play on the phone

After a transcription finished, the Play button seemed to take about 5 s to become available
on the phone, with a spinner on it the whole time.

### How I measured it

The app logs one `score load timings` line each time a score opens (`src/score/loadTimer.ts`,
PR #58). All times are milliseconds since the score screen opened. The app's own steps
(score and sync data fetched, viewer mounted, viewer files ready, recording copied, page
ready, player ready) come from React Native. The viewer page's steps (alphaTab loaded,
soundfonts read, score parsed, player ready) come from the WebView, on the page's own clock.
I read it over USB:

```sh
adb logcat -v time ReactNativeJS:V '*:S' | grep 'score load timings'
```

Before the phone run, I loaded the viewer page in desktop Chrome at 6x CPU throttle. It was
ready in 0.3 s playing back the recording and 1.4 s with the synth sound, so I suspected the
phone itself (WebView start-up, parsing the 1.1 MB alphaTab script, Android audio).

### What I saw

Production app (Play Store build 1.0.0 (7) with update `847f0c9f`), on a Redmi 10 Prime
(Xiaomi 21061119BI), recording playback:

| Step | Reopened from the Library | Just after the job finished |
|---|---|---|
| Score data fetched | 0.35 s | 0.30 s |
| Viewer mounted | 0.40 s | 0.39 s |
| Recording copied for the viewer | 0.56 s | 0.43 s |
| Viewer page ready | 1.28 s | 0.74 s |
| Play available | 1.65 s | 1.14 s |

Inside the viewer page, the soundfonts take about 15 ms and parsing the score about 80 ms.
Most of the page's time is the WebView starting and loading alphaTab (0.2-0.4 s before the
page's script runs at all).

### What it means

On this phone, the spinner on the Play button lasts 1.1-1.7 s, not 5 s. The measured steps
don't account for the rest. What they don't cover is the time between the worker finishing
and the score appearing: the app checks the job every 2 s (up to 2 s, about 1 s on average),
plus the last pipeline stages.

### Still open

- Measure the iPhone (Console.app; store builds may not log `console.info`).
- Measure the synth sound on the phone; in Chrome it was the slower of the two.
- If the wait before the score appears matters, check the job more often near the end, or
  use the completion push notification to refresh it.

## 2026-11: transcription took 35-40 s for a 20-second clip

### What I saw

Locally, `python -m pipeline transcribe` on a 20-second guitar clip took about 3 s. On
production the same kind of clip took 35-40 s from queued to finished. So the models weren't
the problem: almost all the time was spent outside them.

Production, v1.0.8, one 20-second job (normalize not captured):

| Stage | Whole message | Compute | Overhead | Gap before |
|---|---|---|---|---|
| separate | 2.5 s | 0.0 s | 2.5 s | |
| transcribe | 6.9 s | 1.8 s | 5.0 s | 2.1 s |
| quantize | 4.9 s | 0.02 s | 4.8 s | 0 s |
| notation | 8.4 s | 0.00 s | 8.4 s | 2.1 s |
| tab | 7.7 s | 0.01 s | 7.7 s | 2.1 s |

About 2 s of compute, about 28 s of overhead and about 6 s of gaps.

### Cause 1: storage transfers one at a time

Each stage is one queue message, and any worker can take any message, so the job's
object-storage prefix is its shared work directory (ADR-0001). Before running a stage the
worker downloads every file the job has so far, and afterwards it uploads what the stage
wrote. It did both one file at a time. From the home lab every request to R2 is a round trip
of about 0.4 s, and by the last stage a job has around a dozen files, so the overhead grew
with every stage: 2.5 s for the second stage, 7-8 s for the last ones.

Fix (#54): the transfers run in parallel on 8 threads (botocore keeps 10 connections per
client). Manifests are still uploaded after the other files of their stage, because a
manifest in storage is what says the stage is complete.

### Cause 2: the worker waited on the wrong queue

CPU and ML stages go to separate queues, so GPU workers can take over the ML queue later.
The one worker serves both, and it waited on them in turn: up to 2 s on the CPU queue, then
up to 2 s on the ML queue. When a job moved from an ML stage to a CPU stage, or the other
way round, the next message was often sitting on the queue the worker wasn't waiting on.
That cost about 2 s at three points of every job.

Fix (#54): one blocking `XREADGROUP` over every stream of every queue the worker serves.
High priority still comes first across the queues, and the queues stay separate.

### After

Staging, a test job submitted straight to the queue (20-second clip, new code): 10.7 s from
queued to finished, about 3 s of it compute, 0.9-1.6 s of overhead per stage, no gaps.

Production, v1.0.9, a 20-second job from the Play Store app:

| Stage | Whole message | Compute | Overhead | Gap before |
|---|---|---|---|---|
| normalize | 2.7 s | 0.11 s | 2.6 s | |
| separate | 1.3 s | 0.00 s | 1.3 s | 0 s |
| transcribe | 5.7 s | 4.0 s | 1.8 s | 0 s |
| quantize | 1.9 s | 0.05 s | 1.9 s | 0 s |
| notation | 1.8 s | 0.01 s | 1.8 s | 0 s |
| tab | 2.3 s | 0.02 s | 2.2 s | 0 s |

15.6 s in the worker, down from about 40 s. On the phone it felt right.

### What I took away

- Measure the whole path before touching the models. The models were 5-10% of the time.
- A design that is right for scale (any worker can take any stage, storage is the shared
  state) has a cost per stage that is invisible on a laptop with local storage and obvious
  on a home lab talking to a cloud bucket. Round trips, not bandwidth, were the cost.
- Polling several queues in turn adds the poll interval at every hop between queues. Wait
  on all of them at once.

### Still open

- **Overhead is still 1.3-2.6 s per stage on production** (4-5 round trips in a row: list,
  download, upload, upload manifests, database). Options, biggest first: run consecutive
  stages of one queue as one message (normalize + separate; quantize + notation + tab),
  about 5-6 s; keep the job's files on the worker between stages and skip the download when
  it already has them, about 1 s per stage; check where the R2 bucket is, since 0.4 s per
  request is slow for a bucket in the same region.
- **On the phone, the Play button takes about 5 s to become available** after the score
  appears. Measured since: 1.1-1.7 s on a mid-range Android phone (the section above).
