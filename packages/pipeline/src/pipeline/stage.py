"""The stage contract (ADR-0001): typed inputs -> typed output, files written via StageContext."""

import shutil
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

from pipeline.config import PipelineConfig
from pipeline.errors import PipelineError
from pipeline.hashing import sha256_file
from pipeline.types import ArtifactRef, SourceAudio, StageName, StageOutput

MANIFEST = "manifest.json"


class StageInputs:
    """Upstream outputs a stage declared in `requires`, plus artifact path resolution."""

    def __init__(self, workdir: Path, outputs: Mapping[type[StageOutput], StageOutput]) -> None:
        self._workdir = workdir
        self._outputs = dict(outputs)

    @property
    def outputs(self) -> Mapping[type[StageOutput], StageOutput]:
        return self._outputs

    def get[O: StageOutput](self, kind: type[O]) -> O:
        value = self._outputs.get(kind)
        if not isinstance(value, kind):
            raise PipelineError(f"{kind.__name__} is not in this stage's `requires`")
        return value

    def path(self, ref: ArtifactRef) -> Path:
        return self._workdir / ref.path


class StageContext:
    """Where a running stage writes its files. The dir is temporary until the stage succeeds."""

    def __init__(self, stage: StageName, out_dir: Path, cfg: PipelineConfig) -> None:
        self.stage = stage
        self.out_dir = out_dir
        self.cfg = cfg

    def path(self, name: str) -> Path:
        if Path(name).name != name or name in {"", ".", "..", MANIFEST}:
            raise ValueError(f"invalid artifact name: {name!r}")
        return self.out_dir / name

    def ref(self, name: str) -> ArtifactRef:
        """Reference a file already written with `path(name)`."""
        return ArtifactRef(path=f"{self.stage}/{name}", sha256=sha256_file(self.path(name)))


class Stage[O: StageOutput](ABC):
    name: ClassVar[StageName]
    # Bump whenever this stage's output for the same input can change.
    version: ClassVar[str]
    requires: ClassVar[tuple[type[StageOutput], ...]] = ()
    output_type: type[O]

    def applies(self, cfg: PipelineConfig) -> bool:
        return True

    def fingerprint(self) -> Mapping[str, str]:
        """Extra cache-key data not covered by config or inputs (e.g. the source file hash)."""
        return {}

    @abstractmethod
    def run(self, inputs: StageInputs, ctx: StageContext) -> O: ...


class SourceStage(Stage[SourceAudio]):
    """Copies the input file into the work dir so every later stage reads from one place."""

    name = StageName.SOURCE
    version = "1"
    output_type = SourceAudio

    def __init__(self, source: Path) -> None:
        self._source = source

    def fingerprint(self) -> Mapping[str, str]:
        return {"sha256": sha256_file(self._source), "suffix": self._source.suffix.lower()}

    def run(self, inputs: StageInputs, ctx: StageContext) -> SourceAudio:
        name = f"input{self._source.suffix.lower()}"
        shutil.copyfile(self._source, ctx.path(name))
        return SourceAudio(audio=ctx.ref(name))
