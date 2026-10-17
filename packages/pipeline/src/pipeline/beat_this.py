"""Beat This! beat and downbeat tracking, ported from beat_this 1.1.0 (CPJKU, MIT).

Changes from upstream: ONNX Runtime instead of PyTorch, the log-mel spectrogram in numpy instead
of torchaudio, and no post-processor: the quantize stage tracks beats over the model's beat
probabilities with our Ellis tracker (`pipeline/beats.py`), which keeps them evenly spaced.
The model is the `small0` checkpoint exported to ONNX with fused attention and int8 matrix
weights (`tests/fixtures/beat_this/make_reference.py`); tests check parity against outputs
recorded from the real package. Model, licence and provenance: `pipeline/models/beat_this/`.
See ADR-0013.
"""

import math
from importlib import resources

import numpy as np
import numpy.typing as npt
import onnxruntime as ort

from pipeline.mel import mel_filters

SAMPLE_RATE = 22_050
N_FFT = 1024
HOP = 441
FPS = SAMPLE_RATE / HOP  # 50 frames per second
N_MELS = 128
F_MIN, F_MAX = 30.0, 11_000.0
LOG_MULTIPLIER = 1000.0
CHUNK_FRAMES = 1500  # the model's training length, 30 s
BORDER_FRAMES = 6  # predictions this close to a chunk edge are discarded

Audio = npt.NDArray[np.float32]
Frames = npt.NDArray[np.float32]

# Belt and braces: telemetry is already off via ORT_DISABLE_TELEMETRY (pipeline/__init__.py).
ort.disable_telemetry_events()


class BeatThis:
    """The Beat This! small0 ONNX model on CPU."""

    def __init__(self) -> None:
        model = resources.files("pipeline.models.beat_this").joinpath("small0.onnx").read_bytes()
        options = ort.SessionOptions()
        # Without the arena the ~200 MB that attention over a 30 s chunk needs is returned after
        # each run instead of staying with the worker; measured no slower.
        options.enable_cpu_mem_arena = False
        self._session = ort.InferenceSession(model, options, providers=["CPUExecutionProvider"])

    def logits(self, audio: Audio) -> tuple[Frames, Frames]:
        """Beat and downbeat logits per frame (FPS) for mono audio at SAMPLE_RATE."""
        spect = log_mel(audio)
        beat = np.empty(len(spect), np.float32)
        downbeat = np.empty(len(spect), np.float32)
        # Chunks one at a time: attention memory grows with the square of the chunk length.
        # Later chunks are written first, so where chunks overlap the earlier one wins
        # (upstream "keep_first").
        for start in reversed(chunk_starts(len(spect))):
            lo, hi = max(start, 0), min(start + CHUNK_FRAMES, len(spect))
            right = max(0, min(BORDER_FRAMES, start + CHUNK_FRAMES - len(spect)))
            chunk = np.pad(spect[lo:hi], ((lo - start, right), (0, 0)))
            b, d = self._session.run(None, {"spect": chunk[None]})
            keep = slice(start + BORDER_FRAMES, start + len(chunk) - BORDER_FRAMES)
            beat[keep] = b[0, BORDER_FRAMES:-BORDER_FRAMES]
            downbeat[keep] = d[0, BORDER_FRAMES:-BORDER_FRAMES]
        return beat, downbeat

    def activations(self, audio: Audio) -> Frames:
        """(n_frames, 2) probabilities that a beat / a downbeat falls on each frame (FPS)."""
        logits = np.stack(self.logits(audio), axis=1)
        return (1 / (1 + np.exp(-logits))).astype(np.float32)


def chunk_starts(n_frames: int) -> list[int]:
    """Upstream `split_piece`: chunks overlap by BORDER_FRAMES, the last one ends at the end."""
    step = CHUNK_FRAMES - 2 * BORDER_FRAMES
    starts = list(range(-BORDER_FRAMES, n_frames - BORDER_FRAMES, step))
    if n_frames > step:
        starts[-1] = n_frames - (CHUNK_FRAMES - BORDER_FRAMES)
    return starts


def log_mel(audio: Audio) -> Frames:
    """(n_frames, N_MELS) log1p(1000 * magnitude mel spectrogram), as torchaudio computes it:
    centred frames with reflect padding, periodic Hann window, magnitude divided by sqrt(N_FFT)
    ("frame_length" normalisation), Slaney mel filters without area normalisation."""
    padded = np.pad(audio.astype(np.float32), N_FFT // 2, mode="reflect")
    n_frames = 1 + audio.size // HOP
    window = _hann()
    filters = mel_filters(SAMPLE_RATE, N_FFT, N_MELS, F_MIN, F_MAX, area_norm=False)
    out = np.empty((n_frames, N_MELS), np.float32)
    block = 2048  # frames per FFT batch, to bound memory on long clips
    for first in range(0, n_frames, block):
        count = min(block, n_frames - first)
        index = (first + np.arange(count))[:, None] * HOP + np.arange(N_FFT)
        magnitude = np.abs(np.fft.rfft(padded[index] * window, axis=1)).astype(np.float32)
        out[first : first + count] = magnitude @ filters
    np.log1p(LOG_MULTIPLIER * out, out=out)
    return out


def _hann() -> npt.NDArray[np.float32]:
    window = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)  # periodic
    return (window / math.sqrt(N_FFT)).astype(np.float32)  # torch.stft(normalized=True)
