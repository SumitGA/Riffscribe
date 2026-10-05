"""Request and response bodies."""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from tabscribe_platform.db import JobStatus, StageStatus

# Upload types the API accepts, and the file extension the stored upload gets. The normalize
# stage decodes with ffmpeg and rejects anything that isn't really audio.
AUDIO_TYPES = {
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/flac": "flac",
    "audio/ogg": "ogg",
}


class Instrument(StrEnum):
    GUITAR = "guitar"
    PIANO = "piano"


class Tuning(StrEnum):
    STANDARD = "standard"
    DROP_D = "drop_d"


class JobOptions(BaseModel):
    """What the client can choose. Stored as the job's config and read by the worker as the
    pipeline's `PipelineConfig` (a test keeps the two compatible). The API doesn't import the
    pipeline: it would pull the ML libraries into the API.
    """

    model_config = ConfigDict(extra="forbid")

    instrument: Instrument
    tuning: Tuning = Tuning.STANDARD  # guitar only
    capo: int = Field(default=0, ge=0, le=12)  # guitar only


class CreateJobRequest(JobOptions):
    content_type: str = Field(description=f"One of: {', '.join(sorted(AUDIO_TYPES))}")
    size_bytes: int = Field(gt=0, description="Size of the file the client will upload")


class PresignedRequestOut(BaseModel):
    method: str
    url: str
    headers: dict[str, str]
    expires_in_s: int


class StageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    status: StageStatus
    attempts: int
    started_at: datetime | None
    finished_at: datetime | None


class JobError(BaseModel):
    code: str
    message: str | None


class JobOutputs(BaseModel):
    """Presigned downloads of the job's latest score version."""

    version: int
    musicxml: PresignedRequestOut
    tab_musicxml: PresignedRequestOut | None
    midi: PresignedRequestOut | None


class JobOut(BaseModel):
    id: uuid.UUID
    status: JobStatus
    options: JobOptions
    created_at: datetime
    submitted_at: datetime | None
    finished_at: datetime | None
    pipeline_version: str | None
    error: JobError | None
    stages: list[StageOut]
    outputs: JobOutputs | None


class CreateJobResponse(BaseModel):
    job: JobOut
    upload: PresignedRequestOut


class JobSummary(BaseModel):
    id: uuid.UUID
    status: JobStatus
    instrument: Instrument
    created_at: datetime


class JobList(BaseModel):
    jobs: list[JobSummary]
    # Pass as `cursor` to get the next page; None on the last page.
    next_cursor: str | None


class MeOut(BaseModel):
    user_id: str
    jobs_this_month: int
    jobs_per_month: int
