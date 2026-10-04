# ADR-0005: Our own beat tracker instead of librosa

- Status: accepted
- Date: 2026-10-04
- Amends: "librosa for beat and tempo" in CLAUDE.md

## Context

The quantize stage needs a tempo and beat times. CLAUDE.md named librosa. Measured on a
5-minute clip on the MVP's CPU-only setup (ADR-0004):

| librosa 1.0.0 `beat.beat_track` | Result |
|---|---|
| Install size | 281 MB (numba, llvmlite, scikit-learn, joblib, pooch, ...) |
| First run in a fresh container | 30 s (numba compiles its kernels) |
| Later runs | 1.6 s |
| Peak memory | 560-670 MB (the whole pipeline before this: 326 MB) |

Most of the memory is the tempogram: librosa builds a `win_length x n_frames` float64 matrix
(about 140 MB) and autocorrelates all of it, then only uses its mean.

Basic Pitch already produces an onset activation per pitch at ~86 frames/s, so a second pass
over the audio to find onsets is unnecessary.

## Decision

- `transcribe` saves an onset envelope: per-pitch rises in Basic Pitch onset activation
  (positive flux), summed over the instrument's range and resampled to an even 22050/256
  frames/s grid. Summing raw activations failed on every test tempo (it came out ~120 bpm),
  while positive flux found all of them.
- `pipeline/beats.py` ports librosa's tempo estimation and Ellis (2007) dynamic-programming beat
  tracker (ISC licence, attribution in the module). It averages the tempogram chunk by chunk
  instead of materialising it. No numba.
- librosa is not a dependency. Its outputs on committed envelopes are recorded once, in a
  throwaway environment (`tests/fixtures/rhythm/make_reference.py`); tests require identical
  tempo and beat frames. A separate test checks that synthesized clips at known tempos come out
  right, since parity says nothing about whether the envelope itself is good.
- Per ADR-0003, the dynamic program stays in numpy: 85 ms for 5 minutes. Tempo estimation is
  463 ms of FFTs (native code).

## Consequences

- Quantize on 5 minutes: 0.6 s, no warm-up, no extra install weight, no memory spike.
- We maintain ~150 lines of ported code; the recorded references make upgrades checkable.
- Same algorithm, same known limits as librosa: one global tempo, octave errors for fast music
  (a 175 bpm pulse is reported as 87.6), see `docs/tech-debt/README.md` TD-12 and TD-13.
