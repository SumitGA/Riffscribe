import os
import socket
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from tabscribe_platform.jobqueue import QueueName


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


class WorkerSettings(BaseSettings):
    """`WORKER_*` environment variables. Shared settings are `tabscribe_platform`'s."""

    model_config = SettingsConfigDict(env_prefix="WORKER_", frozen=True, extra="ignore")

    # Which queues this worker serves, comma-separated. The MVP's one CPU pool serves both;
    # GPU workers would set WORKER_QUEUES=ml and CPU workers WORKER_QUEUES=cpu.
    queues: Annotated[list[QueueName], NoDecode] = Field(
        default=[QueueName.CPU, QueueName.ML], min_length=1
    )
    # Consumer name in the queue; unique per process.
    id: str = Field(default_factory=_default_worker_id)
    # How long one receive call blocks before trying the next queue.
    poll_s: float = Field(default=2.0, gt=0)

    @field_validator("queues", mode="before")
    @classmethod
    def _comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value
