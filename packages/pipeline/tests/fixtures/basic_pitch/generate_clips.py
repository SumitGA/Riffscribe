"""Write the synthetic clips used by the Basic Pitch parity tests.

The WAVs are committed; this script documents how they were made. Run from the repo root:
    uv run python packages/pipeline/tests/fixtures/basic_pitch/generate_clips.py
"""

from pathlib import Path

import numpy as np
import soundfile

RATE = 22_050  # Basic Pitch's model rate, so the reference run does no resampling
HERE = Path(__file__).parent


def hz(midi: int) -> float:
    return float(440.0 * 2 ** ((midi - 69) / 12))


def piano_note(midi: int, seconds: float) -> np.ndarray:
    """Additive tone with decaying harmonics, roughly piano-like."""
    t = np.arange(int(seconds * RATE)) / RATE
    tone = sum(np.sin(2 * np.pi * hz(midi) * k * t) / k**1.5 for k in range(1, 7))
    return np.asarray(tone * np.exp(-3.0 * t) * np.minimum(1, t / 0.005))


def plucked_string(midi: int, seconds: float, seed: int) -> np.ndarray:
    """Karplus-Strong plucked string, roughly guitar-like."""
    n = int(seconds * RATE)
    period = round(RATE / hz(midi))
    buf = np.random.default_rng(seed).uniform(-1, 1, period)
    out = np.empty(n)
    for i in range(n):
        out[i] = buf[i % period]
        buf[i % period] = 0.996 * 0.5 * (buf[i % period] + buf[(i + 1) % period])
    return out


def place(events: list[tuple[float, np.ndarray]], seconds: float) -> np.ndarray:
    mix = np.zeros(int(seconds * RATE))
    for start, note in events:
        i = int(start * RATE)
        mix[i : i + note.size] += note[: mix.size - i]
    return np.asarray(0.5 * mix / np.abs(mix).max())


def piano_clip() -> np.ndarray:
    arpeggio = [(0.25 * i, piano_note(m, 0.6)) for i, m in enumerate([60, 64, 67, 72, 67, 64])]
    chord = [(2.0, piano_note(m, 1.5)) for m in [53, 57, 60]]  # F major
    melody = [(3.6 + 0.4 * i, piano_note(m, 0.5)) for i, m in enumerate([69, 71, 72, 74])]
    return place(arpeggio + chord + melody, 6.0)


def guitar_clip() -> np.ndarray:
    riff = [40, 43, 45, 47, 50, 52, 50, 47]  # E minor pentatonic from low E
    events = [(0.3 * i, plucked_string(m, 1.0, seed=i)) for i, m in enumerate(riff)]
    dyads = [(2.6, plucked_string(45, 1.5, 20)), (2.6, plucked_string(52, 1.5, 21))]
    dyads += [(4.0, plucked_string(47, 1.5, 22)), (4.0, plucked_string(54, 1.5, 23))]
    return place(events + dyads, 6.0)


if __name__ == "__main__":
    for name, clip in [("piano_like", piano_clip()), ("guitar_like", guitar_clip())]:
        soundfile.write(HERE / f"{name}.wav", clip.astype(np.float32), RATE, subtype="PCM_16")
        print(f"wrote {name}.wav")
