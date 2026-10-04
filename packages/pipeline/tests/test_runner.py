import json
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest
import soundfile
from typer.testing import CliRunner

from pipeline.cli import app
from pipeline.config import Instrument, PipelineConfig
from pipeline.errors import PipelineError, StageFailedError
from pipeline.runner import RunResult, run_pipeline
from pipeline.stage import Stage, StageContext, StageInputs
from pipeline.types import ArtifactRef, SourceAudio, StageName, StageOutput

pytestmark = pytest.mark.unit

GUITAR = PipelineConfig(instrument=Instrument.GUITAR)


class Upper(StageOutput):
    stage = StageName.NORMALIZE
    text: ArtifactRef


class Length(StageOutput):
    stage = StageName.TRANSCRIBE
    data: ArtifactRef
    length: int


class UpperStage(Stage[Upper]):
    name = StageName.NORMALIZE
    version = "1"
    requires = (SourceAudio,)
    output_type = Upper

    def __init__(self) -> None:
        self.calls = 0

    def run(self, inputs: StageInputs, ctx: StageContext) -> Upper:
        self.calls += 1
        text = inputs.path(inputs.get(SourceAudio).audio).read_text()
        ctx.path("upper.txt").write_text(text.upper())
        return Upper(text=ctx.ref("upper.txt"))


class LengthStage(Stage[Length]):
    name = StageName.TRANSCRIBE
    version = "1"
    requires = (Upper,)
    output_type = Length

    def __init__(self) -> None:
        self.calls = 0

    def run(self, inputs: StageInputs, ctx: StageContext) -> Length:
        self.calls += 1
        text = inputs.path(inputs.get(Upper).text).read_text()
        ctx.path("len.json").write_text(json.dumps(len(text)))
        return Length(data=ctx.ref("len.json"), length=len(text))


class LengthStageV2(LengthStage):
    version: ClassVar[str] = "2"


class GuitarOnlyUpper(UpperStage):
    def applies(self, cfg: PipelineConfig) -> bool:
        return cfg.instrument is Instrument.GUITAR


class FailingLengthStage(LengthStage):
    def run(self, inputs: StageInputs, ctx: StageContext) -> Length:
        ctx.path("partial.json").write_text("{")
        raise RuntimeError("model crashed")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "clip.TXT"
    path.write_text("hello")
    return path


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path / "work"


def statuses(result: RunResult) -> dict[str, str]:
    return {r.stage: r.status for r in result.stages}


def test_first_run_writes_outputs_and_manifests(source: Path, workdir: Path) -> None:
    result = run_pipeline(source, workdir, GUITAR, [UpperStage(), LengthStage()])

    assert statuses(result) == {"source": "ran", "normalize": "ran", "transcribe": "ran"}
    assert result.output(Length).length == 5
    assert result.output(SourceAudio).audio.path == "source/input.txt"
    assert (workdir / "normalize" / "upper.txt").read_text() == "HELLO"
    manifest = json.loads((workdir / "transcribe" / "manifest.json").read_text())
    assert manifest["pipeline_version"] == result.pipeline_version
    assert manifest["artifacts"] == [result.output(Length).data.model_dump()]


def test_second_run_is_fully_cached(source: Path, workdir: Path) -> None:
    upper, length = UpperStage(), LengthStage()
    run_pipeline(source, workdir, GUITAR, [upper, length])
    result = run_pipeline(source, workdir, GUITAR, [upper, length])

    assert set(statuses(result).values()) == {"cached"}
    assert (upper.calls, length.calls) == (1, 1)
    assert result.output(Length).length == 5


def test_changed_source_reruns_everything(source: Path, workdir: Path) -> None:
    run_pipeline(source, workdir, GUITAR, [UpperStage(), LengthStage()])
    source.write_text("hello world")
    result = run_pipeline(source, workdir, GUITAR, [UpperStage(), LengthStage()])

    assert set(statuses(result).values()) == {"ran"}
    assert result.output(Length).length == 11


def test_changed_config_reruns(source: Path, workdir: Path) -> None:
    run_pipeline(source, workdir, GUITAR, [UpperStage()])
    piano = PipelineConfig(instrument=Instrument.PIANO)
    result = run_pipeline(source, workdir, piano, [UpperStage()])

    assert statuses(result)["normalize"] == "ran"


