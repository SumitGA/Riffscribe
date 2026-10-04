"""Guitar tab: a string and fret for every note (search runs in Rust, rust/tab.rs)."""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from pipeline import _tabcore
from pipeline.config import Tuning
from pipeline.score import ScoreNote

# Open-string pitches, lowest string first.
TUNINGS: dict[Tuning, tuple[int, ...]] = {
    Tuning.STANDARD: (40, 45, 50, 55, 59, 64),
    Tuning.DROP_D: (38, 45, 50, 55, 59, 64),
}
MAX_FRET = 24


@dataclass(frozen=True)
class TabPosition:
    string: int  # 1 = highest string, as written in tab
    fret: int  # relative to the capo


def assign_tab(
    notes: Sequence[ScoreNote], tuning: Tuning, capo: int
) -> dict[tuple[Fraction, int], TabPosition]:
    """Positions keyed by (onset_beats, pitch). Notes that can't be played are left out."""
    by_onset: dict[Fraction, list[int]] = {}
    for n in notes:
        by_onset.setdefault(n.onset_beats, []).append(n.pitch)
    onsets = sorted(by_onset)
    chords = [sorted(set(by_onset[o])) for o in onsets]
    strings = TUNINGS[tuning]
    open_strings = [p + capo for p in strings]

    placed = _tabcore.tab_positions(chords, open_strings, MAX_FRET - capo)
    positions = {}
    for onset, chord, chord_positions in zip(onsets, chords, placed, strict=True):
        for pitch, position in zip(chord, chord_positions, strict=True):
            if position is not None:
                string_index, fret = position
                positions[(onset, pitch)] = TabPosition(len(strings) - string_index, fret)
    return positions
