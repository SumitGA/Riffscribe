"""Parity with upstream basic-pitch 0.4.0; see fixtures/basic_pitch/make_reference.py."""

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile

from pipeline.basic_pitch import SAMPLE_RATE, BasicPitch, DecodeParams, RawNote, decode_notes

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "basic_pitch"
CLIPS = ["guitar_like", "piano_like"]


@pytest.fixture(scope="module")
def model() -> BasicPitch:
    return BasicPitch()


def load_audio(clip: str) -> np.ndarray:
    audio, rate = soundfile.read(FIXTURES / f"{clip}.wav", dtype="float32")
    assert rate == SAMPLE_RATE
    return np.asarray(audio)


def reference_activations(clip: str) -> tuple[np.ndarray, np.ndarray]:
    data = np.load(FIXTURES / f"{clip}.activations.npz")
    return data["note"], data["onset"]


def reference_notes(clip: str) -> list[RawNote]:
    rows = json.loads((FIXTURES / f"{clip}.notes.json").read_text())
    return [RawNote(r["start_s"], r["end_s"], r["pitch"], r["amplitude"]) for r in rows]


def assert_same_notes(actual: list[RawNote], expected: list[RawNote], time_tol: float) -> None:
    assert [n.pitch for n in actual] == [n.pitch for n in expected]
    for a, e in zip(actual, expected, strict=True):
        assert a.start_s == pytest.approx(e.start_s, abs=time_tol)
        assert a.end_s == pytest.approx(e.end_s, abs=time_tol)
        assert a.amplitude == pytest.approx(e.amplitude, abs=1e-3)


@pytest.mark.parametrize("clip", CLIPS)
def test_activations_match_upstream(model: BasicPitch, clip: str) -> None:
    frames, onsets = model.activations(load_audio(clip))
    ref_frames, ref_onsets = reference_activations(clip)

    assert frames.shape == ref_frames.shape
    np.testing.assert_allclose(frames, ref_frames, atol=1e-4)
    np.testing.assert_allclose(onsets, ref_onsets, atol=1e-4)


@pytest.mark.parametrize("clip", CLIPS)
def test_decoding_upstream_activations_gives_upstream_notes(clip: str) -> None:
    notes = decode_notes(*reference_activations(clip))

    assert_same_notes(notes, reference_notes(clip), time_tol=1e-6)


@pytest.mark.parametrize("clip", CLIPS)
def test_end_to_end_matches_upstream(model: BasicPitch, clip: str) -> None:
    notes = decode_notes(*model.activations(load_audio(clip)))

    assert_same_notes(notes, reference_notes(clip), time_tol=1e-6)


def test_pitch_limits_are_inclusive() -> None:
    frames, onsets = reference_activations("guitar_like")
    all_pitches = {n.pitch for n in decode_notes(frames, onsets)}
    low, high = min(all_pitches), max(all_pitches)

    limited = decode_notes(frames, onsets, DecodeParams(min_pitch=low + 1, max_pitch=high))
    assert {n.pitch for n in limited} <= set(range(low + 1, high + 1))
    assert high in {n.pitch for n in limited}
