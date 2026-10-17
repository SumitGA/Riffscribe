"""Score pipeline output against ground truth with mir_eval (the accuracy suite)."""

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import mir_eval
import numpy as np
import numpy.typing as npt

from pipeline.config import Instrument, PipelineConfig
from pipeline.rhythm import BEATS_PER_BAR, BeatMap
from pipeline.runner import run_pipeline
from pipeline.score import Score
from pipeline.stages import default_stages
from pipeline.stages.normalize import NormalizedAudio
from pipeline.stages.quantize import QuantizedScore
from pipeline.stages.tab import TabFile, Tablature
from pipeline.stages.transcribe import NoteEvents, NoteList

FIXTURES = Path(__file__).parent / "fixtures"
# guitar_techs: guitar no model we use trained on (Basic Pitch trained on most of GuitarSet,
# TD-11), so its numbers are the honest ones; it has no beat or chord annotations.
SUITES = {
    "guitarset": Instrument.GUITAR,
    "guitar_techs": Instrument.GUITAR,
    "piano_synth": Instrument.PIANO,
}
TEMPO_TOLERANCE = 0.04  # a tempo within 4 % counts as right


@dataclass(frozen=True)
class Clip:
    name: str
    audio: Path
    truth: dict[str, Any]
    instrument: Instrument
    suite: str


def clips() -> list[Clip]:
    found = []
    for suite, instrument in SUITES.items():
        for truth_path in sorted((FIXTURES / suite).glob("*.truth.json")):
            audio = truth_path.with_name(truth_path.name.replace(".truth.json", ".flac"))
            truth = json.loads(truth_path.read_text())
            found.append(Clip(truth["track"], audio, truth, instrument, suite))
    return found


def evaluate(clip: Clip, workdir: Path) -> dict[str, float]:
    """Run the whole pipeline on the clip and score it. All metrics are 0..1, higher is better."""
    cfg = PipelineConfig(instrument=clip.instrument)
    result = run_pipeline(clip.audio, workdir, cfg, default_stages())
    shift = result.output(NormalizedAudio).trim_start_s  # pipeline times start after trimming
    notes = NoteList.model_validate_json(
        (workdir / result.output(NoteEvents).notes.path).read_text()
    ).notes
    score = Score.model_validate_json(
        (workdir / result.output(QuantizedScore).score.path).read_text()
    )

    ref = clip.truth["notes"]
    ref_intervals = _intervals([(n["onset_s"], n["offset_s"]) for n in ref])
    ref_hz = _hz([n["pitch"] for n in ref])
    est_intervals = _intervals([(n.onset_s + shift, n.offset_s + shift) for n in notes])
    est_hz = _hz([n.pitch for n in notes])

    precision, recall, f1, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ref_intervals, ref_hz, est_intervals, est_hz, offset_ratio=None
    )
    _, _, f1_offset, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ref_intervals, ref_hz, est_intervals, est_hz
    )
    metrics = {
        "note_f1": f1,
        "note_precision": precision,
        "note_recall": recall,
        "note_f1_with_offsets": f1_offset,
    }
    if clip.truth.get("beats_s"):
        ref_beats = mir_eval.beat.trim_beats(np.asarray(clip.truth["beats_s"], dtype=float))
        est_beats = mir_eval.beat.trim_beats(np.asarray(score.beat_times_s, dtype=float) + shift)
        tempo_error = abs(score.tempo_bpm / clip.truth["tempo_bpm"] - 1)
        metrics["beat_f"] = mir_eval.beat.f_measure(ref_beats, est_beats)
        metrics["tempo_correct"] = float(tempo_error <= TEMPO_TOLERANCE)
        est_bars = np.asarray(score.beat_times_s[score.pickup_beats :: BEATS_PER_BAR]) + shift
        metrics["downbeat_f"] = mir_eval.beat.f_measure(
            np.asarray(clip.truth["downbeats_s"], dtype=float), est_bars
        )
        metrics.update(bar_positions(clip.truth, score, shift))
    if clip.instrument is Instrument.GUITAR:
        tab_path = workdir / result.output(Tablature).tab.path
        tab = TabFile.model_validate_json(tab_path.read_text())
        metrics["tab_string_accuracy"] = _string_accuracy(clip, score, tab, shift)
    metrics.update(
        grid_grouping(
            clip.truth["notes"],
            [(n.onset_s + shift, n.offset_s + shift, n.pitch, n.onset_beats) for n in score.notes],
        )
    )
    if "chords" in clip.truth and clip.name.endswith("_comp"):  # solos: the band's chords
        estimated = [(c.onset_s + shift, c.offset_s + shift, c.harte()) for c in score.chords]
        metrics.update(chord_accuracy(clip.truth["chords"], estimated))
    return {name: round(float(value), 4) for name, value in metrics.items()}


