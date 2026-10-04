from typing import Any

from pipeline.stage import Stage
from pipeline.stages.normalize import NormalizeStage
from pipeline.stages.notation import NotationStage
from pipeline.stages.quantize import QuantizeStage
from pipeline.stages.tab import TabStage
from pipeline.stages.transcribe import TranscribeStage


def default_stages() -> list[Stage[Any]]:
    """The production stage order after `source`. Stages are added as they are implemented."""
    return [NormalizeStage(), TranscribeStage(), QuantizeStage(), NotationStage(), TabStage()]
