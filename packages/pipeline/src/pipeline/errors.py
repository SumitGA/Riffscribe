from pipeline.types import StageName


class PipelineError(Exception):
    """A pipeline was wired or invoked incorrectly."""


class InvalidInputError(Exception):
    """The user's input can never succeed (not audio, too long, silent). Do not retry.

    `user_message` is short and safe to show the user; `detail` (e.g. ffmpeg's stderr, which
    names server paths) is only for logs and the CLI, which print both.
    """

    def __init__(self, user_message: str, *, detail: str | None = None) -> None:
        super().__init__(f"{user_message}: {detail}" if detail else user_message)
        self.user_message = user_message
        self.detail = detail


class StageFailedError(PipelineError):
    """A stage raised while running. Its previous output, if any, is left untouched."""

    def __init__(self, stage: StageName, cause: BaseException) -> None:
        super().__init__(f"stage '{stage}' failed: {cause}")
        self.stage = stage
        # Workers retry transient failures (max 3 attempts) but never bad input.
        self.retryable = not isinstance(cause, InvalidInputError)
