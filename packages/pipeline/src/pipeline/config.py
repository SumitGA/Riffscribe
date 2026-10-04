from enum import StrEnum

from pydantic import Field

from pipeline.types import Frozen


class Instrument(StrEnum):
    GUITAR = "guitar"
    PIANO = "piano"


class PipelineConfig(Frozen):
    """Every setting that can change a result. All of it feeds every stage's cache key."""

    instrument: Instrument
    # Free tier limit; the paid tier will raise it.
    max_duration_s: float = Field(default=300.0, gt=0)
