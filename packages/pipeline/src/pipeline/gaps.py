"""GAPS guitar note model (Riley et al., ISMIR 2024), ported from piano_transcription_inference
0.1.0 (Kong et al., Apache-2.0) as used by hf_midi_transcription (Riley, MIT).

The model is Kong's high-resolution piano CRNN fine-tuned on classical guitar (GAPS): four
networks over a log-mel spectrogram give, per 10 ms frame and pitch, how close an onset or an
offset is, whether the note sounds, and its velocity. Notes are decoded from those like upstream's
`RegressionPostProcessor`. Changes from upstream: ONNX Runtime instead of PyTorch, the log-mel
spectrogram in numpy instead of torchlibrosa, decoding vectorised in numpy, and the audio split
into 10 s chunks overlapping by 1 s instead of by half (same notes, half the work). The model
file is converted to int8 by `tests/fixtures/gaps/make_reference.py`; tests check parity against
outputs recorded from the real packages. Model, licence and provenance: `pipeline/models/gaps/`.
See ADR-0014.
"""

from importlib import resources
from typing import NamedTuple

import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from pipeline.basic_pitch import RawNote
from pipeline.mel import mel_filters

SAMPLE_RATE = 16_000
N_FFT = 2048
HOP = 160
FPS = SAMPLE_RATE // HOP  # 100 frames per second
N_MELS = 229
F_MIN, F_MAX = 30.0, 8000.0
MIDI_OFFSET = 21  # pitch bin 0 is A0
N_PITCHES = 88
# 10 s, the training length. Peak memory grows with the chunk (30 s chunks: 610 MB, 10 s: 300 MB);
# time per second of audio doesn't.
CHUNK_FRAMES = 1000
BORDER_FRAMES = 50  # predictions this close to a chunk edge are replaced by the next chunk's
# Upstream's defaults, except FRAME_THRESHOLD (0.1 for the piano's sustain pedal): with it, guitar
# notes rang on until the next note on their string. Onset F1 is the same for 0.1-0.6; offset F1
# (onset and offset right) on the 48 GuitarSet tuning clips is 0.749 at 0.1 and 0.768-0.772 for
# 0.2-0.4, so the smallest change: GuitarSet test 0.729 -> 0.759, Guitar-TECHS 0.505 -> 0.526.
ONSET_THRESHOLD = 0.3
OFFSET_THRESHOLD = 0.3
FRAME_THRESHOLD = 0.2
MAX_NOTE_FRAMES = 600  # a note still sounding after 6 s is ended there

Audio = npt.NDArray[np.float32]
Frames = npt.NDArray[np.float32]

# Belt and braces: telemetry is already off via ORT_DISABLE_TELEMETRY (pipeline/__init__.py).
ort.disable_telemetry_events()


class Outputs(NamedTuple):
    """Each (n_frames, N_PITCHES), frame i at i / FPS seconds."""

    onset: Frames  # closeness to an onset, peaking on it
    offset: Frames  # closeness to an offset
    frame: Frames  # probability that the note sounds
    velocity: Frames  # 0..1, read at the onset


class Gaps:
    """The GAPS guitar ONNX model on CPU."""

    def __init__(self) -> None:
        model = resources.files("pipeline.models.gaps").joinpath("guitar.onnx").read_bytes()
        options = ort.SessionOptions()
        options.enable_cpu_mem_arena = False  # as for Beat This!: memory returned after each run
        self._session = ort.InferenceSession(model, options, providers=["CPUExecutionProvider"])

    def outputs(self, audio: Audio) -> Outputs:
        """The model's four outputs for mono audio at SAMPLE_RATE."""
        mel = log_mel(audio)
        out = np.zeros((4, len(mel), N_PITCHES), np.float32)
        for start, keep_from, keep_to in chunks(len(mel)):
            chunk = mel[None, None, start : start + CHUNK_FRAMES]
            result = np.stack([o[0] for o in self._session.run(None, {"mel": chunk})])
            out[:, keep_from:keep_to] = result[:, keep_from - start : keep_to - start]
        return Outputs(*out)


def chunks(n_frames: int) -> list[tuple[int, int, int]]:
    """(start, keep_from, keep_to) per chunk: chunks overlap by 2 * BORDER_FRAMES, each keeps
    the frames from the middle of the overlap on, the last one ends at the end."""
    if n_frames <= CHUNK_FRAMES:
        return [(0, 0, n_frames)]
    step = CHUNK_FRAMES - 2 * BORDER_FRAMES
    starts = [*range(0, n_frames - CHUNK_FRAMES, step), n_frames - CHUNK_FRAMES]
    keep = [0] + [s + BORDER_FRAMES for s in starts[1:]] + [n_frames]
    return [(s, max(keep[i], 0), keep[i + 1]) for i, s in enumerate(starts)]


