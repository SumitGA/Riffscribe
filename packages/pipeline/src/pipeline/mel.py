"""Slaney mel filter banks, as librosa and torchaudio build them (librosa is not a dependency)."""

import numpy as np
import numpy.typing as npt


def mel_filters(
    sample_rate: int, n_fft: int, n_mels: int, f_min: float, f_max: float, *, area_norm: bool
) -> npt.NDArray[np.float32]:
    """(n_fft/2+1, n_mels) triangular filters on the Slaney mel scale. `area_norm` scales each
    to unit area (librosa's default `norm="slaney"`); without it every peak is 1 (torchaudio's
    `norm=None`)."""
    freqs = np.linspace(0, sample_rate // 2, n_fft // 2 + 1)
    edges = _mel_to_hz(np.linspace(_hz_to_mel(f_min), _hz_to_mel(f_max), n_mels + 2))
    widths = np.diff(edges)
    slopes = edges[None, :] - freqs[:, None]
    down = -slopes[:, :-2] / widths[:-1]
    up = slopes[:, 2:] / widths[1:]
    filters = np.maximum(0, np.minimum(down, up))
    if area_norm:
        filters *= 2 / (edges[2:] - edges[:-2])
    return filters.astype(np.float32)


_MEL_STEP_HZ = 200 / 3  # Slaney: linear below 1 kHz, logarithmic above
_LOG_START_HZ = 1000.0
_LOG_STEP = np.log(6.4) / 27


def _hz_to_mel(hz: float) -> float:
    if hz < _LOG_START_HZ:
        return hz / _MEL_STEP_HZ
    return float(_LOG_START_HZ / _MEL_STEP_HZ + np.log(hz / _LOG_START_HZ) / _LOG_STEP)


def _mel_to_hz(mels: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    log_start = _LOG_START_HZ / _MEL_STEP_HZ
    linear = mels * _MEL_STEP_HZ
    logarithmic = _LOG_START_HZ * np.exp(_LOG_STEP * (mels - log_start))
    return np.where(mels >= log_start, logarithmic, linear)
