from typing import Any

from pipeline.stage import Stage
from pipeline.stages.normalize import NormalizeStage


def default_stages() -> list[Stage[Any]]:
    """The production stage order after `source`. Stages are added as they are implemented."""
    return [NormalizeStage()]
