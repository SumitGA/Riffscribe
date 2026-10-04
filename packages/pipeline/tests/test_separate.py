import importlib.util
from pathlib import Path

import numpy as np
import pytest
import soundfile

from pipeline.config import Instrument, PipelineConfig
from pipeline.errors import StageFailedError
from pipeline.runner import run_pipeline
from pipeline.stages import default_stages
from pipeline.stages.separate import SeparatedAudio
from pipeline.stages.transcribe import NoteEvents

FIXTURES = Path(__file__).parent / "fixtures" / "basic_pitch"
GUITAR = PipelineConfig(instrument=Instrument.GUITAR)
DEMUCS_INSTALLED = importlib.util.find_spec("demucs") is not None


@pytest.mark.unit
def test_default_is_a_passthrough_that_writes_no_audio(tmp_path: Path) -> None:
    result = run_pipeline(FIXTURES / "guitar_like.wav", tmp_path, GUITAR, default_stages())
    separated = result.output(SeparatedAudio)

    assert (separated.audio, separated.method) == (None, "passthrough")
    assert sorted(p.name for p in (tmp_path / "separate").iterdir()) == ["manifest.json"]
    assert result.output(NoteEvents).note_count > 0  # transcribed from the normalized audio


@pytest.mark.unit
@pytest.mark.skipif(DEMUCS_INSTALLED, reason="checks the message shown without Demucs")
def test_separation_without_demucs_explains_how_to_install(tmp_path: Path) -> None:
    cfg = GUITAR.model_copy(update={"separation": True})
    with pytest.raises(StageFailedError, match="uv sync --group separation"):
        run_pipeline(FIXTURES / "guitar_like.wav", tmp_path, cfg, default_stages())


@pytest.mark.separation
def test_demucs_writes_the_instrument_stem(tmp_path: Path) -> None:
    pytest.importorskip("demucs")
    cfg = GUITAR.model_copy(update={"separation": True})
    result = run_pipeline(FIXTURES / "guitar_like.wav", tmp_path, cfg, default_stages())
    separated = result.output(SeparatedAudio)

    assert separated.method == "demucs:htdemucs_6s:guitar"
    assert separated.audio is not None
    stem, rate = soundfile.read(tmp_path / separated.audio.path, dtype="float32")
    assert rate == 44_100 and stem.ndim == 1 and np.abs(stem).max() > 0
