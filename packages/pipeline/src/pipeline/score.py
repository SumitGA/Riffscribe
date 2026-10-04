"""The quantized score: notes on a beat grid plus meter, key and tempo (quantized.json)."""

from fractions import Fraction
from typing import Literal

from pipeline.types import Frozen


class ScoreNote(Frozen):
    pitch: int
    velocity: int
    onset_beats: Fraction  # from the start of the first (possibly partial) bar
    duration_beats: Fraction
    onset_s: float  # original timing, for playback sync and debugging
    offset_s: float


class KeySignature(Frozen):
    tonic: int  # pitch class, 0 = C
    mode: Literal["major", "minor"]
    fifths: int  # sharps > 0, flats < 0


class Score(Frozen):
    """Contents of quantized.json."""

    tempo_bpm: float
    beats_per_bar: int
    beat_unit: int
    pickup_beats: int
    key: KeySignature
    beat_times_s: list[float]  # time in the normalized audio of beat 0, 1, 2, ...
    notes: list[ScoreNote]
