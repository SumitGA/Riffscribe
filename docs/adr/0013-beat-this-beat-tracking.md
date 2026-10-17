# ADR-0013: Beats from the Beat This! model

- Status: accepted
- Date: 2026-10-17
- Amends: ADR-0005 (our tracker now runs over the model's beat probabilities, not the onset
  envelope)

## Context

Notes are written relative to the beat, so a wrong beat puts right notes in the wrong place:
a note on beat 1 written an eighth late, simple strums turned into syncopations. ADR-0005's
tracker (Ellis dynamic programming over Basic Pitch onsets) got the tempo right on 29 of 54
GuitarSet clips, and on half of those its beats fell between the real ones: beat F 0.25 on the
accuracy suite. Hand rules on top made it worse. Users heard it as notes that "don't land
correctly".

[Beat This!](https://github.com/CPJKU/beat_this) (Foscarin, Schlüter, Widmer, ISMIR 2024) is a
transformer trained on 16 beat-annotated datasets. Code and weights are MIT. Measured on the 54
clips with its own post-processing: beat F 0.75 (`small0`, 8.1 MB) or 0.80 (`final0`, 78 MB).

## Decision

- **`small0`, converted to ONNX and vendored** (`pipeline/models/beat_this/`, 3.0 MB): exported
  with ONNX Runtime's fused attention kernel, int8 matrix weights and short tensor names
  (`tests/fixtures/beat_this/make_reference.py`). The float export matches PyTorch to 6e-5; int8
  leaves beat F unchanged. No new runtime dependency: ONNX Runtime and numpy were already
  there, and torch stays out of the images. `final0` would add ~0.05 beat F for 26x the file.
- **`pipeline/beat_this.py`** ports the log-mel spectrogram (numpy, matches torchaudio to 1e-4)
  and upstream's 30 s chunking. The transcribe stage saves the model's beat and downbeat
  probabilities (`beat_activation.npy`, 50 frames/s).
- **The quantize stage runs our Ellis tracker over the beat probabilities** instead of
  upstream's peak picking. Peak picking jumped between half and double speed and added beats
  0.1 s apart on unaccompanied solos; the tracker keeps beats evenly spaced: beat F 0.748 ->
  0.768, tempo right 34 -> 36 of 54, solos 0.58 -> 0.61. Bars start on the beat (mod 4) with the
  most downbeat probability (downbeat F 0.565 for a vote over picked downbeats, 0.596 this way).
- **Fallback:** when no frame reaches probability 0.5 (no beat heard, e.g. single chords with
  pauses), the onset-envelope tracker of ADR-0005 is used, as before.

## Consequences

- Accuracy suite, GuitarSet: beat F 0.25 -> 0.80, tempo right 4 -> 6 of 6, bar lines (downbeat
  F) 0.08 -> 0.55, notes written at the right place in the beat 20 % -> 68 % and in the bar 6 % ->
  49 % (two new metrics). Piano clips: notes in the right place in the bar 56 % -> 100 %.
  Playback (the app viewer's MIDI against the played notes): within 100 ms 58 % -> 64 %.
- GuitarSet is in Beat This!'s training data, so those numbers flatter it; Guitar-TECHS (held
  out) has no beat annotations. There the grid-dependent metrics moved a little: notes kept
  apart 0.96 -> 0.975, chords kept whole 0.74 -> 0.79, tab strings 0.600 -> 0.595.
- Cost per job: ~0.35 s of CPU per 30 s of audio (Apple M-series; 4.2 s for 5 minutes), ~200 MB
  extra while it runs, returned afterwards (no memory arena). See TD-35.
- Unaccompanied solos remain the weak spot: without the band, the pulse is often ambiguous.
