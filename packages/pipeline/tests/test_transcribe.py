import json
from pathlib import Path

import mido
import pytest

from pipeline.config import Instrument, PipelineConfig
from pipeline.midi import write_notes
from pipeline.runner import run_pipeline
from pipeline.stages import default_stages
from pipeline.stages.transcribe import PITCH_RANGE, NoteEvents, NoteList, TranscribeStage
from pipeline.types import StageName

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "basic_pitch"
GUITAR = PipelineConfig(instrument=Instrument.GUITAR)


def onset_f1(actual: NoteList, expected: list[dict[str, float]], tol: float = 0.05) -> float:
    """Note F1 counting a hit when pitch matches and onsets are within `tol` seconds."""
    unmatched = list(expected)
    hits = 0
    for note in actual.notes:
        match = next(
            (
                e
                for e in unmatched
                if e["pitch"] == note.pitch and abs(e["start_s"] - note.onset_s) <= tol
            ),
            None,
        )
        if match is not None:
            unmatched.remove(match)
            hits += 1
    return 2 * hits / (len(actual.notes) + len(expected))


def test_full_pipeline_with_default_decoding_matches_upstream_notes(tmp_path: Path) -> None:
    """Piano uses Basic Pitch's default decoding, so its notes must match upstream's."""
    piano = PipelineConfig(instrument=Instrument.PIANO)
    result = run_pipeline(FIXTURES / "guitar_like.wav", tmp_path, piano, default_stages())
    notes = NoteList.model_validate_json(
        (tmp_path / result.output(NoteEvents).notes.path).read_text()
    )
    upstream = json.loads((FIXTURES / "guitar_like.notes.json").read_text())

    # Normalize resamples to 44.1 kHz, changes gain and trims, so allow small differences.
    assert onset_f1(notes, upstream) >= 0.9


def test_guitar_transcription_uses_its_range_and_program(tmp_path: Path) -> None:
    result = run_pipeline(FIXTURES / "guitar_like.wav", tmp_path, GUITAR, default_stages())
    events = result.output(NoteEvents)
    notes = NoteList.model_validate_json((tmp_path / events.notes.path).read_text())

    assert events.note_count == len(notes.notes) > 0
    low, high = PITCH_RANGE[Instrument.GUITAR]
    assert all(low <= n.pitch <= high for n in notes.notes)

    midi = mido.MidiFile(tmp_path / events.midi.path)
    note_ons = [m for m in midi.tracks[0] if m.type == "note_on"]
    programs = [m.program for m in midi.tracks[0] if m.type == "program_change"]
    assert len(note_ons) == events.note_count
    assert programs == [25]


def test_cached_run_does_not_load_the_model(tmp_path: Path) -> None:
    source = FIXTURES / "piano_like.wav"
    cfg = PipelineConfig(instrument=Instrument.PIANO)
    run_pipeline(source, tmp_path, cfg, default_stages())

    transcribe = TranscribeStage()
    upstream = default_stages()[:2]  # normalize, separate
    result = run_pipeline(source, tmp_path, cfg, [*upstream, transcribe])

    assert {r.stage: r.status for r in result.stages}[StageName.TRANSCRIBE] == "cached"
    assert transcribe._model is None


def test_midi_repeated_notes_end_before_they_restart(tmp_path: Path) -> None:
    path = tmp_path / "x.mid"
    write_notes(path, [(0.0, 0.5, 60, 100), (0.5, 1.0, 60, 90)])

    messages = [m for m in mido.MidiFile(path).tracks[0] if m.type in {"note_on", "note_off"}]
    assert [(m.type, m.time) for m in messages] == [
        ("note_on", 0),
        ("note_off", 480),
        ("note_on", 0),
        ("note_off", 480),
    ]
