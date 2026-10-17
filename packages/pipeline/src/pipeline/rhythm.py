"""Turn timed notes into notated rhythm: beat positions, per-beat grid, downbeat and key."""

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import pairwise
from typing import Literal

import numpy as np
import numpy.typing as npt

BEATS_PER_BAR = 4  # v1 assumes 4/4
STRAIGHT, TRIPLET = 4, 3  # grid divisions per beat: sixteenths or eighth-note triplets
# Simpler grids are tried first (quarters, then eighths): human timing drifts by tens of ms,
# and at fast tempos that is enough to push an eighth note onto a sixteenth position.
SIMPLE_GRIDS = (1, 2)
SNAP_TOLERANCE_S = 0.045  # how far a note may be from a simpler grid and still use it...
MAX_TOLERANCE_BEATS = 0.125  # ...but never more than a 32nd note, so slow music keeps detail
# Strummed or rolled chords: strings hit a few ms apart are one chord, written at the first.
ROLL_GAP_S = 0.035  # consecutive onsets this close belong to the same roll...
ROLL_MAX_SPAN_S = 0.1  # ...up to this long in total (a 32nd note is 48 ms even at 157 bpm)
StrumDirection = Literal["down", "up"]  # down: the low strings first (pitch rises over time)
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
class StrumParams:
    """When notes a little apart are one strummed chord (tests/tuning/tune_strums.py).

    A strum sweeps the strings one after another: on guitar recordings the first and last
    string are a median 110 ms and up to 200 ms apart, about a sixteenth note. Notes that close
    are also how fast melody runs look, so a wider gap only joins a strum while the earlier
    string still rings and the pitch keeps moving the same way (low to high on a downstroke).
    """

    gap_s: float = 0.12  # consecutive strings at most this far apart...
    span_s: float = 0.2  # ...the whole strum at most this long
    min_ring_s: float = 0.1  # the previous string still sounds this long after the next starts
    min_spread_s: float = 0.02  # a chord spread less than this was struck at once (no strum)
    jitter_s: float = 0.008  # onsets this close say nothing about the strum's direction


@dataclass(frozen=True)
class Strum:
    onset_beats: Fraction
    direction: StrumDirection


@dataclass(frozen=True)
class Rhythm:
    notes: list[GridNote]
    pickup_beats: int  # beats before the first full bar (0 = no pickup)
    beat_times_s: list[float]  # time of beat 0, 1, 2, ... in the shifted numbering
    strums: list[Strum] = field(default_factory=list)  # chords played as a strum


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


def quantize(
    notes: Sequence[TimedNote],
    beat_times: Sequence[float],
    strum: StrumParams | None = None,
    downbeat_weights: Sequence[float] = (),
) -> Rhythm:
    """Snap notes to a per-beat grid, pick the downbeat and number beats from the first bar.

    `strum=None` keeps only the tight roll rule (ROLL_GAP_S); StrumParams also joins strums.
    `downbeat_weights`, one per beat, say how likely each beat starts a bar; bars start on the
    beat (mod 4) with the most weight. Without them, where the loudest on-beat notes land.
    """
    if not notes:
        return Rhythm(notes=[], pickup_beats=0, beat_times_s=[float(t) for t in beat_times])
    beat_map = BeatMap(beat_times)
    groups = strum_groups(notes, strum) if strum else []
    starts = roll_starts([n.onset_s for n in notes])
    for group in groups:
        for i in group:
            starts[i] = notes[group[0]].onset_s
    onsets = [beat_map.beat_at(t) for t in starts]
    grids = _grid_per_beat(onsets, beat_map)

    snapped = [_snap(b, grids) for b in onsets]
    ends = [_snap_end(beat_map.beat_at(n.offset_s), grids, beat_map) for n in notes]
    durations = _durations(notes, snapped, ends, grids)
    merged = _merge_duplicates(notes, snapped, durations)

    origin = math.floor(min(onset for _, onset, _ in merged))
    downbeat = (
        max(range(BEATS_PER_BAR), key=lambda p: sum(downbeat_weights[p::BEATS_PER_BAR]))
        if len(downbeat_weights)
        else _downbeat_phase([(n, onset) for n, onset, _ in merged])
    )
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
    strums = []
    if strum:
        for group in groups:
            direction = strum_direction([notes[i] for i in group], strum)
            if direction:
                strums.append(Strum(snapped[group[0]] - origin, direction))
    return Rhythm(
        notes=grid_notes,
        pickup_beats=(downbeat - origin) % BEATS_PER_BAR,
        beat_times_s=[round(beat_map.time_at(origin + b), 4) for b in range(last_beat + 1)],
        strums=sorted({s.onset_beats: s for s in strums}.values(), key=lambda s: s.onset_beats),
    )


