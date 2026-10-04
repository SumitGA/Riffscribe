from enum import StrEnum

from pipeline.types import Frozen


class Instrument(StrEnum):
    GUITAR = "guitar"
    PIANO = "piano"


class PipelineConfig(Frozen):
    """Every setting that can change a result. All of it feeds every stage's cache key."""

    instrument: Instrument
