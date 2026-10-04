from pipeline.types import StageName


class PipelineError(Exception):
    """A pipeline was wired or invoked incorrectly."""


class InvalidInputError(Exception):
    """The user's input can never succeed (not audio, too long, silent). Do not retry."""


class StageFailedError(PipelineError):
    """A stage raised while running. Its previous output, if any, is left untouched."""

    def __init__(self, stage: StageName, cause: BaseException) -> None:
        super().__init__(f"stage '{stage}' failed: {cause}")
        self.stage = stage
        # Workers retry transient failures (max 3 attempts) but never bad input.
        self.retryable = not isinstance(cause, InvalidInputError)