# The player's strums: annotated onsets chained this closely, each pitch once (a strum hits each
# string once), at least STRUM_MIN_NOTES of them.
TRUTH_STRUM_GAP_S = 0.1
TRUTH_STRUM_SPAN_S = 0.25
STRUM_MIN_NOTES = 3
SEPARATE_S = 0.1  # annotated events this far apart are separate notes or chords


POSITION_TOLERANCE = 1 / 8  # beats: half a sixteenth either way


def bar_positions(truth: dict[str, Any], score: Score, shift: float) -> dict[str, float]:
    """Whether notes are written where they were played, judged against the annotated beats.

    `notes_on_beat`: of the notes we found, the share written at the right place within the beat
    (on it, on the "and", ...). `notes_in_bar`: the share at the right place within the bar
    (which beat, and where in it). A note written a beat or half a beat off scores 0 here, even
    if its time in seconds is right.
    """
    ref = truth["notes"]
    ref_beats = BeatMap(truth["beats_s"])
    first_bar = round(ref_beats.beat_at(truth["downbeats_s"][0]))
    pairs = mir_eval.transcription.match_notes(
        _intervals([(n["onset_s"], n["offset_s"]) for n in ref]),
        _hz([n["pitch"] for n in ref]),
        _intervals([(n.onset_s + shift, n.offset_s + shift) for n in score.notes]),
        _hz([n.pitch for n in score.notes]),
        offset_ratio=None,
    )
    if not pairs:
        return {}

    def off(a: float, b: float, cycle: float) -> bool:
        d = abs(a - b) % cycle
        return min(d, cycle - d) > POSITION_TOLERANCE

    on_beat = in_bar = 0
    for r, e in pairs:
        truth_pos = ref_beats.beat_at(ref[r]["onset_s"]) - first_bar
        written = float(score.notes[e].onset_beats) - score.pickup_beats
        on_beat += not off(truth_pos, written, 1)
        in_bar += not off(truth_pos, written, BEATS_PER_BAR)
    return {"notes_on_beat": on_beat / len(pairs), "notes_in_bar": in_bar / len(pairs)}


def grid_grouping(
    ref: list[dict[str, Any]], est: list[tuple[float, float, int, Fraction]]
) -> dict[str, float]:
    """Whether the score keeps the player's chords together and their separate notes apart.

    Note F1 is scored on times in seconds, so it can't see this: a strum written as a run of
    sixteenths still has every note at the right time. Here the score's grid positions count.
    `chords_whole`: of the annotated strums whose notes we found (2+), the share written at one
    grid position. `notes_apart`: of neighbouring annotated events at least SEPARATE_S apart
    (both found), the share that don't share a grid position.
    """
    events: list[list[int]] = []
    for i in sorted(range(len(ref)), key=lambda i: ref[i]["onset_s"]):
        onset = ref[i]["onset_s"]
        if (
            events
            and onset - ref[events[-1][-1]]["onset_s"] <= TRUTH_STRUM_GAP_S
            and onset - ref[events[-1][0]]["onset_s"] <= TRUTH_STRUM_SPAN_S
            and ref[i]["pitch"] not in {ref[j]["pitch"] for j in events[-1]}  # once per string
        ):
            events[-1].append(i)
        else:
            events.append([i])
    pairs = mir_eval.transcription.match_notes(
        _intervals([(n["onset_s"], n["offset_s"]) for n in ref]),
        _hz([n["pitch"] for n in ref]),
        _intervals([(on, off) for on, off, _, _ in est]),
        _hz([p for _, _, p, _ in est]),
        offset_ratio=None,
    )
    grid_of = {r: est[e][3] for r, e in pairs}
    positions = [{grid_of[i] for i in event if i in grid_of} for event in events]
    found = [sum(i in grid_of for i in event) for event in events]

    strums = [
        p
        for event, p, n in zip(events, positions, found, strict=True)
        if len(event) >= STRUM_MIN_NOTES and n >= 2
    ]
    neighbours = [
        not (positions[k] & positions[k + 1])
        for k in range(len(events) - 1)
        if positions[k]
        and positions[k + 1]
        and ref[events[k + 1][0]]["onset_s"] - ref[events[k][-1]]["onset_s"] >= SEPARATE_S
    ]
    metrics = {}
    if strums:
        metrics["chords_whole"] = sum(len(p) == 1 for p in strums) / len(strums)
    if neighbours:
        metrics["notes_apart"] = sum(neighbours) / len(neighbours)
    return metrics