def log_mel(audio: Audio) -> Frames:
    """(n_frames, N_MELS) log-mel power spectrogram in dB, as torchlibrosa computes it: centred
    frames with reflect padding, periodic Hann window, power, Slaney mel filters with area
    normalisation (librosa's defaults), 10 * log10 with a floor of 1e-10."""
    padded = np.pad(audio.astype(np.float32), N_FFT // 2, mode="reflect")
    n_frames = 1 + audio.size // HOP
    window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)
    filters = mel_filters(SAMPLE_RATE, N_FFT, N_MELS, F_MIN, F_MAX, area_norm=True)
    out = np.empty((n_frames, N_MELS), np.float32)
    block = 1024  # frames per FFT batch, to bound memory on long clips
    for first in range(0, n_frames, block):
        count = min(block, n_frames - first)
        index = (first + np.arange(count))[:, None] * HOP + np.arange(N_FFT)
        spectrum = np.fft.rfft(padded[index] * window, axis=1)
        power = (spectrum.real**2 + spectrum.imag**2).astype(np.float32)
        out[first : first + count] = power @ filters
    np.maximum(out, 1e-10, out=out)
    np.log10(out, out=out)
    out *= 10
    return out


def decode_notes(outputs: Outputs, min_pitch: int, max_pitch: int) -> list[RawNote]:
    """Notes from the model's outputs, sorted by start time then pitch (upstream's
    `RegressionPostProcessor`; `amplitude` is the velocity output at the onset)."""
    onsets, onset_shift = _peaks(outputs.onset, ONSET_THRESHOLD, neighbour=2)
    offsets, offset_shift = _peaks(outputs.offset, OFFSET_THRESHOLD, neighbour=4)
    n = len(outputs.onset)
    notes = []
    for b in range(max(0, min_pitch - MIDI_OFFSET), min(N_PITCHES, max_pitch - MIDI_OFFSET + 1)):
        starts = np.flatnonzero(onsets[:, b])
        ends = np.flatnonzero(offsets[:, b])
        silent = np.flatnonzero(outputs.frame[:, b] <= FRAME_THRESHOLD)
        for j, begin in enumerate(starts.tolist()):
            following = int(starts[j + 1]) if j + 1 < len(starts) else n
            gone = _first_after(silent, begin, n)
            limit = min(begin + MAX_NOTE_FRAMES, n - 1)
            if following <= min(gone, limit):  # re-picked while sounding: ends just before
                end, shift = following - 1, 0.0
            elif gone <= limit:  # an offset well after the onset beats the frame fading out
                offset = _first_after(ends, begin, n)
                close = offset <= gone and offset - begin > gone - offset
                end = offset if close else gone
                shift = float(offset_shift[end, b])
            else:
                end, shift = limit, float(offset_shift[limit, b])
            notes.append(
                RawNote(
                    float((begin + onset_shift[begin, b]) / FPS),
                    float((end + shift) / FPS),
                    b + MIDI_OFFSET,
                    float(outputs.velocity[begin, b]),
                )
            )
    return sorted(notes, key=lambda note: (note.start_s, note.pitch))


def _first_after(indices: npt.NDArray[np.intp], frame: int, default: int) -> int:
    i = int(np.searchsorted(indices, frame, side="right"))
    return int(indices[i]) if i < len(indices) else default


def _peaks(
    curve: Frames, threshold: float, neighbour: int
) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.float32]]:
    """Frames where the curve is above the threshold and rises for `neighbour` frames before and
    falls for `neighbour` after, and each peak's sub-frame offset from a triangle fitted through
    its neighbours (Kong et al. 2021, section III-D)."""
    n = len(curve)
    peaks = np.zeros(curve.shape, bool)
    shift = np.zeros(curve.shape, np.float32)
    if n <= 2 * neighbour:
        return peaks, shift
    inner = slice(neighbour, n - neighbour)
    is_peak = curve[inner] > threshold
    for i in range(neighbour):
        is_peak &= (
            curve[neighbour - i : n - neighbour - i]
            >= curve[neighbour - i - 1 : n - neighbour - i - 1]
        )
        is_peak &= (
            curve[neighbour + i : n - neighbour + i]
            >= curve[neighbour + i + 1 : n - neighbour + i + 1]
        )
    peaks[inner] = is_peak
    centre, before, after = (
        curve[inner],
        curve[neighbour - 1 : n - neighbour - 1],
        curve[neighbour + 1 : n - neighbour + 1],
    )
    side = np.where(before > after, after, before)
    with np.errstate(divide="ignore", invalid="ignore"):
        fitted = (after - before) / (centre - side) / 2
    # Upstream divides by zero on a flat-topped peak; such a peak gets no shift instead.
    shift[inner] = np.where(is_peak & np.isfinite(fitted), fitted, 0)
    return peaks, shift
