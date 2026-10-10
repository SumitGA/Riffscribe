"""Score versions: the editor's saves (ADR-0011).

`POST /jobs/{id}/versions` stores the edit operations as a pending version and queues a render;
the worker applies them and makes the version ready (or failed, with a reason). Versions are
never overwritten: restoring an old one creates a new version with its content.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from api.auth import CurrentUserDep
from api.deps import QueueDep, SessionDep, StoreDep
from api.jobs import outputs_of
from api.schemas import CreateVersionRequest, VersionList, VersionOut
from tabscribe_platform.db import Job, JobStatus, ScoreVersion, VersionStatus
from tabscribe_platform.jobqueue import RENDER, Priority, QueueName, StageMessage
from tabscribe_platform.observability import inject_trace
from tabscribe_platform.storage import ObjectStore

router = APIRouter(prefix="/jobs", tags=["versions"])
logger = logging.getLogger(__name__)
_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "job not found")


def _out(version: ScoreVersion, store: ObjectStore | None = None) -> VersionOut:
    return VersionOut(
        version=version.version,
        status=version.status,
        base_version=version.base_version,
        error_message=version.error_message,
        created_at=version.created_at,
        outputs=outputs_of(store, version) if store is not None else None,
    )


@router.post("/{job_id}/versions", status_code=status.HTTP_202_ACCEPTED)
def create_version(
    job_id: uuid.UUID,
    body: CreateVersionRequest,
    user: CurrentUserDep,
    session: SessionDep,
    queue: QueueDep,
) -> VersionOut:
    """Save edits as a new version. 409 if `base_version` isn't the latest (another save won)
    or the previous save is still being rendered; the app reloads and tries again."""
    # FOR UPDATE on the job: two saves can't both become the same new version.
    job = session.scalars(
        select(Job).where(Job.id == job_id, Job.user_id == user.id).with_for_update()
    ).first()
    if job is None:
        raise _NOT_FOUND
    if job.status is not JobStatus.SUCCEEDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "the transcription isn't finished yet")
    versions = {
        v.version: v
        for v in session.scalars(select(ScoreVersion).where(ScoreVersion.job_id == job.id))
    }
    latest = versions[max(versions)]
    if latest.status is VersionStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "the last changes are still being saved")
    if body.base_version != latest.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"version {latest.version} is newer than your copy"
        )
    source = body.from_version if body.from_version is not None else body.base_version
    if versions.get(source) is None or versions[source].status is not VersionStatus.READY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"version {source} can't be restored")

    version = ScoreVersion(
        job_id=job.id,
        user_id=user.id,
        version=latest.version + 1,
        status=VersionStatus.PENDING,
        base_version=source,  # the content the edits apply to
        edits={"edits": [e.model_dump() for e in body.edits], "saved_on": body.base_version},
    )
    session.add(version)
    session.commit()
    message = StageMessage(
        job_id=job.id, user_id=user.id, stage=RENDER, version=version.version, trace=inject_trace()
    )
    try:
        queue.enqueue(QueueName.CPU, message, priority=Priority.NORMAL)
    except Exception as exc:
        session.delete(version)  # so the client can simply save again
        session.commit()
        logger.exception("could not enqueue render", extra={"job_id": str(job.id)})
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "queue unavailable; retry"
        ) from exc
    logger.info("version %s queued", version.version, extra={"job_id": str(job.id)})
    return _out(version)


@router.get("/{job_id}/versions")
def list_versions(job_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> VersionList:
    if (
        session.scalars(select(Job.id).where(Job.id == job_id, Job.user_id == user.id)).first()
        is None
    ):
        raise _NOT_FOUND
    rows = session.scalars(
        select(ScoreVersion)
        .where(ScoreVersion.job_id == job_id, ScoreVersion.user_id == user.id)
        .order_by(ScoreVersion.version.desc())
    )
    return VersionList(versions=[_out(v) for v in rows])


@router.get("/{job_id}/versions/{number}")
def get_version(
    job_id: uuid.UUID, number: int, user: CurrentUserDep, session: SessionDep, store: StoreDep
) -> VersionOut:
    version = session.scalars(
        select(ScoreVersion).where(
            ScoreVersion.job_id == job_id,
            ScoreVersion.user_id == user.id,
            ScoreVersion.version == number,
        )
    ).first()
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    return _out(version, store)