def _string_accuracy(clip: Clip, score: Score, tab: TabFile, shift: float) -> float:
    """Of the notes we found (right pitch, onset within 50 ms), how many are on the right string."""
    string_of = {(n.onset_beats, n.pitch): n.string for n in tab.notes}
    placed = [
        (n, string_of[(n.onset_beats, n.pitch)])
        for n in score.notes
        if (n.onset_beats, n.pitch) in string_of
    ]
    if not placed:
        return 0.0
    ref = clip.truth["notes"]
    pairs = mir_eval.transcription.match_notes(
        _intervals([(n["onset_s"], n["offset_s"]) for n in ref]),
        _hz([n["pitch"] for n in ref]),
        _intervals([(n.onset_s + shift, n.offset_s + shift) for n, _ in placed]),
        _hz([n.pitch for n, _ in placed]),
        offset_ratio=None,
    )
    if not pairs:
        return 0.0
    correct = sum(1 for r, e in pairs if ref[r]["string"] == placed[e][1])
    return correct / len(pairs)


def chord_accuracy(
    truth: list[dict[str, Any]], estimated: list[tuple[float, float, str]]
) -> dict[str, float]:
    """Share of the annotated time with the right chord: root only, and major/minor triad.

    `estimated` is (onset_s, offset_s, Harte label) in the truth's time base; a gap between
    chords counts as "no chord" (N).
    """
    ref_intervals = _intervals([(c["onset_s"], c["offset_s"]) for c in truth])
    ref_labels = [c["label"] for c in truth]
    spans: list[tuple[float, float]] = []
    est_labels: list[str] = []
    for on, off, label in estimated:
        if spans and on > spans[-1][1]:
            spans.append((spans[-1][1], on))
            est_labels.append("N")
        spans.append((on, off))
        est_labels.append(label)
    est_intervals = _intervals(spans) if spans else ref_intervals[:1]
    est_intervals, est_labels = mir_eval.util.adjust_intervals(
        est_intervals, est_labels or ["N"], ref_intervals.min(), ref_intervals.max(), "N", "N"
    )
    merged, ref, est = mir_eval.util.merge_labeled_intervals(
        ref_intervals, ref_labels, est_intervals, est_labels
    )
    durations = mir_eval.util.intervals_to_durations(merged)
    return {
        "chord_root": mir_eval.chord.weighted_accuracy(mir_eval.chord.root(ref, est), durations),
        "chord_majmin": mir_eval.chord.weighted_accuracy(
            mir_eval.chord.majmin(ref, est), durations
        ),
    }


def _intervals(pairs: list[tuple[float, float]]) -> npt.NDArray[np.float64]:
    """(n, 2) onset/offset array; zero-length notes get 1 ms so mir_eval accepts them."""
    if not pairs:
        return np.zeros((0, 2))
    return np.array([(on, max(off, on + 1e-3)) for on, off in pairs], dtype=float)


def _hz(pitches: list[int]) -> npt.NDArray[np.float64]:
    return np.asarray(mir_eval.util.midi_to_hz(np.asarray(pitches, dtype=float)), dtype=float)
