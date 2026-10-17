"""Parity with upstream GAPS and Kong et al.; see fixtures/gaps/make_reference.py."""

from pathlib import Path

import numpy as np
import pytest
import soundfile
from scipy.signal import resample_poly

from pipeline import gaps
from pipeline.gaps import (
    BORDER_FRAMES,
    CHUNK_FRAMES,
    N_PITCHES,
    Gaps,
    Outputs,
    chunks,
    decode_notes,
    log_mel,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = np.load(FIXTURES / "gaps" / "reference.npz")
UPSTREAM = Outputs(*(REFERENCE[k] for k in ("onset", "offset", "frame", "velocity")))
# The shipped model has int8 convolutions and its upstream reference ran the 12 s in one piece,
# not two chunks. Measured: mean difference 3e-5 to 2e-3; note F1 on the accuracy clips unchanged.
OUTPUT_MEAN_TOL = 0.005


def upstream_notes() -> list[tuple[float, float, int, int]]:
    return [(round(a, 4), round(b, 4), int(p), int(v)) for a, b, p, v in REFERENCE["notes"]]


@pytest.fixture(scope="module")
def audio() -> np.ndarray:
    audio, rate = soundfile.read(
        FIXTURES / "guitarset" / "05_BN1-129-Eb_solo.flac", dtype="float32"
    )
    assert rate == 44_100
    return np.asarray(resample_poly(audio, 160, 441), np.float32)[: 12 * 16_000]


@pytest.fixture(scope="module")
def outputs(audio: np.ndarray) -> Outputs:
    return Gaps().outputs(audio)


def test_log_mel_matches_torchlibrosa(audio: np.ndarray) -> None:
    np.testing.assert_allclose(log_mel(audio), REFERENCE["mel"], atol=0.1)  # reference is fp16


def test_outputs_match_upstream(outputs: Outputs) -> None:
    for ours, theirs in zip(outputs, UPSTREAM, strict=True):
        assert ours.shape == theirs.shape
        assert np.abs(ours - theirs).mean() < OUTPUT_MEAN_TOL


def test_decoding_matches_upstream_post_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gaps, "FRAME_THRESHOLD", 0.1)  # upstream's
    notes = decode_notes(UPSTREAM, 21, 108)
    ours = [
        (round(n.start_s, 4), round(n.end_s, 4), n.pitch, int(n.amplitude * 128)) for n in notes
    ]
    assert sorted(ours) == sorted(upstream_notes())


def test_model_finds_upstreams_notes(outputs: Outputs) -> None:
    ours = {(round(n.start_s, 1), n.pitch) for n in decode_notes(outputs, 21, 108)}
    theirs = {(round(a, 1), p) for a, _, p, _ in upstream_notes()}
    assert len(ours & theirs) >= 0.9 * len(theirs | ours)


def test_decoding_keeps_to_the_pitch_range() -> None:
    notes = decode_notes(UPSTREAM, 50, 60)
    assert notes
    assert all(50 <= n.pitch <= 60 for n in notes)


def test_a_repicked_note_ends_where_the_next_begins() -> None:
    curve = np.zeros((100, N_PITCHES), np.float32)
    onset = curve.copy()
    onset[8:13, 30] = onset[38:43, 30] = [0.4, 0.7, 0.9, 0.7, 0.4]
    frame = curve.copy()
    frame[10:80, 30] = 0.9
    velocity = np.full_like(curve, 0.5)
    notes = decode_notes(Outputs(onset, curve, frame, velocity), 21, 108)
    times = [(round(n.start_s, 4), round(n.end_s, 4), n.pitch) for n in notes]
    assert times == [(0.1, 0.39, 51), (0.4, 0.8, 51)]


def test_chunks_cover_every_frame_once() -> None:
    for n in (10, CHUNK_FRAMES, CHUNK_FRAMES + 1, 2 * CHUNK_FRAMES - 2 * BORDER_FRAMES, 30_017):
        covered = np.zeros(n, int)
        for start, keep_from, keep_to in chunks(n):
            assert start <= keep_from < keep_to <= min(start + CHUNK_FRAMES, n)
            assert keep_from == 0 or keep_from - start >= BORDER_FRAMES
            assert keep_to == n or start + CHUNK_FRAMES - keep_to >= BORDER_FRAMES
            covered[keep_from:keep_to] += 1
        assert (covered == 1).all()


def test_silence_has_no_notes() -> None:
    outputs = Gaps().outputs(np.zeros(16_000 * 3, np.float32))
    assert outputs.frame.shape == (301, N_PITCHES)
    assert decode_notes(outputs, 21, 108) == []
