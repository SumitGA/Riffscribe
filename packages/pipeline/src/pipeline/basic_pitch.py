"""Basic Pitch inference and note decoding, ported from basic-pitch 0.4.0 (Spotify, Apache-2.0).

Changes from upstream: ONNX Runtime only, windows run in batches, and pitch bends, contours,
MIDI writing and the librosa / pretty_midi / mir_eval dependencies are removed. Note decoding
follows upstream `output_to_notes_polyphonic` and runs in Rust (`rust/notes.rs`); tests check
parity against outputs recorded from the real package. Model, licence and NOTICE are in
`pipeline/models/basic_pitch/`. See docs/tech-debt TD-11.
"""

from dataclasses import dataclass
from importlib import resources

import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from pipeline import _tabcore

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

# Belt and braces: telemetry is already off via ORT_DISABLE_TELEMETRY (pipeline/__init__.py).
ort.disable_telemetry_events()


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


LEVEL_REFERENCE = 0.75  # typical 99th-percentile frame activation on GuitarSet mic recordings


def level_gain(frames: Activations, min_pitch: int, max_pitch: int) -> float:
    """Scale that brings a recording's strongest activations up (or down) to LEVEL_REFERENCE.

    Activation strength varies between recordings (a phone recording of the same playing comes
    out weaker than a studio mic), so fixed thresholds drop real notes on quiet recordings.
    Multiplying activations by this gain makes decoding thresholds relative to the recording.
    """
    in_range = frames[:, min_pitch - MIDI_OFFSET : max_pitch - MIDI_OFFSET + 1]
    if in_range.size == 0:
        return 1.0
    return LEVEL_REFERENCE / max(float(np.percentile(in_range, 99)), 1e-3)


ENVELOPE_FPS = SAMPLE_RATE / FFT_HOP  # exact rate of onset_envelope() (~86.13 frames/s)


def onset_envelope(onsets: Activations, min_pitch: int, max_pitch: int) -> npt.NDArray[np.float32]:
    """Onset strength for beat tracking: per-pitch rises in onset activation, summed.

    Like spectral flux, only increases count. Summing raw activations instead lets low-level
    activity across 88 pitches bury the attacks (tempo came out ~120 bpm whatever the music).
    Activation frames are not evenly spaced in time (see `frame_times`), which would skew the
    tempo by ~0.5 %, so the result is resampled onto an even ENVELOPE_FPS grid from 0 s.
    """
    if onsets.shape[0] == 0:
        return np.zeros(0, dtype=np.float32)
    in_range = onsets[:, min_pitch - MIDI_OFFSET : max_pitch - MIDI_OFFSET + 1].astype(np.float64)
    rises = np.maximum(0.0, np.diff(in_range, axis=0, prepend=0.0)).sum(axis=1)
    times = frame_times(rises.size)
    even = np.arange(int(times[-1] * ENVELOPE_FPS) + 1) / ENVELOPE_FPS
    return np.asarray(np.interp(even, times, rises), dtype=np.float32)


def decode_notes(
    frames: Activations, onsets: Activations, params: DecodeParams = UPSTREAM_DEFAULTS
) -> list[RawNote]:
    """Turn activations into notes, sorted by start time then pitch.

    Upstream's algorithm, run in Rust (`rust/notes.rs`); it was the slowest step in Python.
    """
    low = MIDI_OFFSET if params.min_pitch is None else params.min_pitch
    high = MIDI_OFFSET + N_PITCHES - 1 if params.max_pitch is None else params.max_pitch
    events = _tabcore.decode_notes(
        np.ascontiguousarray(frames, dtype=np.float32),
        np.ascontiguousarray(onsets, dtype=np.float32),
        onset_threshold=params.onset_threshold,
        frame_threshold=params.frame_threshold,
        min_note_frames=params.min_note_frames,
        min_pitch_bin=max(0, low - MIDI_OFFSET),
        max_pitch_bin=max(-1, high - MIDI_OFFSET),
        infer_onsets=params.infer_onsets,
        melodia_trick=params.melodia_trick,
        energy_tolerance=params.energy_tolerance,
    )
    times = frame_times(frames.shape[0])
    notes = [
        RawNote(float(times[s]), float(times[e]), b + MIDI_OFFSET, amp) for s, e, b, amp in events
    ]
    return sorted(notes, key=lambda n: (n.start_s, n.pitch))


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
