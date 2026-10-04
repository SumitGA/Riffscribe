"""normalize: decode to 44.1 kHz mono, trim edge silence, normalize loudness, store FLAC."""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile

from pipeline.errors import InvalidInputError
from pipeline.loudness import integrated_loudness
from pipeline.stage import Stage, StageContext, StageInputs
from pipeline.types import ArtifactRef, SourceAudio, StageName, StageOutput

SAMPLE_RATE = 44_100
MIN_DURATION_S = 1.0
TARGET_LUFS = -20.0
PEAK_CEILING = 0.99  # about -0.1 dBFS, so the 24-bit FLAC never clips
SILENCE_FLOOR_DBFS = -60.0  # quieter than this everywhere = silent recording
EDGE_RANGE_DB = 40.0  # edge blocks this far below the loudest block count as silence
EDGE_PAD_S = 0.1  # keep a little silence so the first onset isn't clipped
BLOCK = 1024  # ~23 ms analysis blocks for silence detection
DECODE_TIMEOUT_S = 120
HASH_BLOCK = 1 << 16  # samples per read when hashing, so hashing never loads the whole file

Audio = npt.NDArray[np.float32]


class NormalizedAudio(StageOutput):
    stage = StageName.NORMALIZE
    audio: ArtifactRef  # 24-bit FLAC, mono, SAMPLE_RATE
    sample_rate: int
    duration_s: float
    trim_start_s: float  # where this audio starts within the source, to map times back
    pcm_sha256: str  # hash of the stored samples; with pipeline_version, the dedup key


class NormalizeStage(Stage[NormalizedAudio]):
    name = StageName.NORMALIZE
    version = "1"
    requires = (SourceAudio,)
    output_type = NormalizedAudio

    def run(self, inputs: StageInputs, ctx: StageContext) -> NormalizedAudio:
        max_s = ctx.cfg.max_duration_s
        # Decode slightly past the limit so an over-long file is detected without decoding it all.
        audio = decode(inputs.path(inputs.get(SourceAudio).audio), max_seconds=max_s + 1)
        if audio.size > max_s * SAMPLE_RATE:
            raise InvalidInputError(f"audio is longer than the {max_s:g} s limit")
        _require_min_duration(audio)

        start, end = _sound_bounds(audio)
        audio = audio[start:end]
        _require_min_duration(audio)
        audio = _normalize_loudness(audio)

        path = ctx.path("audio.flac")
        soundfile.write(path, audio, SAMPLE_RATE, subtype="PCM_24", format="FLAC")
        return NormalizedAudio(
            audio=ctx.ref("audio.flac"),
            sample_rate=SAMPLE_RATE,
            duration_s=round(audio.size / SAMPLE_RATE, 6),
            trim_start_s=round(start / SAMPLE_RATE, 6),
            pcm_sha256=pcm_sha256(path),
        )


def decode(path: Path, max_seconds: float) -> Audio:
    """Decode the first audio stream of any ffmpeg-readable file to mono float32 at SAMPLE_RATE."""
    with tempfile.TemporaryDirectory(prefix="tabscribe-decode-") as tmp:
        # Raw samples go to a file and are loaded with one allocation; piping them through
        # stdout would hold several copies in memory.
        raw = Path(tmp) / "audio.f32"
        # ffmpeg runs as a separate program, not a linked library (see docs/tech-debt TD-9).
        cmd = [
            os.environ.get("FFMPEG_BINARY", "ffmpeg"),
            "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(path),
            "-map", "0:a:0", "-t", f"{max_seconds:.3f}",
            "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", str(raw),
        ]  # fmt: skip
        try:
            proc = subprocess.run(cmd, capture_output=True, check=False, timeout=DECODE_TIMEOUT_S)
        except FileNotFoundError as exc:
            raise RuntimeError("ffmpeg not found; install it or set FFMPEG_BINARY") from exc
        if proc.returncode != 0:
            detail = proc.stderr.decode(errors="replace").strip()[-300:]
            raise InvalidInputError(f"could not decode audio: {detail}")
        audio: Audio = (
            np.fromfile(raw, dtype=np.float32) if raw.exists() else np.empty(0, np.float32)
        )
    if audio.size == 0:
        raise InvalidInputError("file contains no audio samples")
    # One boolean mask (1/4 of the audio size); nan_to_num would allocate several.
    bad = ~np.isfinite(audio)
    if bad.any():
        audio[bad] = 0.0
    return audio


def pcm_sha256(flac: Path) -> str:
    """Hash the decoded samples, not the file bytes, so container metadata can't change it."""
    digest = hashlib.sha256()
    for block in soundfile.blocks(flac, blocksize=HASH_BLOCK, dtype="int32"):
        digest.update(np.ascontiguousarray(block).tobytes())
    return digest.hexdigest()


def _require_min_duration(audio: Audio) -> None:
    if audio.size < MIN_DURATION_S * SAMPLE_RATE:
        raise InvalidInputError(f"less than {MIN_DURATION_S:g} s of sound")


def _sound_bounds(audio: Audio) -> tuple[int, int]:
    """Sample range from the first to the last non-silent block, plus a little padding."""
    blocks = audio[: audio.size // BLOCK * BLOCK].reshape(-1, BLOCK)
    level_db = 10 * np.log10(np.einsum("ij,ij->i", blocks, blocks) / BLOCK + 1e-12)
    loudest = float(level_db.max())
    if loudest < SILENCE_FLOOR_DBFS:
        raise InvalidInputError("no sound detected; the recording is silent")
    loud = np.flatnonzero(level_db > max(SILENCE_FLOOR_DBFS, loudest - EDGE_RANGE_DB))
    pad = int(EDGE_PAD_S * SAMPLE_RATE)
    start = max(0, int(loud[0]) * BLOCK - pad)
    end = min(audio.size, (int(loud[-1]) + 1) * BLOCK + pad)
    return start, end


def _normalize_loudness(audio: Audio) -> Audio:
    """Scale to TARGET_LUFS, then down again if that would push peaks past PEAK_CEILING.

    Modifies `audio` in place to avoid another full-size copy.
    """
    loudness = integrated_loudness(audio, SAMPLE_RATE)
    gain = 10 ** ((TARGET_LUFS - loudness) / 20) if np.isfinite(loudness) else 1.0
    peak = max(float(audio.max()), -float(audio.min())) * gain
    if peak > PEAK_CEILING:
        gain *= PEAK_CEILING / peak
    audio *= np.float32(gain)
    return audio
