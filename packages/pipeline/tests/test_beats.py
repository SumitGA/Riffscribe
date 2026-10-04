"""Parity with librosa 1.0.0 beat tracking; see fixtures/rhythm/make_reference.py."""

import json
from pathlib import Path

import numpy as np
import pytest
from fixtures.basic_pitch.generate_clips import piano_note, place, plucked_string

from pipeline.basic_pitch import ENVELOPE_FPS, BasicPitch, onset_envelope
from pipeline.beats import beat_track, estimate_tempo

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "rhythm"
ENVELOPES = np.load(FIXTURES / "envelopes.npz")
REFERENCE = json.loads((FIXTURES / "reference.json").read_text())
FPS = 22050 / 256


@pytest.mark.parametrize("name", ENVELOPES.files)
def test_tempo_and_beats_match_librosa(name: str) -> None:
    bpm, beats = beat_track(ENVELOPES[name], FPS)
    ref_bpm, ref_beats = REFERENCE[name]

    assert bpm == pytest.approx(ref_bpm, rel=1e-9)
    assert beats.tolist() == ref_beats


def test_clear_pulse_tempos_are_found() -> None:
    for name, expected in [("pulse72", 72), ("pulse100", 100), ("pulse140", 140)]:
        bpm, _ = beat_track(ENVELOPES[name], FPS)
        assert bpm == pytest.approx(expected, rel=0.01), name


def test_fast_tempo_is_halved_like_librosa() -> None:
    """Known limitation: the 120 bpm prior turns 175 bpm into its half (TD-12)."""
    bpm, _ = beat_track(ENVELOPES["pulse175"], FPS)
    assert bpm == pytest.approx(175 / 2, rel=0.01)


def test_silence_has_no_beats() -> None:
    bpm, beats = beat_track(np.zeros(1000), FPS)
    assert (bpm, beats.size) == (0.0, 0)


def melody_clip(instrument: str, bpm: float, notes_per_beat: int, n_beats: int = 24) -> np.ndarray:
    spb = 60 / bpm
    melody = [60, 62, 64, 65, 67, 65, 64, 62]
    events = []
    for i in range(n_beats * notes_per_beat):
        start, length = 0.5 + i * spb / notes_per_beat, spb / notes_per_beat
        pitch = melody[i % len(melody)]
        if instrument == "piano":
            events.append((start, piano_note(pitch, length * 0.9)))
        else:
            events.append((start, plucked_string(pitch - 12, length * 1.5, seed=i)))
    return place(events, 0.5 + (n_beats + 1) * spb).astype(np.float32)


@pytest.mark.parametrize(
    ("instrument", "bpm", "notes_per_beat"),
    [("piano", 72, 1), ("piano", 140, 1), ("guitar", 100, 2), ("guitar", 90, 1)],
)
def test_onset_envelope_gives_the_played_tempo(
    instrument: str, bpm: float, notes_per_beat: int
) -> None:
    """Guards the envelope itself: parity with librosa says nothing if the envelope is wrong."""
    _, onsets = BasicPitch().activations(melody_clip(instrument, bpm, notes_per_beat))
    envelope = onset_envelope(onsets, 21, 108).astype(np.float64)

    assert estimate_tempo(envelope, ENVELOPE_FPS) == pytest.approx(bpm, rel=0.02)
