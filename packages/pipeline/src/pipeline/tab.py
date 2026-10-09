"""Guitar tab: a string and fret for every note (search runs in Rust, rust/tab.rs)."""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from importlib import resources

from pipeline import _tabcore
from pipeline.config import Tuning
from pipeline.score import ScoreNote

# Open-string pitches, lowest string first.
TUNINGS: dict[Tuning, tuple[int, ...]] = {
    Tuning.STANDARD: (40, 45, 50, 55, 59, 64),
    Tuning.DROP_D: (38, 45, 50, 55, 59, 64),
}
MAX_FRET = 24
# Position prior: each note costs PRIOR_WEIGHT * -log P(string | pitch), with P counted from the
# fingerings GuitarSet players used (models/tab_prior; tuned in tests/tuning/tune_tab.py). It
# keeps a stray high note from dragging a whole solo to frets 18-22 of the low strings.
PRIOR_WEIGHT = 1.0
PRIOR_SMOOTHING = 1.0  # added to every count, so unseen positions are rare, not impossible


@dataclass(frozen=True)
class TabPosition:
    string: int  # 1 = highest string, as written in tab
    fret: int  # relative to the capo


def assign_tab(
    notes: Sequence[ScoreNote],
    tuning: Tuning,
    capo: int,
    weights: Mapping[str, float] | None = None,
    prior_weight: float = PRIOR_WEIGHT,
) -> dict[tuple[Fraction, int], TabPosition]:
    """Positions keyed by (onset_beats, pitch). Notes that can't be played are left out.

    `weights` overrides fingering cost weights (names as in rust/tab.rs `Weights`); only the
    tuning script sets them, and `prior_weight`.
    """
    by_onset: dict[Fraction, list[int]] = {}
    for n in notes:
        by_onset.setdefault(n.onset_beats, []).append(n.pitch)
    onsets = sorted(by_onset)
    chords = [sorted(set(by_onset[o])) for o in onsets]
    strings = TUNINGS[tuning]
    open_strings = [p + capo for p in strings]

    max_fret = MAX_FRET - capo
    prior = position_cost(string_counts(), prior_weight, len(strings), max_fret)
    placed = _tabcore.tab_positions(
        chords, open_strings, max_fret, position_cost=prior, **(weights or {})
    )
    positions = {}
    for onset, chord, chord_positions in zip(onsets, chords, placed, strict=True):
        for pitch, position in zip(chord, chord_positions, strict=True):
            if position is not None:
                string_index, fret = position
                positions[(onset, pitch)] = TabPosition(len(strings) - string_index, fret)
    return positions


@cache
def string_counts() -> dict[int, list[int]]:
    """MIDI pitch -> how often each string played it (lowest string first), standard tuning."""
    path = resources.files("pipeline.models.tab_prior").joinpath("string_counts.json")
    raw: dict[str, list[int]] = json.loads(path.read_text())["counts"]
    return {int(pitch): counts for pitch, counts in raw.items()}


def position_cost(
    counts: Mapping[int, Sequence[int]], weight: float, n_strings: int, max_fret: int
) -> list[list[float]]:
    """Cost per (string index from the lowest string, fret): weight * -log P(string | pitch).

    Positions are looked up as if in standard tuning without capo (string and fret are what the
    hand feels, so the habits carry over to drop D and capo approximately).
    """
    if weight == 0:
        return []
    standard = TUNINGS[Tuning.STANDARD]
    table = []
    for string in range(n_strings):
        row = []
        for fret in range(max_fret + 1):
            pitch = standard[min(string, len(standard) - 1)] + fret
            playable = [s for s in range(len(standard)) if 0 <= pitch - standard[s] <= MAX_FRET]
            seen = counts.get(pitch, [0] * len(standard))
            total = sum(seen[s] for s in playable) + PRIOR_SMOOTHING * len(playable)
            share = (seen[string] + PRIOR_SMOOTHING) / total if string < len(seen) else 1.0
            row.append(-weight * math.log(share))
        table.append(row)
    return table
