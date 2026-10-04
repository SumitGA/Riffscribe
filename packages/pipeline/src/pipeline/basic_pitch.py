"""Basic Pitch inference and note decoding, ported from basic-pitch 0.4.0 (Spotify, Apache-2.0).

Changes from upstream: ONNX Runtime only, windows run in batches, and pitch bends, contours,
MIDI writing and the librosa / pretty_midi / mir_eval dependencies are removed. Note decoding
follows upstream `output_to_notes_polyphonic` step by step; tests check parity against outputs
recorded from the real package. Model, licence and NOTICE: `pipeline/models/basic_pitch/`.
See docs/tech-debt TD-11.
"""

from dataclasses import dataclass
from importlib import resources

import numpy as np
import numpy.typing as npt
import onnxruntime as ort
from scipy.signal import argrelmax

SAMPLE_RATE = 22_050
FFT_HOP = 256
FRAMES_PER_SECOND = SAMPLE_RATE // FFT_HOP  # 86
WINDOW_SAMPLES = 2 * SAMPLE_RATE - FFT_HOP  # model input: 2 s windows
WINDOW_FRAMES = 2 * FRAMES_PER_SECOND  # model output frames per window
OVERLAP_FRAMES = 30
OVERLAP_SAMPLES = OVERLAP_FRAMES * FFT_HOP
WINDOW_HOP = WINDOW_SAMPLES - OVERLAP_SAMPLES
MIDI_OFFSET = 21  # pitch bin 0 is A0
N_PITCHES = 88
# Windows per model call. Measured on 5 min of audio (Apple M-series, CPU): inference takes
# ~2.0 s at any batch size, but peak RSS grows with it (4: 256 MB, 16: 398 MB).
BATCH_WINDOWS = 4

_INPUT = "serving_default_input_2:0"
_NOTE_OUTPUT = "StatefulPartitionedCall:1"
_ONSET_OUTPUT = "StatefulPartitionedCall:2"

Audio = npt.NDArray[np.float32]
Activations = npt.NDArray[np.float32]


@dataclass(frozen=True)
class DecodeParams:
    """Upstream `predict()` defaults unless noted."""

    onset_threshold: float = 0.5
    frame_threshold: float = 0.3
    min_note_frames: int = 11  # 127.7 ms
    min_pitch: int | None = None  # inclusive MIDI pitch
    max_pitch: int | None = None  # inclusive MIDI pitch
    infer_onsets: bool = True
    melodia_trick: bool = True
    energy_tolerance: int = 11


@dataclass(frozen=True)
class RawNote:
    start_s: float
    end_s: float
    pitch: int
    amplitude: float  # mean frame activation, 0..1


UPSTREAM_DEFAULTS = DecodeParams()


class BasicPitch:
    """The Basic Pitch ONNX model on CPU."""

    def __init__(self) -> None:
        model = resources.files("pipeline.models.basic_pitch").joinpath("nmp.onnx").read_bytes()
        self._session = ort.InferenceSession(model, providers=["CPUExecutionProvider"])

    def activations(self, audio: Audio) -> tuple[Activations, Activations]:
        """Frame and onset activations, each (n_frames, 88), for mono audio at SAMPLE_RATE."""
        padded = np.concatenate([np.zeros(OVERLAP_SAMPLES // 2, np.float32), audio])
        starts = range(0, padded.size, WINDOW_HOP)
        notes, onsets = [], []
        for first in range(0, len(starts), BATCH_WINDOWS):
            batch = np.stack([_window(padded, s) for s in starts[first : first + BATCH_WINDOWS]])
            note, onset = self._session.run(
                [_NOTE_OUTPUT, _ONSET_OUTPUT], {_INPUT: batch[..., None]}
            )
            notes.append(note)
            onsets.append(onset)
        n_frames = int(np.floor(audio.size * FRAMES_PER_SECOND / SAMPLE_RATE))
        return _unwrap(np.concatenate(notes), n_frames), _unwrap(np.concatenate(onsets), n_frames)


def frame_times(n_frames: int) -> npt.NDArray[np.float64]:
    """Start time in seconds of each activation frame, including upstream's window correction."""
    index = np.arange(n_frames)
    # Upstream: "this is a magic number, but it's needed for this to align properly".
    window_offset = (FFT_HOP / SAMPLE_RATE) * (WINDOW_FRAMES - WINDOW_SAMPLES / FFT_HOP) + 0.0018
    return np.asarray(
        index * FFT_HOP / SAMPLE_RATE - window_offset * np.floor(index / WINDOW_FRAMES),
        dtype=np.float64,
    )


def decode_notes(
    frames: Activations, onsets: Activations, params: DecodeParams = UPSTREAM_DEFAULTS
) -> list[RawNote]:
    """Turn activations into notes, sorted by start time then pitch (upstream algorithm)."""
    frames = frames.copy()
    onsets = onsets.copy()
    n_frames = frames.shape[0]
    tol, thresh = params.energy_tolerance, params.frame_threshold
    if params.max_pitch is not None:
        frames[:, params.max_pitch - MIDI_OFFSET + 1 :] = 0
        onsets[:, params.max_pitch - MIDI_OFFSET + 1 :] = 0
    if params.min_pitch is not None:
        frames[:, : max(0, params.min_pitch - MIDI_OFFSET)] = 0
        onsets[:, : max(0, params.min_pitch - MIDI_OFFSET)] = 0
    if params.infer_onsets:
        onsets = _inferred_onsets(onsets, frames)

    peaks = np.zeros(onsets.shape)
    peak_idx = argrelmax(onsets, axis=0)
    peaks[peak_idx] = onsets[peak_idx]
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


def _inferred_onsets(onsets: Activations, frames: Activations, n_diff: int = 2) -> Activations:
    """Max of predicted onsets and sharp rises in frame activation (rescaled to onsets' max)."""
    diffs = []
    for n in range(1, n_diff + 1):
        shifted = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(shifted[n:, :] - shifted[:-n, :])
    frame_diff = np.min(diffs, axis=0)
    frame_diff[frame_diff < 0] = 0
    frame_diff[:n_diff, :] = 0
    frame_diff = np.max(onsets) * frame_diff / np.max(frame_diff)
    return np.asarray(np.max([onsets, frame_diff], axis=0), dtype=np.float32)


def _window(padded: Audio, start: int) -> Audio:
    window = padded[start : start + WINDOW_SAMPLES]
    if window.size < WINDOW_SAMPLES:
        window = np.pad(window, (0, WINDOW_SAMPLES - window.size))
    return window


def _unwrap(output: Activations, n_frames: int) -> Activations:
    """Drop each window's overlapping edge frames and join the windows into one timeline."""
    half = OVERLAP_FRAMES // 2
    trimmed = output[:, half:-half, :]
    return trimmed.reshape(-1, trimmed.shape[2])[:n_frames]