def strum_groups(notes: Sequence[TimedNote], params: StrumParams) -> list[list[int]]:
    """Indices of notes played as one chord, each group in time order (singles included).

    A note joins the chord before it if it is within the tight roll window (ROLL_GAP_S), or
    if it continues a strum: close enough (params.gap_s, params.span_s), a pitch the chord
    doesn't have yet, the previous string still ringing, and the same direction so far.
    """
    order = sorted(range(len(notes)), key=lambda i: (notes[i].onset_s, notes[i].pitch))
    groups: list[list[int]] = []
    direction = 0  # +1 rising (downstroke), -1 falling (upstroke), 0 not known yet
    for i in order:
        note = notes[i]
        group = groups[-1] if groups else None
        if group is not None:
            first, previous = notes[group[0]], notes[group[-1]]
            gap = note.onset_s - previous.onset_s
            span = note.onset_s - first.onset_s
            tight = gap <= ROLL_GAP_S and span <= ROLL_MAX_SPAN_S
            step = (note.pitch > previous.pitch) - (note.pitch < previous.pitch)
            steers = gap > params.jitter_s and step != 0
            strummed = (
                gap <= params.gap_s
                and span <= params.span_s
                and note.pitch not in {notes[j].pitch for j in group}
                and previous.offset_s >= note.onset_s + params.min_ring_s
                and not (steers and direction and step != direction)
            )
            if tight or strummed:
                group.append(i)
                if steers and not direction:
                    direction = step
                continue
        groups.append([i])
        direction = 0
    return groups


def strum_direction(chord: Sequence[TimedNote], params: StrumParams) -> StrumDirection | None:
    """Down (low strings first) or up, if the chord's notes were spread out in time."""
    if len(chord) < 2 or chord[-1].onset_s - chord[0].onset_s < params.min_spread_s:
        return None
    rising = falling = 0
    for a, b in pairwise(chord):
        if b.onset_s - a.onset_s > params.jitter_s:
            rising += b.pitch > a.pitch
            falling += b.pitch < a.pitch
    if rising == falling:
        return None
    return "down" if rising > falling else "up"


def roll_starts(onsets_s: Sequence[float]) -> list[float]:
    """For each onset, the start of the strum/roll it belongs to (itself if it stands alone).

    Onsets chained by gaps of at most ROLL_GAP_S, spanning at most ROLL_MAX_SPAN_S, are one
    chord. Without this, the later strings of a strum snap to the next sixteenth.
    """
    order = sorted(range(len(onsets_s)), key=lambda i: onsets_s[i])
    starts = list(onsets_s)
    roll_start = previous = None
    for i in order:
        t = onsets_s[i]
        if (
            roll_start is None
            or previous is None
            or t - previous > ROLL_GAP_S
            or t - roll_start > ROLL_MAX_SPAN_S
        ):
            roll_start = t
        starts[i] = roll_start
        previous = t
    return starts


def tempo_from_beats(beat_times: Sequence[float]) -> float:
    """Tempo for the score: from the median beat interval (robust to a few odd beats)."""
    return float(60.0 / np.median(np.diff(np.asarray(beat_times))))


def beat_frames_to_times(frames: npt.NDArray[np.int64], fps: float) -> list[float]:
    return [float(f) / fps for f in frames]


def _grid_per_beat(onsets: Sequence[float], beat_map: BeatMap) -> dict[int, int]:
    """Divisions per beat, chosen from the onsets inside it: the simplest grid that fits."""
    by_beat: dict[int, list[float]] = {}
    for b in onsets:
        by_beat.setdefault(math.floor(b), []).append(b - math.floor(b))
    grids = {}
    for beat, fracs in by_beat.items():
        simple = _simplest_fitting(fracs, _tolerance(beat_map, beat))
        if simple is not None:
            grids[beat] = simple
            continue
        straight, triplet = _grid_error(fracs, STRAIGHT), _grid_error(fracs, TRIPLET)
        use_triplet = (
            len(fracs) >= MIN_ONSETS_FOR_TRIPLET and triplet < TRIPLET_ERROR_RATIO * straight
        )
        grids[beat] = TRIPLET if use_triplet else STRAIGHT
    return grids


def _grid_error(fracs: Sequence[float], divisions: int) -> float:
    return sum(_distance(f, divisions) for f in fracs)


def _distance(frac: float, divisions: int) -> float:
    """Beats from a position within a beat to the nearest line of a grid."""
    return abs(frac * divisions - round(frac * divisions)) / divisions


def _simplest_fitting(fracs: Sequence[float], tolerance: float) -> int | None:
    return next((d for d in SIMPLE_GRIDS if all(_distance(f, d) <= tolerance for f in fracs)), None)


def _tolerance(beat_map: BeatMap, beat: int) -> float:
    """SNAP_TOLERANCE_S in beats at this beat's local tempo, capped at MAX_TOLERANCE_BEATS."""
    beat_s = beat_map.time_at(beat + 1) - beat_map.time_at(beat)
    return min(MAX_TOLERANCE_BEATS, SNAP_TOLERANCE_S / beat_s) if beat_s > 0 else 0.0


def _snap(beat: float, grids: dict[int, int]) -> Fraction:
    whole = math.floor(beat)
    divisions = grids.get(whole, STRAIGHT)
    return whole + Fraction(round((beat - whole) * divisions), divisions)


def _snap_end(beat: float, grids: dict[int, int], beat_map: BeatMap) -> Fraction:
    """Note ends use their beat's grid; in a beat with no onsets, the simplest one that fits."""
    whole = math.floor(beat)
    if whole not in grids:
        simple = _simplest_fitting([beat - whole], _tolerance(beat_map, whole))
        grids = {whole: simple or STRAIGHT}
    return _snap(beat, grids)


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
