"""Pure-Python port of upstream Basic Pitch note decoding, kept as a test oracle.

Production decoding is Rust (`rust/notes.rs`). This follows upstream
`output_to_notes_polyphonic` line by line (including float64 inferred onsets) so randomized
tests can check that the Rust version gives the same notes.
"""

from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.signal import argrelmax

from pipeline.basic_pitch import (
    MIDI_OFFSET,
    UPSTREAM_DEFAULTS,
    Activations,
    DecodeParams,
    RawNote,
    frame_times,
)


def decode_notes(
    frames: Activations, onsets: Activations, params: DecodeParams = UPSTREAM_DEFAULTS
) -> list[RawNote]:
    """Turn activations into notes, sorted by start time then pitch (upstream algorithm)."""
    frames = frames.copy()
    predicted = onsets.copy()
    n_frames = frames.shape[0]
    tol, thresh = params.energy_tolerance, params.frame_threshold
    if params.max_pitch is not None:
        frames[:, params.max_pitch - MIDI_OFFSET + 1 :] = 0
        predicted[:, params.max_pitch - MIDI_OFFSET + 1 :] = 0
    if params.min_pitch is not None:
        frames[:, : max(0, params.min_pitch - MIDI_OFFSET)] = 0
        predicted[:, : max(0, params.min_pitch - MIDI_OFFSET)] = 0
    strength: npt.NDArray[np.floating[Any]] = (
        _inferred_onsets(predicted, frames) if params.infer_onsets else predicted
    )

    peaks = np.zeros(strength.shape)
    peak_idx = argrelmax(strength, axis=0)
    peaks[peak_idx] = strength[peak_idx]
    onset_t, onset_f = np.where(peaks >= params.onset_threshold)

    remaining = frames.astype(np.float64)
    events: list[tuple[int, int, int, float]] = []
    # Walk onsets backwards in time, as upstream does; the order decides which overlaps win.
    for start, f in zip(onset_t[::-1].tolist(), onset_f[::-1].tolist(), strict=True):
        if start >= n_frames - 1:
            continue
        i, k = start + 1, 0
        while i < n_frames - 1 and k < tol:
            k = k + 1 if remaining[i, f] < thresh else 0
            i += 1
        i -= k
        if i - start <= params.min_note_frames:
            continue
        _clear(remaining, start, i, f)
        events.append((start, i, f, float(np.mean(frames[start:i, f]))))

    if params.melodia_trick:
        events.extend(_melodia_notes(frames, remaining, params))

    times = frame_times(n_frames)
    notes = [
        RawNote(float(times[s]), float(times[e]), f + MIDI_OFFSET, amp) for s, e, f, amp in events
    ]
    return sorted(notes, key=lambda n: (n.start_s, n.pitch))


def _melodia_notes(
    frames: Activations, remaining: npt.NDArray[np.float64], params: DecodeParams
) -> list[tuple[int, int, int, float]]:
    """Add notes from leftover energy that had no detected onset (upstream "melodia trick")."""
    n_frames = frames.shape[0]
    tol, thresh = params.energy_tolerance, params.frame_threshold
    events = []
    while np.max(remaining) > thresh:
        mid, f = (int(x) for x in np.unravel_index(np.argmax(remaining), remaining.shape))
        remaining[mid, f] = 0

        i, k = mid + 1, 0
        while i < n_frames - 1 and k < tol:
            k = k + 1 if remaining[i, f] < thresh else 0
            _clear(remaining, i, i + 1, f)
            i += 1
        end = i - 1 - k

        i, k = mid - 1, 0
        while i > 0 and k < tol:
            k = k + 1 if remaining[i, f] < thresh else 0
            _clear(remaining, i, i + 1, f)
            i -= 1
        start = i + 1 + k

        if end - start <= params.min_note_frames:
            continue
        events.append((start, end, f, float(np.mean(frames[start:end, f]))))
    return events


def _clear(remaining: npt.NDArray[np.float64], start: int, end: int, f: int) -> None:
    """Zero a note's energy in its own pitch bin and both neighbours."""
    remaining[start:end, max(0, f - 1) : f + 2] = 0


def _inferred_onsets(
    onsets: Activations, frames: Activations, n_diff: int = 2
) -> npt.NDArray[np.float64]:
    """Max of predicted onsets and sharp rises in frame activation (rescaled to onsets' max)."""
    diffs = []
    for n in range(1, n_diff + 1):
        shifted = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(shifted[n:, :] - shifted[:-n, :])
    frame_diff = np.min(diffs, axis=0)
    frame_diff[frame_diff < 0] = 0
    frame_diff[:n_diff, :] = 0
    frame_diff = np.max(onsets) * frame_diff / np.max(frame_diff)
    return np.asarray(np.max([onsets, frame_diff], axis=0), dtype=np.float64)
