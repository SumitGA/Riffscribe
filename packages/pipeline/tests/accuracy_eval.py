"""Score pipeline output against ground truth with mir_eval (the accuracy suite)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mir_eval
import numpy as np
import numpy.typing as npt

from pipeline.config import Instrument, PipelineConfig
from pipeline.runner import run_pipeline
from pipeline.score import Score
from pipeline.stages import default_stages
from pipeline.stages.normalize import NormalizedAudio
from pipeline.stages.quantize import QuantizedScore
from pipeline.stages.tab import TabFile, Tablature
from pipeline.stages.transcribe import NoteEvents, NoteList

FIXTURES = Path(__file__).parent / "fixtures"
SUITES = {"guitarset": Instrument.GUITAR, "piano_synth": Instrument.PIANO}
TEMPO_TOLERANCE = 0.04  # a tempo within 4 % counts as right


@dataclass(frozen=True)
class Clip:
    name: str
    audio: Path
    truth: dict[str, Any]
    instrument: Instrument


def clips() -> list[Clip]:
    found = []
    for suite, instrument in SUITES.items():
        for truth_path in sorted((FIXTURES / suite).glob("*.truth.json")):
            audio = truth_path.with_name(truth_path.name.replace(".truth.json", ".flac"))
            truth = json.loads(truth_path.read_text())
            found.append(Clip(truth["track"], audio, truth, instrument))
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
    ref_beats = mir_eval.beat.trim_beats(np.asarray(clip.truth["beats_s"], dtype=float))
    est_beats = mir_eval.beat.trim_beats(np.asarray(score.beat_times_s, dtype=float) + shift)
    tempo_error = abs(score.tempo_bpm / clip.truth["tempo_bpm"] - 1)

    metrics = {
        "note_f1": f1,
        "note_precision": precision,
        "note_recall": recall,
        "note_f1_with_offsets": f1_offset,
        "beat_f": mir_eval.beat.f_measure(ref_beats, est_beats),
        "tempo_correct": float(tempo_error <= TEMPO_TOLERANCE),
    }
    if clip.instrument is Instrument.GUITAR:
        tab_path = workdir / result.output(Tablature).tab.path
        tab = TabFile.model_validate_json(tab_path.read_text())
        metrics["tab_string_accuracy"] = _string_accuracy(clip, score, tab, shift)
    if clip.name.endswith("_comp"):  # in solos the chords are the band's, not the guitar's
        estimated = [(c.onset_s + shift, c.offset_s + shift, c.harte()) for c in score.chords]
        metrics.update(chord_accuracy(clip.truth["chords"], estimated))
    return {name: round(float(value), 4) for name, value in metrics.items()}


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
