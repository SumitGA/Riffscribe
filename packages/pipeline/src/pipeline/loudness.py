"""Integrated loudness (ITU-R BS.1770-4, mono), computed in chunks so memory stays flat.

Uses the same K-weighting biquads as pyloudnorm (RBJ cookbook formulas); a test checks that the
two agree. pyloudnorm itself makes several full-length float64 copies (~5x the audio size).
"""

import math

import numpy as np
import numpy.typing as npt
from scipy import signal

_SUBBLOCK_S = 0.1  # 400 ms gating blocks with 75 % overlap = 4 consecutive 100 ms sub-blocks
_SUBBLOCKS_PER_BLOCK = 4
_CHUNK_SUBBLOCKS = 20  # filter 2 s at a time (~2 MB of float64 scratch)
_ABSOLUTE_GATE_LUFS = -70.0
_RELATIVE_GATE_LU = -10.0


def integrated_loudness(audio: npt.NDArray[np.float32], rate: int) -> float:
    """Gated loudness in LUFS, or -inf if every block is below the absolute gate."""
    sub = round(_SUBBLOCK_S * rate)
    n_sub = audio.size // sub
    if n_sub < _SUBBLOCKS_PER_BLOCK:
        return -math.inf

    sos = _k_weighting(rate)
    zi = np.zeros((sos.shape[0], 2))
    power = np.empty(n_sub)  # mean square of each K-weighted sub-block
    chunk = sub * _CHUNK_SUBBLOCKS
    for start in range(0, n_sub * sub, chunk):
        stop = min(start + chunk, n_sub * sub)
        filtered, zi = signal.sosfilt(sos, audio[start:stop].astype(np.float64), zi=zi)
        frames = filtered.reshape(-1, sub)
        power[start // sub : stop // sub] = np.einsum("ij,ij->i", frames, frames) / sub

    blocks = np.convolve(power, np.full(_SUBBLOCKS_PER_BLOCK, 1 / _SUBBLOCKS_PER_BLOCK), "valid")
    with np.errstate(divide="ignore"):
        block_lufs = _lufs(blocks)
    above_abs = block_lufs > _ABSOLUTE_GATE_LUFS
    if not above_abs.any():
        return -math.inf
    relative_gate = float(_lufs(blocks[above_abs].mean())) + _RELATIVE_GATE_LU
    gated = blocks[above_abs & (block_lufs > relative_gate)]
    return float(_lufs(gated.mean()))


def _lufs(mean_square: npt.ArrayLike) -> npt.NDArray[np.float64]:
    return np.asarray(-0.691 + 10 * np.log10(mean_square), dtype=np.float64)


def _k_weighting(rate: int) -> npt.NDArray[np.float64]:
    """Second-order sections: high shelf (+4 dB above ~1.5 kHz), then high pass at 38 Hz."""
    return np.array([_high_shelf(rate, 4.0, 1 / math.sqrt(2), 1500.0), _high_pass(rate, 0.5, 38.0)])


def _high_shelf(rate: int, gain_db: float, q: float, fc: float) -> list[float]:
    a = 10 ** (gain_db / 40)
    w0 = 2 * math.pi * fc / rate
    cos, alpha = math.cos(w0), math.sin(w0) / (2 * q)
    k = 2 * math.sqrt(a) * alpha
    b0 = a * ((a + 1) + (a - 1) * cos + k)
    b1 = -2 * a * ((a - 1) + (a + 1) * cos)
    b2 = a * ((a + 1) + (a - 1) * cos - k)
    a0 = (a + 1) - (a - 1) * cos + k
    a1 = 2 * ((a - 1) - (a + 1) * cos)
    a2 = (a + 1) - (a - 1) * cos - k
    return [b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]


def _high_pass(rate: int, q: float, fc: float) -> list[float]:
    w0 = 2 * math.pi * fc / rate
    cos, alpha = math.cos(w0), math.sin(w0) / (2 * q)
    a0 = 1 + alpha
    b = [(1 + cos) / 2, -(1 + cos), (1 + cos) / 2]
    return [b[0] / a0, b[1] / a0, b[2] / a0, 1.0, -2 * cos / a0, (1 - alpha) / a0]
