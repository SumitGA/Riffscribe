"""Turn timed notes into notated rhythm: beat positions, per-beat grid, downbeat and key."""

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

import numpy as np
import numpy.typing as npt

BEATS_PER_BAR = 4  # v1 assumes 4/4
STRAIGHT, TRIPLET = 4, 3  # grid divisions per beat: sixteenths or eighth-note triplets
# A beat is notated as triplets only if that fits its onsets clearly better than sixteenths.
TRIPLET_ERROR_RATIO = 0.5
MIN_ONSETS_FOR_TRIPLET = 2

Mode = Literal["major", "minor"]


@dataclass(frozen=True)
class TimedNote:
    onset_s: float
    offset_s: float
    pitch: int
    velocity: int


@dataclass(frozen=True)
class GridNote:
    onset_s: float
    offset_s: float
    pitch: int
    velocity: int
    onset_beats: Fraction  # from the start of the first (possibly partial) bar
    duration_beats: Fraction


@dataclass(frozen=True)
class Rhythm:
    notes: list[GridNote]
    pickup_beats: int  # beats before the first full bar (0 = no pickup)
    beat_times_s: list[float]  # time of beat 0, 1, 2, ... in the shifted numbering


@dataclass(frozen=True)
class Key:
    tonic: int  # pitch class, 0 = C
    mode: Mode
    fifths: int  # key signature: sharps > 0, flats < 0


class BeatMap:
    """Seconds <-> fractional beat numbers, linear between tracked beats and beyond them."""

    def __init__(self, beat_times: Sequence[float]) -> None:
        if len(beat_times) < 2:
            raise ValueError("need at least two beats")
        self.times = np.asarray(beat_times, dtype=np.float64)

    def beat_at(self, t: float) -> float:
        times = self.times
        if t <= times[0]:
            return float((t - times[0]) / (times[1] - times[0]))
        if t >= times[-1]:
            return float(times.size - 1 + (t - times[-1]) / (times[-1] - times[-2]))
        return float(np.interp(t, times, np.arange(times.size)))

    def time_at(self, beat: float) -> float:
        times, last = self.times, self.times.size - 1
        if beat <= 0:
            return float(times[0] + beat * (times[1] - times[0]))
        if beat >= last:
            return float(times[-1] + (beat - last) * (times[-1] - times[-2]))
        return float(np.interp(beat, np.arange(times.size), times))


def quantize(notes: Sequence[TimedNote], beat_times: Sequence[float]) -> Rhythm:
    """Snap notes to a per-beat grid, pick the downbeat and number beats from the first bar."""
    if not notes:
        return Rhythm(notes=[], pickup_beats=0, beat_times_s=[float(t) for t in beat_times])
    beat_map = BeatMap(beat_times)
    onsets = [beat_map.beat_at(n.onset_s) for n in notes]
    grids = _grid_per_beat(onsets)

    snapped = [_snap(b, grids) for b in onsets]
    ends = [_snap(beat_map.beat_at(n.offset_s), grids) for n in notes]
    durations = _durations(notes, snapped, ends, grids)
    merged = _merge_duplicates(notes, snapped, durations)

    origin = math.floor(min(onset for _, onset, _ in merged))
    downbeat = _downbeat_phase([(n, onset) for n, onset, _ in merged])
    grid_notes = sorted(
        (
            GridNote(
                onset_s=n.onset_s,
                offset_s=n.offset_s,
                pitch=n.pitch,
                velocity=n.velocity,
                onset_beats=onset - origin,
                duration_beats=duration,
            )
            for n, onset, duration in merged
        ),
        key=lambda g: (g.onset_beats, g.pitch),
    )
    last_beat = math.ceil(max(g.onset_beats + g.duration_beats for g in grid_notes))
    return Rhythm(
        notes=grid_notes,
        pickup_beats=(downbeat - origin) % BEATS_PER_BAR,
        beat_times_s=[round(beat_map.time_at(origin + b), 4) for b in range(last_beat + 1)],
    )


def tempo_from_beats(beat_times: Sequence[float]) -> float:
    """Tempo for the score: from the median beat interval (robust to a few odd beats)."""
    return float(60.0 / np.median(np.diff(np.asarray(beat_times))))


def beat_frames_to_times(frames: npt.NDArray[np.int64], fps: float) -> list[float]:
    return [float(f) / fps for f in frames]


