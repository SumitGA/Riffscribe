"""Parity with upstream Beat This! (small0); see fixtures/beat_this/make_reference.py."""

from pathlib import Path

import numpy as np
import pytest
import soundfile
from scipy.signal import resample_poly

from pipeline.beat_this import BORDER_FRAMES, CHUNK_FRAMES, BeatThis, chunk_starts, log_mel

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = np.load(FIXTURES / "beat_this" / "reference.npz")
INPUTS = {
    "comp": ["04_SS1-100-C#_comp"],
    "long": ["00_BN1-129-Eb_comp", "01_Funk1-114-Ab_solo", "02_Jazz1-130-D_comp"],  # 60 s
}
# The shipped model has int8 weights; upstream's logits are float32. Measured: mean difference
# 0.06-0.08 (the float export matched to 6e-5); beat F on 54 GuitarSet clips unchanged.
LOGIT_MEAN_TOL = 0.15


@pytest.fixture(scope="module")
def model() -> BeatThis:
    return BeatThis()


def load(name: str) -> np.ndarray:
    parts = []
    for clip in INPUTS[name]:
        audio, rate = soundfile.read(FIXTURES / "guitarset" / f"{clip}.flac", dtype="float32")
        parts.append(resample_poly(audio, 1, rate // 22050).astype(np.float32))
    return np.concatenate(parts)


def test_log_mel_matches_torchaudio() -> None:
    np.testing.assert_allclose(log_mel(load("comp")), REFERENCE["comp.spect"], atol=2e-4)


@pytest.mark.parametrize("name", INPUTS)
def test_logits_match_upstream(model: BeatThis, name: str) -> None:
    beat, downbeat = model.logits(load(name))
    assert beat.shape == REFERENCE[f"{name}.beat"].shape
    assert np.abs(beat - REFERENCE[f"{name}.beat"]).mean() < LOGIT_MEAN_TOL
    assert np.abs(downbeat - REFERENCE[f"{name}.downbeat"]).mean() < LOGIT_MEAN_TOL


def test_chunks_cover_every_frame_outside_their_borders() -> None:
    for n in (10, CHUNK_FRAMES - 2 * BORDER_FRAMES + 2, 3001, 15_000):
        covered = np.zeros(n, int)
        for start in chunk_starts(n):
            length = min(start + CHUNK_FRAMES, n + BORDER_FRAMES) - start
            covered[max(0, start + BORDER_FRAMES) : start + length - BORDER_FRAMES] += 1
        assert covered.min() >= 1


def test_silence_has_no_beats(model: BeatThis) -> None:
    activations = model.activations(np.zeros(22050 * 5, np.float32))
    assert activations.shape == (251, 2)
    assert activations.max() < 0.5
