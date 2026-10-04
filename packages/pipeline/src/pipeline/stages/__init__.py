from typing import Any

from pipeline.stage import Stage


def default_stages() -> list[Stage[Any]]:
    """The production stage order after `source`. Stages are added as they are implemented."""
    return []
