from pipeline.types import StageName


class PipelineError(Exception):
    """A pipeline was wired or invoked incorrectly."""


class StageFailedError(PipelineError):
    """A stage raised while running. Its previous output, if any, is left untouched."""

    def __init__(self, stage: StageName, cause: BaseException) -> None:
        super().__init__(f"stage '{stage}' failed: {cause}")
        self.stage = stage
