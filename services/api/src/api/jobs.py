"""Job endpoints (CLAUDE.md job flow, steps 1-3 and 5).

Every query filters by the caller's user ID; another user's job is a 404, never a 403, so job IDs
can't be probed. Audio never passes through the API: clients upload with a presigned PUT.
"""

import base64
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from opentelemetry import trace
from sqlalchemy import Select, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from api.auth import CurrentUserDep
from api.deps import ApiSettingsDep, LimiterDep, QueueDep, SessionDep, StoreDep
from api.schemas import (
    AUDIO_TYPES,
    CreateJobRequest,
    CreateJobResponse,
    JobError,
    JobList,
    JobOptions,
    JobOut,
    JobOutputs,
    JobSummary,
    PresignedRequestOut,
    StageOut,
)
from tabscribe_platform.db import Job, JobStatus, ScoreVersion, StageRun, User
from tabscribe_platform.jobqueue import STAGES, Priority, StageMessage, queue_for_stage
from tabscribe_platform.observability import inject_trace
from tabscribe_platform.storage import ObjectStore, PresignedRequest, job_key

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "job not found")


def _log(job_id: uuid.UUID, event: str, level: int = logging.INFO) -> None:
    """Log a job event and tag the request's span, so logs and traces both find the job."""
    trace.get_current_span().set_attribute("job.id", str(job_id))
    logger.log(level, event, extra={"job_id": str(job_id)})


def _presigned(request: PresignedRequest) -> PresignedRequestOut:
    return PresignedRequestOut(
        method=request.method,
        url=request.url,
        headers=request.headers,
        expires_in_s=request.expires_in_s,
    )


def _own_job(user_id: str, job_id: uuid.UUID) -> Select[Job]:
    return select(Job).where(Job.id == job_id, Job.user_id == user_id)


def _job_out(session: Session, store: ObjectStore, job: Job) -> JobOut:
    runs = session.scalars(select(StageRun).where(StageRun.job_id == job.id)).all()
    runs = sorted(runs, key=lambda r: STAGES.index(r.stage) if r.stage in STAGES else len(STAGES))
    outputs = None
    if job.status is JobStatus.SUCCEEDED:
        score = session.scalars(
            select(ScoreVersion)
            .where(ScoreVersion.job_id == job.id, ScoreVersion.user_id == job.user_id)
            .order_by(ScoreVersion.version.desc())
            .limit(1)
        ).first()
        if score is not None:
            outputs = JobOutputs(
                version=score.version,
                musicxml=_presigned(store.presign_get(score.musicxml_key, "score.musicxml")),
                tab_musicxml=_presigned(store.presign_get(score.tab_musicxml_key, "tab.musicxml"))
                if score.tab_musicxml_key
                else None,
                midi=_presigned(store.presign_get(score.midi_key, "score.mid"))
                if score.midi_key
                else None,
            )
    return JobOut(
        id=job.id,
        name=job.name,
        status=job.status,
        options=JobOptions.model_validate(job.config),
        created_at=job.created_at,
        submitted_at=job.submitted_at,
        finished_at=job.finished_at,
        pipeline_version=job.pipeline_version,
        error=JobError(code=job.error_code, message=job.error_message) if job.error_code else None,
        stages=[StageOut.model_validate(run) for run in runs],
        outputs=outputs,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_job(
    body: CreateJobRequest,
    user: CurrentUserDep,
    session: SessionDep,
    store: StoreDep,
    limiter: LimiterDep,
    limits: ApiSettingsDep,
) -> CreateJobResponse:
    """Step 1: create a job and get a presigned URL to upload the audio to."""
    if not limiter.hit(user.id, "create_job", limits.job_creates_per_minute, window_s=60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many new jobs; slow down")
    extension = AUDIO_TYPES.get(body.content_type)
    if extension is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"unsupported audio type {body.content_type!r}"
        )
    if body.size_bytes > limits.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"uploads are limited to {limits.max_upload_bytes} bytes",
        )

    # First request from this user: remember them (the auth provider owns the account).
    session.execute(insert(User).values(id=user.id).on_conflict_do_nothing())
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        user_id=user.id,
        name=body.name,
        config=JobOptions.model_validate(
            body.model_dump(include=set(JobOptions.model_fields))
        ).model_dump(mode="json"),
        source_key=job_key(user.id, str(job_id), "source", f"upload.{extension}"),
        source_content_type=body.content_type,
        source_size_bytes=body.size_bytes,
    )
    session.add(job)
    session.commit()
    _log(job_id, "job created")
    upload = store.presign_put(job.source_key, body.content_type)
    return CreateJobResponse(job=_job_out(session, store, job), upload=_presigned(upload))


