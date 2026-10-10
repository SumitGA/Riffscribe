"""Rendering edited score versions (ADR-0011): RENDER messages on the CPU queue.

A pending version holds the edit operations and its base version. The worker loads the base
version's editable document (`score.json`; for version 0 it is built from the job's stage
artifacts), applies the edits with `pipeline.edits`, renders the files and stores them under
`users/{user}/jobs/{job}/versions/{n}/`. Bad edits fail the version with a message for the
user; anything else is retried like a stage.
"""

import json
import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from pipeline.config import Instrument, PipelineConfig
from pipeline.edits import EditableScore, EditList, apply_edits, render
from pipeline.errors import InvalidInputError
from pipeline.score import Score
from pipeline.stages.tab import TabFile
from tabscribe_platform.db import Job, ScoreVersion, VersionStatus
from tabscribe_platform.jobqueue import Delivery, FailOutcome, JobQueue
from tabscribe_platform.storage import ObjectStore, job_prefix

logger = logging.getLogger(__name__)

INTERNAL_ERROR_MESSAGE = "Something went wrong saving your changes. Try again."


class VersionRenderer:
    def __init__(
        self, sessions: Callable[[], Session], store: ObjectStore, queue: JobQueue
    ) -> None:
        self._sessions = sessions
        self._store = store
        self._queue = queue

    def render(self, delivery: Delivery) -> str:
        message = delivery.message
        with self._sessions() as session:
            version = self._version(session, message.job_id, message.user_id, message.version)
            job = session.get(Job, message.job_id)
            if version is None or version.status is not VersionStatus.PENDING or job is None:
                self._queue.ack(delivery)  # deleted, or already rendered: a stale message
                return "dropped"
            base = self._version(session, job.id, job.user_id, version.base_version)
            if base is None or base.status is not VersionStatus.READY:
                return self._finish(
                    delivery, failed="The version these changes were based on is gone."
                )
            prefix = job_prefix(job.user_id, str(job.id))
            config = PipelineConfig.model_validate(job.config)
            base_document_key, edits = base.document_key, version.edits
            number = version.version

        try:
            document = self._document(prefix, base_document_key, config.instrument)
            edited = apply_edits(
                document, EditList.model_validate({"edits": (edits or {}).get("edits", [])}).edits
            )
            keys = self._render_and_upload(edited, f"{prefix}versions/{number}/")
        except (InvalidInputError, ValidationError) as exc:
            reason = (
                exc.user_message if isinstance(exc, InvalidInputError) else "unreadable changes"
            )
            logger.info("edit refused: %s", reason)
            return self._finish(delivery, failed=f"These changes can't be saved: {reason}.")
        except Exception as exc:
            logger.warning("render failed: %s", exc, exc_info=True)
            if self._queue.fail(delivery, str(exc)) is FailOutcome.RETRY:
                return "retried"
            return self._finish(delivery, failed=INTERNAL_ERROR_MESSAGE, acked=True)
        return self._finish(delivery, keys=keys)

    @staticmethod
    def _version(
        session: Session, job_id: object, user_id: str, number: int | None
    ) -> ScoreVersion | None:
        if number is None:
            return None
        return session.scalars(
            select(ScoreVersion).where(
                ScoreVersion.job_id == job_id,
                ScoreVersion.user_id == user_id,
                ScoreVersion.version == number,
            )
        ).first()

    def _document(
        self, prefix: str, document_key: str | None, instrument: Instrument
    ) -> EditableScore:
        """The base version's editable document; version 0's is built from its stage files."""
        if document_key is not None:
            return EditableScore.model_validate_json(self._read(document_key))
        score = Score.model_validate_json(self._read(f"{prefix}quantize/quantized.json"))
        tab = None
        if instrument is Instrument.GUITAR:
            tab = TabFile.model_validate_json(self._read(f"{prefix}tab/tab.json"))
        manifest = json.loads(self._read(f"{prefix}normalize/manifest.json"))
        return EditableScore(
            instrument=instrument,
            score=score,
            tab=tab,
            trim_start_s=float(manifest["output"].get("trim_start_s", 0.0)),
        )

    def _read(self, key: str) -> str:
        with tempfile.TemporaryDirectory(prefix="tabscribe-render-") as tmp:
            path = Path(tmp) / "file"
            self._store.download_file(key, path)
            return path.read_text()

    def _render_and_upload(self, document: EditableScore, prefix: str) -> dict[str, str]:
        with tempfile.TemporaryDirectory(prefix="tabscribe-render-") as tmp:
            files = render(document, Path(tmp))
            keys = {}
            for name, path in files.items():
                keys[name] = f"{prefix}{name}"
                self._store.upload_file(path, keys[name])
            return keys

    def _finish(
        self,
        delivery: Delivery,
        *,
        keys: dict[str, str] | None = None,
        failed: str | None = None,
        acked: bool = False,
    ) -> str:
        message = delivery.message
        with self._sessions() as session:
            version = self._version(session, message.job_id, message.user_id, message.version)
            if version is not None:
                if keys is not None:
                    version.status = VersionStatus.READY
                    version.document_key = keys["score.json"]
                    version.musicxml_key = keys["score.musicxml"]
                    version.tab_musicxml_key = keys.get("tab.musicxml")
                    version.midi_key = keys["quantized.mid"]
                    version.sync_key = keys["sync.json"]
                else:
                    version.status = VersionStatus.FAILED
                    version.error_message = failed
                session.commit()
        if not acked:
            self._queue.ack(delivery)
        logger.info("version %s %s", message.version, "ready" if keys else "failed")
        return "succeeded" if keys else "failed"
