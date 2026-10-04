from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
import soundfile
from fixtures.basic_pitch.generate_clips import RATE, piano_note, place

from pipeline.config import Instrument, PipelineConfig
from pipeline.rhythm import BeatMap, GridNote, TimedNote, estimate_key, quantize
from pipeline.runner import run_pipeline
from pipeline.stages import default_stages
from pipeline.stages.quantize import QuantizedScore, Score

pytestmark = pytest.mark.unit

BPM = 100
SPB = 60 / BPM  # seconds per beat


def steady_beats(n: int, start: float = 0.5, spb: float = SPB) -> list[float]:
    return [start + i * spb for i in range(n)]


def note_at(
    beat: float,
    beats: list[float],
    length: float = 0.5,
    pitch: int = 60,
    vel: int = 80,
    jitter: float = 0.0,
) -> TimedNote:
    beat_map = BeatMap(beats)
    return TimedNote(beat_map.time_at(beat) + jitter, beat_map.time_at(beat + length), pitch, vel)


def onsets(rhythm_notes: list[GridNote]) -> list[Fraction]:
    return [n.onset_beats for n in rhythm_notes]


def test_jittered_sixteenths_snap_to_exact_fractions() -> None:
    beats = steady_beats(8)
    rng = np.random.default_rng(0)
    positions = [0, 0.25, 0.5, 0.75, 1, 1.5, 2, 2.75, 3]
    notes = [
        note_at(p, beats, 0.25, pitch=60 + i, jitter=float(rng.uniform(-0.015, 0.015)))
        for i, p in enumerate(positions)
    ]
    rhythm = quantize(notes, beats)

    assert onsets(rhythm.notes) == [Fraction(p).limit_denominator(4) for p in positions]


def test_triplets_are_recognised_only_with_enough_evidence() -> None:
    beats = steady_beats(8)
    notes = [note_at(b, beats, 1 / 3, pitch=60 + i) for i, b in enumerate([0, 1 / 3, 2 / 3, 1])]
    notes.append(note_at(2.33, beats, 0.5, pitch=70))  # lone off-grid note: stays straight
    rhythm = quantize(notes, beats)

    assert onsets(rhythm.notes) == [0, Fraction(1, 3), Fraction(2, 3), 1, Fraction(9, 4)]


def test_tempo_drift_still_lands_on_beats() -> None:
    times = np.cumsum([0.5, *np.linspace(0.65, 0.48, 15)])  # speeding up
    beats = [float(t) for t in times]
    notes = [TimedNote(t, t + 0.3, 60, 80) for t in beats[:12]]
    rhythm = quantize(notes, beats)

    assert onsets(rhythm.notes) == list(range(12))


def test_pickup_from_accented_downbeats() -> None:
    beats = steady_beats(16)
    # Quiet notes on beats 0-1, then loud notes every 4 beats starting at beat 2.
    notes = [note_at(b, beats, vel=110 if (b - 2) % 4 == 0 else 50) for b in range(14)]
    rhythm = quantize(notes, beats)

    assert rhythm.pickup_beats == 2


def test_durations_are_at_least_one_step_and_do_not_overlap_repeats() -> None:
    beats = steady_beats(8)
    notes = [
        TimedNote(beats[0], beats[0] + 0.01, 60, 80),  # very short
        TimedNote(beats[1], beats[4], 62, 80),  # held into...
        TimedNote(beats[2], beats[3], 62, 80),  # ...a repeat of the same pitch
    ]
    by_pitch = {(n.pitch, n.onset_beats): n.duration_beats for n in quantize(notes, beats).notes}

    assert by_pitch[(60, Fraction(0))] == Fraction(1, 4)
    assert by_pitch[(62, Fraction(1))] == 1
    assert by_pitch[(62, Fraction(2))] == 1


def test_notes_before_first_beat_are_numbered_from_zero() -> None:
    beats = steady_beats(8, start=2.0)
    notes = [TimedNote(2.0 - 2 * SPB, 2.0 - SPB, 60, 80), TimedNote(2.0, 2.5, 64, 80)]
    rhythm = quantize(notes, beats)

    assert onsets(rhythm.notes) == [0, 2]
    assert rhythm.beat_times_s[0] == pytest.approx(2.0 - 2 * SPB, abs=1e-3)


@pytest.mark.parametrize(
    ("pitches", "tonic", "mode", "fifths"),
    [
        ([60, 62, 64, 65, 67, 69, 71, 72, 60, 64, 67], 0, "major", 0),
        ([62, 64, 66, 67, 69, 71, 73, 74, 62, 66, 69], 2, "major", 2),
        ([57, 59, 60, 62, 64, 65, 68, 69, 57, 60, 64], 9, "minor", 0),
        ([65, 67, 69, 70, 72, 74, 76, 77, 65, 69, 72], 5, "major", -1),
    ],
    ids=["C-major", "D-major", "A-minor", "F-major"],
)
def test_key_estimation(pitches: list[int], tonic: int, mode: str, fifths: int) -> None:
    notes = [GridNote(0, 0, p, 80, Fraction(i), Fraction(1)) for i, p in enumerate(pitches)]
    # Weight the tonic triad (last three notes) like a final chord.
    notes += [GridNote(0, 0, p, 80, Fraction(20), Fraction(4)) for p in pitches[-3:]]
    key = estimate_key(notes)

    assert (key.tonic, key.mode, key.fifths) == (tonic, mode, fifths)


def test_piano_at_100_bpm_through_the_whole_pipeline(tmp_path: Path) -> None:
    melody = [60, 62, 64, 65, 67, 65, 64, 62] * 3
    events = [(0.5 + i * SPB, piano_note(m, SPB * 0.9)) for i, m in enumerate(melody)]
    chords = [
        (0.5 + b * SPB, piano_note(p, SPB * 3)) for b in range(0, 24, 4) for p in (48, 52, 55)
    ]
    wav = tmp_path / "piano_100bpm.wav"
    soundfile.write(wav, place(events + chords, 0.5 + 25 * SPB).astype(np.float32), RATE)

    cfg = PipelineConfig(instrument=Instrument.PIANO)
    result = run_pipeline(wav, tmp_path / "work", cfg, default_stages()).output(QuantizedScore)
    score = Score.model_validate_json((tmp_path / "work" / result.score.path).read_text())

    assert score.tempo_bpm == pytest.approx(BPM, rel=0.03)
    assert (score.key.tonic, score.key.mode) == (0, "major")
    on_beat = sum(n.onset_beats.denominator == 1 for n in score.notes)
    assert on_beat / len(score.notes) >= 0.9
    assert score.pickup_beats == 0
