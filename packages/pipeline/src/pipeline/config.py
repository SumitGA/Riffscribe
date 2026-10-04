from enum import StrEnum

from pydantic import Field

from pipeline.types import Frozen


class Instrument(StrEnum):
    GUITAR = "guitar"
    PIANO = "piano"


class Tuning(StrEnum):
    STANDARD = "standard"  # E2 A2 D3 G3 B3 E4
    DROP_D = "drop_d"  # D2 A2 D3 G3 B3 E4


class PipelineConfig(Frozen):
    """Every setting that can change a result. All of it feeds every stage's cache key."""

    instrument: Instrument
    # Free tier limit; the paid tier will raise it.
    max_duration_s: float = Field(default=300.0, gt=0)
    # Isolate the instrument with Demucs before transcribing (optional install; TD-1).
    separation: bool = False
    # Guitar only: used by the tab stage.
    tuning: Tuning = Tuning.STANDARD
    capo: int = Field(default=0, ge=0, le=12)
