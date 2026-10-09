"""Chord names from Basic Pitch note activations: beat-synchronous chroma, templates, Viterbi.

Each beat (or part of a beat) gets a 12-bin chroma: the frame activations folded onto pitch
classes and averaged over the span, plus a bass chroma from the low strings only. Every chord in
the vocabulary is scored by the cosine between its template and the chroma, with a bonus when its
root is in the bass. Viterbi then picks the best chord sequence, with a penalty for changing chord
so one stray beat doesn't flip it. Settings were grid-searched on GuitarSet comp excerpts that
are not test clips (tests/tuning/tune_chords.py).
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pipeline.basic_pitch import MIDI_OFFSET
from pipeline.score import ChordQuality

INTERVALS: dict[ChordQuality, tuple[int, ...]] = {
    "maj": (0, 4, 7),
    "min": (0, 3, 7),
    "7": (0, 4, 7, 10),
    "maj7": (0, 4, 7, 11),
    "min7": (0, 3, 7, 10),
}


@dataclass(frozen=True)
class ChordParams:
    """Defaults from tests/tuning/tune_chords.py: major/minor accuracy 0.761 on the 24 tuning
    comp clips (the top settings all scored 0.75-0.76), vs 0.55 for plain triads per beat;
    0.89 on the 3 held-out test clips."""

    qualities: tuple[ChordQuality, ...] = ("maj", "min", "7", "maj7", "min7")
    subdivisions: int = 2  # chord spans per beat, so a change on the "and" is caught
    bass_max_pitch: int = 52  # E3: the lowest two strings' first frets carry the bass
    power: float = 3.0  # activations ** power before folding, so confident notes dominate
    bass_weight: float = 0.3  # bonus for a chord whose root is the bass note
    stay_probability: float = 0.95  # Viterbi: chance the chord carries on into the next span
    min_energy: float = 0.02  # summed activation below which a span has no chord


DEFAULT = ChordParams()
_SCALE = 10.0  # template scores -> log-likelihood-like scores for Viterbi


@dataclass(frozen=True)
class ChordSpan:
    start_s: float
    end_s: float
    root: int  # pitch class, 0 = C
    quality: ChordQuality


def recognize_chords(
    frames: npt.NDArray[np.floating],
    times: npt.NDArray[np.float64],
    beat_times: Sequence[float],
    params: ChordParams = DEFAULT,
) -> list[list[ChordSpan | None]]:
    """The chord of each span between consecutive beats, `params.subdivisions` per beat.

    `frames` are (n_frames, 88) activations (bin 0 = A0) at `times` seconds. Returns one list per
    beat interval, each with a chord or None (no chord) per subdivision.
    """
    edges = _edges(beat_times, params.subdivisions)
    if len(edges) < 2 or len(frames) == 0:
        return [[None] * params.subdivisions for _ in range(max(len(beat_times) - 1, 0))]
    chroma, bass = _span_chroma(np.asarray(frames, np.float64), times, edges, params)
    labels, templates, roots = _vocabulary(params.qualities)

    norm = np.linalg.norm(chroma, axis=1, keepdims=True)
    scores = chroma / np.maximum(norm, 1e-9) @ templates.T
    bass_share = bass / np.maximum(bass.sum(axis=1, keepdims=True), 1e-9)
    scores += params.bass_weight * bass_share[:, roots]
    silent = chroma.sum(axis=1) < params.min_energy
    # The last state is "no chord": certain in silent spans, impossible elsewhere.
    scores = np.hstack(
        [np.where(silent[:, None], -np.inf, scores), np.where(silent, 1.0, -np.inf)[:, None]]
    )
    path = _viterbi(_SCALE * scores, params.stay_probability)

    spans: list[ChordSpan | None] = []
    for i, state in enumerate(path):
        if state == len(labels):
            spans.append(None)
        else:
            root, quality = labels[state]
            spans.append(ChordSpan(float(edges[i]), float(edges[i + 1]), root, quality))
    sub = params.subdivisions
    return [spans[i : i + sub] for i in range(0, len(spans), sub)]


def _edges(beat_times: Sequence[float], subdivisions: int) -> npt.NDArray[np.float64]:
    beats = np.asarray(beat_times, np.float64)
    if beats.size < 2:
        return beats
    steps = np.arange(subdivisions) / subdivisions
    inner = (beats[:-1, None] + np.diff(beats)[:, None] * steps).ravel()
    return np.append(inner, beats[-1])


def _span_chroma(
    frames: npt.NDArray[np.float64],
    times: npt.NDArray[np.float64],
    edges: npt.NDArray[np.float64],
    params: ChordParams,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Mean chroma and bass chroma per span between consecutive edges, (n_spans, 12) each."""
    activations = frames**params.power
    pitch_class = (np.arange(frames.shape[1]) + MIDI_OFFSET) % 12
    folded = np.zeros((len(frames), 12))
    bass_folded = np.zeros((len(frames), 12))
    n_bass = params.bass_max_pitch - MIDI_OFFSET + 1
    for pc in range(12):
        folded[:, pc] = activations[:, pitch_class == pc].sum(axis=1)
        bass_folded[:, pc] = activations[:, :n_bass][:, pitch_class[:n_bass] == pc].sum(axis=1)

    starts = np.searchsorted(times, edges[:-1])
    ends = np.maximum(np.searchsorted(times, edges[1:]), starts + 1)
    starts, ends = np.minimum(starts, len(frames) - 1), np.minimum(ends, len(frames))
    chroma = np.array([folded[s:e].mean(axis=0) for s, e in zip(starts, ends, strict=True)])
    bass = np.array([bass_folded[s:e].mean(axis=0) for s, e in zip(starts, ends, strict=True)])
    return chroma, bass


def _vocabulary(
    qualities: Sequence[ChordQuality],
) -> tuple[list[tuple[int, ChordQuality]], npt.NDArray[np.float64], npt.NDArray[np.int64]]:
    labels = [(root, quality) for root in range(12) for quality in qualities]
    templates = np.zeros((len(labels), 12))
    for i, (root, quality) in enumerate(labels):
        templates[i, [(root + step) % 12 for step in INTERVALS[quality]]] = 1.0
    templates /= np.linalg.norm(templates, axis=1, keepdims=True)
    return labels, templates, np.array([root for root, _ in labels])


def _viterbi(scores: npt.NDArray[np.float64], stay: float) -> list[int]:
    """Best state path when each step either stays (log stay) or moves to any other state."""
    n_steps, n_states = scores.shape
    log_stay, log_move = np.log(stay), np.log((1 - stay) / (n_states - 1))
    best = scores[0].copy()
    back = np.zeros((n_steps, n_states), np.int64)
    for t in range(1, n_steps):
        leader = int(np.argmax(best))
        stayed = best + log_stay
        moved = best[leader] + log_move
        back[t] = np.where(stayed >= moved, np.arange(n_states), leader)
        best = np.maximum(stayed, moved) + scores[t]
    path = [int(np.argmax(best))]
    for t in range(n_steps - 1, 0, -1):
        path.append(int(back[t, path[-1]]))
    return path[::-1]
