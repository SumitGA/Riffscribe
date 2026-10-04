"""separate: optionally isolate the instrument with Demucs; by default a passthrough."""

import soundfile

from pipeline.stage import Stage, StageContext, StageInputs
from pipeline.stages.normalize import NormalizedAudio
from pipeline.types import ArtifactRef, StageName, StageOutput


class SeparatedAudio(StageOutput):
    stage = StageName.SEPARATE
    # The isolated stem (24-bit FLAC, mono, 44.1 kHz), or None to use the normalized audio as
    # is. A passthrough writes nothing, so it doesn't duplicate the audio in storage.
    audio: ArtifactRef | None
    method: str  # "passthrough" or "demucs:<model>:<stem>"


class SeparateStage(Stage[SeparatedAudio]):
    name = StageName.SEPARATE
    version = "1"
    requires = (NormalizedAudio,)
    output_type = SeparatedAudio

    def run(self, inputs: StageInputs, ctx: StageContext) -> SeparatedAudio:
        if not ctx.cfg.separation:
            return SeparatedAudio(audio=None, method="passthrough")

        from pipeline import separation

        normalized = inputs.get(NormalizedAudio)
        audio, rate = soundfile.read(inputs.path(normalized.audio), dtype="float32")
        if rate != separation.SAMPLE_RATE:
            raise ValueError(f"expected {separation.SAMPLE_RATE} Hz, got {rate} Hz")
        stem = separation.isolate(audio, ctx.cfg.instrument)
        soundfile.write(ctx.path("stem.flac"), stem, rate, subtype="PCM_24", format="FLAC")
        return SeparatedAudio(
            audio=ctx.ref("stem.flac"),
            method=f"demucs:{separation.MODEL}:{separation.STEM[ctx.cfg.instrument]}",
        )
