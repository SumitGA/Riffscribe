import math
from collections.abc import Callable

import numpy as np
import pyloudnorm
import pytest

from pipeline.loudness import integrated_loudness

pytestmark = pytest.mark.unit

RNG = np.random.default_rng(0)


def sine(seconds: float, rate: int, amp: float, freq: float) -> np.ndarray:
    return (amp * np.sin(2 * np.pi * freq * np.arange(int(seconds * rate)) / rate)).astype(
        np.float32
    )


SIGNALS: dict[str, Callable[[int], np.ndarray]] = {
    "low-sine": lambda rate: sine(5, rate, 0.3, 100),
    "high-sine": lambda rate: sine(5, rate, 0.1, 5000),
    "noise": lambda rate: (0.05 * RNG.standard_normal(12 * rate)).astype(np.float32),
    # The quiet half falls under the relative gate, so this exercises gating.
    "loud-then-quiet": lambda rate: np.concatenate(
        [sine(4, rate, 0.5, 440), sine(4, rate, 0.002, 440)]
    ),
}


@pytest.mark.parametrize("rate", [44_100, 48_000])
@pytest.mark.parametrize("name", SIGNALS)
def test_matches_pyloudnorm_reference(name: str, rate: int) -> None:
    audio = SIGNALS[name](rate)
    expected = pyloudnorm.Meter(rate).integrated_loudness(audio.astype(np.float64))

    assert integrated_loudness(audio, rate) == pytest.approx(expected, abs=0.05)


def test_silence_and_too_short_audio_are_minus_infinity() -> None:
    assert integrated_loudness(np.zeros(44_100 * 2, dtype=np.float32), 44_100) == -math.inf
    assert integrated_loudness(sine(0.3, 44_100, 0.5, 440), 44_100) == -math.inf
