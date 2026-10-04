"""Typed stage outputs and manifests shared by every stage (ADR-0001)."""

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict


class StageName(StrEnum):
    SOURCE = "source"
    NORMALIZE = "normalize"
    SEPARATE = "separate"
    TRANSCRIBE = "transcribe"
    QUANTIZE = "quantize"
    NOTATION = "notation"
    TAB = "tab"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ArtifactRef(Frozen):
    """A file produced by a stage. `path` is POSIX and relative to the work dir."""

    path: str
    sha256: str


class StageOutput(Frozen):
    """Base class for each stage's typed result. Subclasses set `stage`."""

    stage: ClassVar[StageName]

    def artifacts(self) -> list[ArtifactRef]:
        """Every ArtifactRef held by this output, including inside lists and dicts."""
        refs: list[ArtifactRef] = []
        for field in type(self).model_fields:
            value = getattr(self, field)
            if isinstance(value, ArtifactRef):
                refs.append(value)
            elif isinstance(value, list | tuple):
                refs.extend(v for v in value if isinstance(v, ArtifactRef))
            elif isinstance(value, Mapping):
                refs.extend(v for v in value.values() if isinstance(v, ArtifactRef))
        return refs


class SourceAudio(StageOutput):
    """The uploaded audio file, copied into the work dir unchanged."""

    stage = StageName.SOURCE
    audio: ArtifactRef


class StageManifest(Frozen):
    """Written last into each stage dir; its presence + matching key means the stage is done."""

    stage: StageName
    stage_version: str
    pipeline_version: str
    cache_key: str
    output: dict[str, Any]
    artifacts: list[ArtifactRef]
    created_at: datetime
    duration_s: float
