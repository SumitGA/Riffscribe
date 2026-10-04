"""Tempo estimation and beat tracking (Ellis 2007), ported from librosa 1.0.0 (ISC licence).

Same algorithm and defaults as `librosa.beat.beat_track(onset_envelope=...)`; tests check that
both give the same tempo and beats. Changes from librosa:
- The tempogram is averaged chunk by chunk instead of being built in full (librosa holds a
  `win_length x n_frames` float64 matrix, ~140 MB for 5 minutes at 86 frames/s).
- No numba: the dynamic program uses numpy per frame (see ADR-0005 for measurements).
- Static tempo only (no time-varying bpm).

librosa: Copyright (c) 2013--2023, librosa development team. ISC licence, see ADR-0005.
"""

import math

import numpy as np
import numpy.typing as npt
from scipy.fft import next_fast_len
from scipy.signal import get_window

Envelope = npt.NDArray[np.float64]

START_BPM = 120.0
STD_BPM = 1.0  # width, in octaves, of the log-normal tempo prior
AC_SIZE_S = 8.0  # autocorrelation window
MAX_TEMPO = 320.0
TIGHTNESS = 100.0  # how strongly beats must follow the tempo
_CHUNK_FRAMES = 512  # tempogram columns processed at a time


def beat_track(envelope: Envelope, fps: float) -> tuple[float, npt.NDArray[np.int64]]:
    """(tempo in bpm, beat frame indices) for an onset-strength envelope sampled at `fps`."""
    if not envelope.any():
        return 0.0, np.empty(0, dtype=np.int64)
    bpm = estimate_tempo(envelope, fps)
    return bpm, track_beats(envelope, fps, bpm)


def estimate_tempo(envelope: Envelope, fps: float) -> float:
    """Global tempo: the mean local autocorrelation peak, weighted by a prior around 120 bpm."""
    win = math.floor(AC_SIZE_S * fps)  # librosa time_to_frames
    tempogram = _mean_tempogram(envelope, win)
    with np.errstate(divide="ignore"):
        bpms = np.concatenate([[np.inf], 60.0 * fps / np.arange(1.0, win)])
        logprior = -0.5 * ((np.log2(bpms) - np.log2(START_BPM)) / STD_BPM) ** 2
    logprior[: int(np.argmax(bpms < MAX_TEMPO))] = -np.inf
    return float(bpms[int(np.argmax(np.log1p(1e6 * tempogram) + logprior))])


def track_beats(
    envelope: Envelope, fps: float, bpm: float, trim: bool = True
) -> npt.NDArray[np.int64]:
    """Beat frames: dynamic programming over a smoothed, normalized envelope."""
    period = float(np.round(fps * 60.0 / bpm))
    normalized = envelope / (envelope.std(ddof=1) + np.finfo(envelope.dtype).tiny)
    localscore = _local_score(normalized, period)
    backlink, cumscore = _dynamic_program(localscore, period)

    beats = np.zeros(localscore.size, dtype=bool)
    n = _last_beat(cumscore)
    while n >= 0:
        beats[n] = True
        n = int(backlink[n])
    return np.flatnonzero(_trim(localscore, beats, trim)).astype(np.int64)


def _mean_tempogram(envelope: Envelope, win: int) -> npt.NDArray[np.float64]:
    """Mean over frames of librosa.feature.tempogram (centered, hann window, inf-norm)."""
    n = envelope.size
    padded = np.pad(envelope, win // 2, mode="linear_ramp", end_values=(0, 0))
    window = get_window("hann", win, fftbins=True)
    n_fft = int(next_fast_len(2 * win - 1, real=True))
    total = np.zeros(win)
    for first in range(0, n, _CHUNK_FRAMES):
        count = min(_CHUNK_FRAMES, n - first)
        idx = first + np.arange(count)[None, :] + np.arange(win)[:, None]
        frames = padded[idx] * window[:, None]  # (win, count)
        spectrum = np.fft.rfft(frames, n=n_fft, axis=0)
        ac = np.fft.irfft(spectrum.real**2 + spectrum.imag**2, n=n_fft, axis=0)[:win]
        norm = np.abs(ac).max(axis=0)
        norm[norm < np.finfo(np.float64).tiny] = 1.0
        total += (ac / norm).sum(axis=1)
    return total / n


def _local_score(onsets: Envelope, period: float) -> Envelope:
    """librosa's same-mode convolution with a Gaussian of width ~period/32 (index 0 quirk kept)."""
    window = np.exp(-0.5 * (np.arange(-period, period + 1) * 32.0 / period) ** 2)
    k_len, n = window.size, onsets.size
    full = np.convolve(onsets, window)  # full[j] = sum_k window[k] * onsets[j - k]
    score = full[k_len // 2 : k_len // 2 + n].copy()
    # librosa's loop stops one short of k = i + K//2, dropping onsets[0] while i + K//2 < K.
    affected = np.arange(min(n, k_len - k_len // 2))
    score[affected] -= window[affected + k_len // 2] * onsets[0]
    return score


def _dynamic_program(
    localscore: Envelope, period: float
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64]]:
    n = localscore.size
    backlink = np.full(n, -1, dtype=np.int64)
    cumscore = np.zeros(n)
    score_thresh = 0.01 * localscore.max()
    # Predecessors are i - offset for offset in [period/2, 2 * period], nearest first.
    offsets = np.arange(round(period / 2), int(2 * period) + 1)
    penalty = TIGHTNESS * (np.log(offsets) - np.log(period)) ** 2
    first_beat = True
    for i in range(n):
        reachable = int(np.searchsorted(offsets, i, side="right"))
        best_loc, best = -1, -np.inf
        if reachable:
            candidates = cumscore[i - offsets[:reachable]] - penalty[:reachable]
            j = int(np.argmax(candidates))  # first max = nearest predecessor, as librosa
            best, best_loc = float(candidates[j]), i - int(offsets[j])
        cumscore[i] = localscore[i] + best if best_loc >= 0 else localscore[i]
        if first_beat and localscore[i] < score_thresh:
            backlink[i] = -1
        else:
            backlink[i] = best_loc
            first_beat = False
    return backlink, cumscore


def _last_beat(cumscore: npt.NDArray[np.float64]) -> int:
    """Last local maximum of the cumulative score above half the median local maximum."""
    padded = np.pad(cumscore, 1, mode="edge")
    is_max = (cumscore > padded[:-2]) & (cumscore >= padded[2:])
    if not is_max.any():
        return cumscore.size - 1
    threshold = 0.5 * float(np.median(cumscore[is_max]))
    candidates = np.flatnonzero(is_max & (cumscore >= threshold))
    return int(candidates[-1]) if candidates.size else cumscore.size - 1


def _trim(localscore: Envelope, beats: npt.NDArray[np.bool_], trim: bool) -> npt.NDArray[np.bool_]:
    """Drop leading/trailing frames whose local score is under half the beats' smoothed RMS."""
    trimmed = beats.copy()
    w = np.hanning(5)
    smooth = np.convolve(localscore[beats], w)[len(w) // 2 : localscore.size + len(w) // 2]
    threshold = 0.5 * float(np.sqrt(np.mean(smooth**2))) if trim else 0.0
    n = 0
    while n < localscore.size and localscore[n] <= threshold:
        trimmed[n] = False
        n += 1
    n = localscore.size - 1
    while n >= 0 and localscore[n] <= threshold:
        trimmed[n] = False
        n -= 1
    return trimmed
