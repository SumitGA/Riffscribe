"""Request and response bodies."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tabscribe_platform.db import JOB_NAME_MAX, JobStatus, StageStatus, VersionStatus

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

    # The second flag: in responses, defaulted fields are always present, so the schema says so.
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    instrument: Instrument
    tuning: Tuning = Tuning.STANDARD  # guitar only
    capo: int = Field(default=0, ge=0, le=12)  # guitar only


class CreateJobRequest(JobOptions):
    content_type: str = Field(description=f"One of: {', '.join(sorted(AUDIO_TYPES))}")
    size_bytes: int = Field(gt=0, description="Size of the file the client will upload")
    name: str | None = Field(default=None, max_length=JOB_NAME_MAX, description="Optional title")

    @field_validator("name")
    @classmethod
    def _blank_name_is_none(cls, name: str | None) -> str | None:
        return name.strip() or None if name is not None else None


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
    # sync.json ({"bar_starts_ms": [...]}): when each bar starts in the uploaded audio, for
    # playing the user's own copy of the recording in step with the score
    sync: PresignedRequestOut | None


class JobOut(BaseModel):
    id: uuid.UUID
    name: str | None
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
    name: str | None
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


EDIT_OPS = ("set_position", "set_pitch", "delete", "add", "set_duration")
MAX_EDITS = 500


class EditOp(BaseModel):
    """One edit operation (ADR-0011). The API checks only its kind; the worker checks the rest
    against the score (the API never runs pipeline code)."""

    model_config = ConfigDict(extra="allow")

    op: Literal["set_position", "set_pitch", "delete", "add", "set_duration"]


class CreateVersionRequest(BaseModel):
    # The latest version the edits were made on; saving against an older one is a conflict.
    base_version: int = Field(ge=0)
    edits: list[EditOp] = Field(max_length=MAX_EDITS)
    # Restore: start from this (older) version's content instead of base_version's.
    from_version: int | None = Field(default=None, ge=0)


class VersionOut(BaseModel):
    version: int
    status: VersionStatus
    base_version: int | None  # the version whose content the edits were applied to
    error_message: str | None
    created_at: datetime
    # Downloads, once the version is ready (only when asked for one version).
    outputs: JobOutputs | None = None


class VersionList(BaseModel):
    versions: list[VersionOut]  # newest first
