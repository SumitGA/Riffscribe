import subprocess
import tracemalloc
from pathlib import Path

import numpy as np
import pyloudnorm
import pytest
import soundfile

from pipeline.config import Instrument, PipelineConfig
from pipeline.errors import StageFailedError
from pipeline.runner import run_pipeline
from pipeline.stages.normalize import (
    SAMPLE_RATE,
    TARGET_LUFS,
    NormalizedAudio,
    NormalizeStage,
    pcm_sha256,
)

pytestmark = pytest.mark.unit

GUITAR = PipelineConfig(instrument=Instrument.GUITAR)


def tone(seconds: float, sr: int, amp: float = 0.1, freq: float = 220.0) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray, sr: int) -> Path:
    soundfile.write(path, audio, sr)
    return path


def normalize(source: Path, workdir: Path, cfg: PipelineConfig = GUITAR) -> NormalizedAudio:
    return run_pipeline(source, workdir, cfg, [NormalizeStage()]).output(NormalizedAudio)


def failure(source: Path, workdir: Path, cfg: PipelineConfig = GUITAR) -> StageFailedError:
    with pytest.raises(StageFailedError) as err:
        normalize(source, workdir, cfg)
    return err.value


def test_stereo_48k_with_silence_becomes_trimmed_mono_44k(tmp_path: Path) -> None:
    sr = 48_000
    mono = np.concatenate([np.zeros(sr), tone(3.0, sr), np.zeros(sr)])
    source = write_wav(tmp_path / "in.wav", np.stack([mono, mono], axis=1), sr)

    out = normalize(source, tmp_path / "work")
    flac = tmp_path / "work" / out.audio.path
    info = soundfile.info(flac)
    audio, _ = soundfile.read(flac, dtype="float32")

    assert (info.channels, info.samplerate, info.subtype) == (1, SAMPLE_RATE, "PCM_24")
    assert out.trim_start_s == pytest.approx(0.9, abs=0.03)  # 1 s silence minus 0.1 s pad
    assert out.duration_s == pytest.approx(3.2, abs=0.05)
    assert pyloudnorm.Meter(SAMPLE_RATE).integrated_loudness(audio) == pytest.approx(
        TARGET_LUFS, abs=0.5
    )


def test_decodes_compressed_phone_formats(tmp_path: Path) -> None:
    wav = write_wav(tmp_path / "in.wav", tone(2.0, 44_100), 44_100)
    m4a = tmp_path / "in.m4a"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", str(m4a)], check=True
    )

    assert normalize(m4a, tmp_path / "work").duration_s == pytest.approx(2.0, abs=0.15)


def test_pcm_hash_is_stable_and_matches_stored_samples(tmp_path: Path) -> None:
    source = write_wav(tmp_path / "in.wav", tone(2.0, 44_100), 44_100)
    first = normalize(source, tmp_path / "a")
    second = normalize(source, tmp_path / "b")

    assert first.pcm_sha256 == second.pcm_sha256
    assert first.pcm_sha256 == pcm_sha256(tmp_path / "a" / first.audio.path)


def test_peak_memory_stays_near_one_copy_of_the_audio(tmp_path: Path) -> None:
    seconds = 30
    source = write_wav(tmp_path / "in.wav", tone(seconds, 44_100), 44_100)
    one_copy = seconds * SAMPLE_RATE * 4  # float32 mono

    tracemalloc.start()
    try:
        normalize(source, tmp_path / "work")
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert peak < 2 * one_copy, f"peak {peak / 1e6:.1f} MB for {one_copy / 1e6:.1f} MB of audio"


def test_loud_input_is_kept_below_full_scale(tmp_path: Path) -> None:
    square = np.sign(tone(2.0, 44_100, amp=1.0)).astype(np.float32)
    out = normalize(write_wav(tmp_path / "in.wav", square, 44_100), tmp_path / "work")
    audio, _ = soundfile.read(tmp_path / "work" / out.audio.path, dtype="float32")

    assert np.abs(audio).max() <= 0.99 + 1e-6


@pytest.mark.parametrize(
    ("audio", "cfg", "message"),
    [
        (tone(3.0, 44_100), GUITAR.model_copy(update={"max_duration_s": 2.0}), "longer than"),
        (tone(0.5, 44_100), GUITAR, "less than 1 s"),
        (np.zeros(3 * 44_100, dtype=np.float32), GUITAR, "silent"),
    ],
    ids=["too-long", "too-short", "silent"],
)
def test_invalid_audio_is_rejected_without_retry(
    tmp_path: Path, audio: np.ndarray, cfg: PipelineConfig, message: str
) -> None:
    err = failure(write_wav(tmp_path / "in.wav", audio, 44_100), tmp_path / "work", cfg)

    assert message in str(err)
    assert not err.retryable


def test_non_audio_file_is_rejected_without_retry(tmp_path: Path) -> None:
    source = tmp_path / "notes.mp3"
    source.write_text("definitely not audio")
    err = failure(source, tmp_path / "work")

    assert "could not decode audio" in str(err)
    assert not err.retryable


def test_missing_ffmpeg_is_retryable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FFMPEG_BINARY", str(tmp_path / "no-such-ffmpeg"))
    err = failure(write_wav(tmp_path / "in.wav", tone(2.0, 44_100), 44_100), tmp_path / "work")

    assert "ffmpeg not found" in str(err)
    assert err.retryable
