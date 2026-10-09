from fractions import Fraction

import numpy as np
import numpy.typing as npt
import pytest

from pipeline.chords import ChordParams, ChordSpan, recognize_chords
from pipeline.stages.quantize import chord_symbols

pytestmark = pytest.mark.unit

FPS = 86.0
C, G, A = 0, 7, 9
PER_BEAT = ChordParams(subdivisions=1)  # one chord per beat keeps the expectations short


def activations(
    chords: list[tuple[int, ...]], seconds_each: float = 1.0
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Frames where each chord's MIDI pitches are fully active for `seconds_each` in turn."""
    per = int(seconds_each * FPS)
    frames = np.zeros((per * len(chords), 88))
    for i, pitches in enumerate(chords):
        for pitch in pitches:
            frames[i * per : (i + 1) * per, pitch - 21] = 0.9
    return frames, np.arange(len(frames)) / FPS


def labels(beats: list[list[ChordSpan | None]]) -> list[tuple[int, str] | None]:
    return [None if c is None else (c.root, c.quality) for beat in beats for c in beat]


def test_open_chord_shapes_are_named() -> None:
    c_major = (48, 52, 55, 60, 64)  # x32010
    g_major = (43, 47, 50, 55, 59, 67)  # 320003
    a_minor = (45, 52, 57, 60, 64)  # x02210
    frames, times = activations([c_major, g_major, a_minor])
    beats = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]

    assert labels(recognize_chords(frames, times, beats)) == (
        [(C, "maj")] * 4 + [(G, "maj")] * 4 + [(A, "min")] * 4  # two spans per beat by default
    )


def test_one_odd_beat_does_not_flip_the_chord() -> None:
    c_major, f_note = (48, 52, 55, 60, 64), (53, 57, 60)  # a passing F chord for half a beat
    frames, times = activations([c_major, c_major, f_note, c_major, c_major], seconds_each=0.5)
    beats = list(np.arange(6) * 0.5)

    found = labels(recognize_chords(frames, times, beats, PER_BEAT))
    assert found == [(C, "maj")] * 5


def test_silence_has_no_chord() -> None:
    frames, times = activations([(), (48, 52, 55)])

    found = labels(recognize_chords(frames, times, [0.0, 1.0, 2.0], PER_BEAT))
    assert found == [None, (C, "maj")]


def test_subdivisions_give_spans_within_each_beat() -> None:
    frames, times = activations([(48, 52, 55), (43, 47, 50)], seconds_each=0.5)
    beats = recognize_chords(
        frames, times, [0.0, 1.0], ChordParams(subdivisions=2, stay_probability=0.5)
    )

    assert labels(beats) == [(C, "maj"), (G, "maj")]
    assert [(c.start_s, c.end_s) for c in beats[0] if c] == [(0.0, 0.5), (0.5, 1.0)]


def test_too_few_beats_gives_no_chords() -> None:
    frames, times = activations([(48, 52, 55)])

    assert recognize_chords(frames, times, [0.5]) == []


def test_runs_of_the_same_chord_become_one_symbol() -> None:
    def span(start: float, root: int) -> ChordSpan:
        return ChordSpan(start, start + 0.5, root, "maj")

    symbols = chord_symbols([[span(0, C)], [span(0.5, C)], [None], [span(1.5, G)], [span(2, G)]])

    assert [(s.root, s.onset_beats, s.duration_beats) for s in symbols] == [
        (C, Fraction(0), Fraction(2)), (G, Fraction(3), Fraction(2)),
    ]  # fmt: skip
    assert (symbols[0].onset_s, symbols[0].offset_s) == (0.0, 1.0)