def test_version_bump_reruns_only_that_stage(source: Path, workdir: Path) -> None:
    first = run_pipeline(source, workdir, GUITAR, [UpperStage(), LengthStage()])
    second = run_pipeline(source, workdir, GUITAR, [UpperStage(), LengthStageV2()])

    assert statuses(second) == {"source": "cached", "normalize": "cached", "transcribe": "ran"}
    assert second.pipeline_version != first.pipeline_version


def test_tampered_artifact_is_recomputed(source: Path, workdir: Path) -> None:
    run_pipeline(source, workdir, GUITAR, [UpperStage(), LengthStage()])
    (workdir / "normalize" / "upper.txt").write_text("CORRUPT")
    result = run_pipeline(source, workdir, GUITAR, [UpperStage(), LengthStage()])

    assert statuses(result)["normalize"] == "ran"
    assert (workdir / "normalize" / "upper.txt").read_text() == "HELLO"
    # Recomputed output is byte-identical, so the downstream stage stays cached.
    assert statuses(result)["transcribe"] == "cached"


def test_force_from_reruns_that_stage_and_later(source: Path, workdir: Path) -> None:
    run_pipeline(source, workdir, GUITAR, [UpperStage(), LengthStage()])
    result = run_pipeline(
        source, workdir, GUITAR, [UpperStage(), LengthStage()], force_from=StageName.NORMALIZE
    )

    assert statuses(result) == {"source": "cached", "normalize": "ran", "transcribe": "ran"}


def test_failed_stage_keeps_previous_output_and_leaves_no_scratch(
    source: Path, workdir: Path
) -> None:
    run_pipeline(source, workdir, GUITAR, [UpperStage(), LengthStage()])
    before = (workdir / "transcribe" / "manifest.json").read_text()

    with pytest.raises(StageFailedError, match="model crashed") as err:
        run_pipeline(
            source,
            workdir,
            GUITAR,
            [UpperStage(), FailingLengthStage()],
            force_from=StageName.TRANSCRIBE,
        )

    assert err.value.stage is StageName.TRANSCRIBE
    assert (workdir / "transcribe" / "manifest.json").read_text() == before
    assert not (workdir / "transcribe" / "partial.json").exists()
    assert sorted(p.name for p in workdir.iterdir()) == ["normalize", "source", "transcribe"]


def test_leftover_scratch_dirs_are_cleaned(source: Path, workdir: Path) -> None:
    (workdir / ".tmp-normalize-dead").mkdir(parents=True)
    run_pipeline(source, workdir, GUITAR, [UpperStage()])

    assert not (workdir / ".tmp-normalize-dead").exists()


def test_skipped_stage_and_missing_requirement(source: Path, workdir: Path) -> None:
    piano = PipelineConfig(instrument=Instrument.PIANO)
    result = run_pipeline(source, workdir, piano, [GuitarOnlyUpper()])
    assert statuses(result)["normalize"] == "skipped"

    with pytest.raises(PipelineError, match="requires Upper"):
        run_pipeline(source, workdir, piano, [GuitarOnlyUpper(), LengthStage()])


def test_unknown_force_from_is_rejected(source: Path, workdir: Path) -> None:
    with pytest.raises(PipelineError, match="not in this pipeline"):
        run_pipeline(source, workdir, GUITAR, [UpperStage()], force_from=StageName.TAB)


def test_artifact_names_cannot_escape_stage_dir(tmp_path: Path) -> None:
    ctx = StageContext(StageName.NORMALIZE, tmp_path, GUITAR)
    for bad in ["../x", "a/b", "", "manifest.json"]:
        with pytest.raises(ValueError, match="invalid artifact name"):
            ctx.path(bad)


def test_cli_transcribe_runs_and_caches(tmp_path: Path, workdir: Path) -> None:
    wav = tmp_path / "clip.wav"
    sr = 44_100
    soundfile.write(wav, 0.1 * np.sin(2 * np.pi * 220 * np.arange(2 * sr) / sr), sr)
    args = ["transcribe", str(wav), "--out", str(workdir), "--instrument", "guitar"]
    first = CliRunner().invoke(app, args)
    second = CliRunner().invoke(app, args)

    assert first.exit_code == 0, first.output
    assert "normalize   ran" in first.output
    assert "normalize   cached" in second.output


def test_cli_reports_invalid_input(source: Path, workdir: Path) -> None:
    args = ["transcribe", str(source), "--out", str(workdir), "--instrument", "guitar"]
    result = CliRunner().invoke(app, args)

    assert result.exit_code == 1
    assert "could not decode audio" in result.output