@router.post("/{job_id}/submit")
def submit_job(
    job_id: uuid.UUID,
    user: CurrentUserDep,
    session: SessionDep,
    store: StoreDep,
    queue: QueueDep,
    limiter: LimiterDep,
    limits: ApiSettingsDep,
) -> JobOut:
    """Step 3: check the upload and the quota, then queue the job. Safe to repeat.

    Only size, type and quota are checked here (one HEAD request). Duration and format need
    the audio decoded, so the normalize stage checks them and fails the job if they're wrong.
    """
    # FOR UPDATE: two concurrent submits of one job can't both take quota and enqueue it.
    job = session.scalars(_own_job(user.id, job_id).with_for_update()).first()
    if job is None:
        raise _NOT_FOUND
    if job.status is not JobStatus.PENDING_UPLOAD:
        return _job_out(session, store, job)  # already submitted: nothing to do

    upload = store.head(job.source_key)
    if upload is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "upload the audio before submitting")
    if upload.size > limits.max_upload_bytes:
        job.status = JobStatus.FAILED
        job.error_code = "invalid_input"
        job.error_message = f"the upload is larger than {limits.max_upload_bytes} bytes"
        job.finished_at = datetime.now(UTC)
        session.commit()
        _log(job.id, "upload larger than the limit", logging.WARNING)
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, job.error_message)

    if not limiter.take_monthly_job(user.id, limits.free_jobs_per_month):
        _log(job.id, "monthly quota used up")
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"monthly limit of {limits.free_jobs_per_month} jobs reached",
        )
    job.status = JobStatus.QUEUED
    job.source_size_bytes = upload.size
    job.submitted_at = datetime.now(UTC)
    session.commit()

    # Enqueued after the commit, so a worker never sees the job before it is `queued`.
    first = STAGES[0]
    # The trace continues in the workers: one trace per job, rooted at this request.
    message = StageMessage(job_id=job.id, user_id=user.id, stage=first, trace=inject_trace())
    try:
        # Paid tier (later) gets Priority.HIGH.
        queue.enqueue(queue_for_stage(first), message, priority=Priority.NORMAL)
    except Exception as exc:
        # Undo, so the client can simply submit again.
        job.status = JobStatus.PENDING_UPLOAD
        job.submitted_at = None
        session.commit()
        limiter.refund_monthly_job(user.id)
        logger.exception("could not enqueue job", extra={"job_id": str(job.id)})
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "queue unavailable; retry"
        ) from exc
    _log(job.id, "job submitted")
    return _job_out(session, store, job)


@router.get("/{job_id}")
def get_job(
    job_id: uuid.UUID, user: CurrentUserDep, session: SessionDep, store: StoreDep
) -> JobOut:
    """Step 5: poll a job's status; once it has succeeded, `outputs` has download links."""
    job = session.scalars(_own_job(user.id, job_id)).first()
    if job is None:
        raise _NOT_FOUND
    return _job_out(session, store, job)


# Keyset pagination on (created_at, id): stable while new jobs arrive. The cursor is opaque
# (base64url), so clients don't parse it and a timestamp's "+" can't get mangled in a URL.
def _cursor(job: Job) -> str:
    return base64.urlsafe_b64encode(f"{job.created_at.isoformat()}|{job.id}".encode()).decode()


def _parse_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created_at, job_id = base64.urlsafe_b64decode(cursor).decode().split("|")
        return datetime.fromisoformat(created_at), uuid.UUID(job_id)
    except ValueError as exc:  # also covers bad base64 (binascii.Error) and bad UTF-8
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid cursor") from exc


@router.get("")
def list_jobs(
    user: CurrentUserDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: str | None = None,
) -> JobList:
    """The caller's jobs, newest first (uses the jobs(user_id, created_at) index)."""
    query = select(Job).where(Job.user_id == user.id)
    if cursor is not None:
        query = query.where(tuple_(Job.created_at, Job.id) < _parse_cursor(cursor))
    jobs = session.scalars(
        query.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)
    ).all()
    page = jobs[:limit]
    last = page[-1] if len(jobs) > limit else None
    return JobList(
        jobs=[
            JobSummary(
                id=j.id,
                name=j.name,
                status=j.status,
                instrument=j.config["instrument"],
                created_at=j.created_at,
            )
            for j in page
        ],
        next_cursor=_cursor(last) if last else None,
    )