def _grid_per_beat(onsets: Sequence[float]) -> dict[int, int]:
    """Divisions per beat, chosen per beat from the onsets that fall inside it."""
    by_beat: dict[int, list[float]] = {}
    for b in onsets:
        by_beat.setdefault(math.floor(b), []).append(b - math.floor(b))
    grids = {}
    for beat, fracs in by_beat.items():
        straight, triplet = _grid_error(fracs, STRAIGHT), _grid_error(fracs, TRIPLET)
        use_triplet = (
            len(fracs) >= MIN_ONSETS_FOR_TRIPLET and triplet < TRIPLET_ERROR_RATIO * straight
        )
        grids[beat] = TRIPLET if use_triplet else STRAIGHT
    return grids


def _grid_error(fracs: Sequence[float], divisions: int) -> float:
    return sum(abs(f * divisions - round(f * divisions)) / divisions for f in fracs)


def _snap(beat: float, grids: dict[int, int]) -> Fraction:
    whole = math.floor(beat)
    divisions = grids.get(whole, STRAIGHT)
    return whole + Fraction(round((beat - whole) * divisions), divisions)


def _durations(
    notes: Sequence[TimedNote],
    onsets: Sequence[Fraction],
    ends: Sequence[Fraction],
    grids: dict[int, int],
) -> list[Fraction]:
    """At least one grid step long, and never overlapping the next note of the same pitch."""
    starts_by_pitch: dict[int, list[Fraction]] = {}
    for n, onset in zip(notes, onsets, strict=True):
        starts_by_pitch.setdefault(n.pitch, []).append(onset)
    for starts in starts_by_pitch.values():
        starts.sort()

    durations = []
    for n, onset, end in zip(notes, onsets, ends, strict=True):
        step = Fraction(1, grids.get(math.floor(onset), STRAIGHT))
        duration = max(end - onset, step)
        starts = starts_by_pitch[n.pitch]
        later = bisect_right(starts, onset)
        if later < len(starts):
            duration = min(duration, max(starts[later] - onset, step))
        durations.append(duration)
    return durations


def _merge_duplicates(
    notes: Sequence[TimedNote], onsets: Sequence[Fraction], durations: Sequence[Fraction]
) -> list[tuple[TimedNote, Fraction, Fraction]]:
    """Two notes of one pitch snapped to the same onset become one (the louder, longer one)."""
    best: dict[tuple[int, Fraction], tuple[TimedNote, Fraction, Fraction]] = {}
    for n, onset, duration in zip(notes, onsets, durations, strict=True):
        kept = best.get((n.pitch, onset))
        if kept is None:
            best[(n.pitch, onset)] = (n, onset, duration)
        else:
            louder = n if n.velocity > kept[0].velocity else kept[0]
            best[(n.pitch, onset)] = (louder, onset, max(duration, kept[2]))
    return list(best.values())


def _downbeat_phase(notes: Sequence[tuple[TimedNote, Fraction]]) -> int:
    """Which beat (mod 4) starts bars: the one where the loudest on-beat notes land."""
    weight = [0.0] * BEATS_PER_BAR
    for n, onset in notes:
        if onset.denominator == 1:
            weight[int(onset) % BEATS_PER_BAR] += n.velocity
    return int(np.argmax(weight))


# Krumhansl-Kessler key profiles (probe-tone ratings) for C major and C minor.
_PROFILES: tuple[tuple[Mode, npt.NDArray[np.float64]], ...] = (
    ("major", np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])),
    ("minor", np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])),
)
# Key signature of each major tonic; F#/Gb is written as F# (6 sharps).
_MAJOR_FIFTHS = {0: 0, 1: -5, 2: 2, 3: -3, 4: 4, 5: -1, 6: 6, 7: 1, 8: -4, 9: 3, 10: -2, 11: 5}


def estimate_key(notes: Sequence[GridNote]) -> Key:
    """Krumhansl-Schmuckler: correlate the duration-weighted pitch-class histogram with each key."""
    histogram = np.zeros(12)
    for n in notes:
        histogram[n.pitch % 12] += float(n.duration_beats)
    if np.count_nonzero(histogram) < 2:
        return Key(tonic=0, mode="major", fifths=0)
    best_score, best_tonic = -np.inf, 0
    best_mode: Mode = "major"
    for tonic in range(12):
        for mode, profile in _PROFILES:
            score = float(np.corrcoef(histogram, np.roll(profile, tonic))[0, 1])
            if score > best_score:
                best_score, best_tonic, best_mode = score, tonic, mode
    relative_major = best_tonic if best_mode == "major" else (best_tonic + 3) % 12
    return Key(tonic=best_tonic, mode=best_mode, fifths=_MAJOR_FIFTHS[relative_major])
