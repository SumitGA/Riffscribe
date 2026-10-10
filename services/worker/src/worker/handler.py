"""Runs one stage of one job per queue message.

The job's object-storage prefix is the shared work dir: a worker downloads it into a temporary
directory, runs the pipeline up to the message's stage (earlier stages are cache hits, so the
runner needs no changes), uploads what ran and queues the next stage. Any worker can take any
message, and running a message twice is harmless (stages are idempotent, ADR-0001).
"""

import logging
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from pipeline.config import PipelineConfig
from pipeline.errors import InvalidInputError, StageFailedError
from pipeline.runner import RunResult, run_pipeline
from pipeline.stage import Stage
from pipeline.stages import default_stages
from pipeline.stages.normalize import NormalizedAudio
from pipeline.stages.notation import Notation
from pipeline.stages.quantize import QuantizedScore
from pipeline.stages.tab import Tablature
from pipeline.types import StageName
from tabscribe_platform.db import (
    Job,
    JobStatus,
    ResultCache,
    ScoreVersion,
    StageRun,
    StageStatus,
)
from tabscribe_platform.jobqueue import (
    MAX_ATTEMPTS,
    STAGES,
    Delivery,
    JobQueue,
    StageMessage,
    queue_for_stage,
)
from tabscribe_platform.observability import extract_trace, inject_trace, log_context
from tabscribe_platform.storage import ObjectStore, job_prefix
from worker.dedup import full_pipeline_version, result_cache_key
from worker.metrics import JOBS_FINISHED, STAGE_RUNS, STAGE_SECONDS
from worker.notify import Notifier

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("tabscribe.worker")

# Shown to the user when we failed them; the details stay in the logs and stage_runs.
INTERNAL_ERROR_MESSAGE = "Something went wrong while processing this recording. Please try again."
_ACTIVE = (JobStatus.QUEUED, JobStatus.RUNNING)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _Outputs:
    """A finished job's score files (object keys) and the pipeline that made them."""

    pipeline_version: str
    musicxml_key: str
    tab_musicxml_key: str | None
    midi_key: str | None
    sync_key: str | None


@dataclass(frozen=True)
class _Failure:
    retryable: bool
    detail: str  # for logs and stage_runs.last_error
    user_message: str  # for jobs.error_message


class StageWorker:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        store: ObjectStore,
        queue: JobQueue,
        notifier: Notifier,
        *,
        heartbeat_s: float,
        stages: Callable[[], Sequence[Stage[Any]]] = default_stages,
    ) -> None:
        self._sessions = sessions
        self._store = store
        self._queue = queue
        self._notifier = notifier
        self._heartbeat_s = heartbeat_s
        self._stages = stages
        self._pipeline_version = full_pipeline_version(stages())

    def handle(self, delivery: Delivery) -> None:
        """Process one message; always acks or fails it.

        Runs in a span continuing the job's trace, with job_id/stage/attempt on every log line.
        """
        message = delivery.message
        stage = message.stage
        with (
            log_context(job_id=str(message.job_id), stage=stage, attempt=message.attempt),
            _tracer.start_as_current_span(
                f"stage {stage}",
                context=extract_trace(message.trace),
                kind=SpanKind.CONSUMER,
                attributes={
                    "job.id": str(message.job_id),
                    "stage": stage,
                    "attempt": message.attempt,
                },
            ) as span,
        ):
            start = time.perf_counter()
            outcome = self._handle(delivery)
            elapsed = time.perf_counter() - start
            span.set_attribute("stage.outcome", outcome)
            if outcome in ("retried", "failed"):
                span.set_status(Status(StatusCode.ERROR))
            STAGE_RUNS.labels(stage, outcome).inc()
            STAGE_SECONDS.labels(stage, outcome).observe(elapsed)
            logger.info("stage %s", outcome, extra={"duration_s": round(elapsed, 3)})

    def _handle(self, delivery: Delivery) -> str:
        message = delivery.message
        with self._sessions() as session:
            job = self._load(session, message)
            if job is None or job.status not in _ACTIVE:
                # Deleted, already finished, or never submitted: a stale or duplicate message.
                self._queue.ack(delivery)
                return "dropped"
            if message.attempt > MAX_ATTEMPTS:  # its workers kept dying (see JobQueue.receive)
                failure = _Failure(False, "worker stopped responding", INTERNAL_ERROR_MESSAGE)
                return self._fail(session, delivery, job, failure, error_code="stage_failed")
            config = PipelineConfig.model_validate(job.config)
            source_key = job.source_key
            job.status = JobStatus.RUNNING
            self._set_stage(
                session,
                message,
                status=StageStatus.RUNNING,
                attempts=message.attempt,
                started_at=_now(),
                finished_at=None,
            )
            session.commit()

        try:
            with self._heartbeat(delivery):
                result = self._run(message, source_key, config)
        except Exception as exc:
            failure = _classify(exc)
            logger.warning("stage failed: %s", failure.detail, exc_info=failure.retryable)
            with self._sessions() as session:
                job = self._load(session, message)
                if job is None:
                    self._queue.ack(delivery)
                    return "dropped"
                return self._fail(session, delivery, job, failure, error_code=None)

        return self._advance(delivery, result)

    def _run(self, message: StageMessage, source_key: str, config: PipelineConfig) -> RunResult:
        prefix = job_prefix(message.user_id, str(message.job_id))
        stages = list(self._stages())
        names = [str(s.name) for s in stages]
        target = stages[: names.index(message.stage) + 1]
        with tempfile.TemporaryDirectory(prefix="tabscribe-") as tmp:
            source = Path(tmp) / "upload" / Path(source_key).name
            self._store.download_file(source_key, source)
            workdir = Path(tmp) / "work"
            for key in self._store.list_keys(prefix):
                relative = key.removeprefix(prefix)
                # source/ holds the upload; the source stage copies it locally on every run
                # rather than storing a second copy.
                if not relative.startswith(f"{StageName.SOURCE}/"):
                    self._store.download_file(key, workdir / relative)

            result = run_pipeline(source, workdir, config, target)

            for stage_result in result.stages:
                if stage_result.status == "ran" and stage_result.stage is not StageName.SOURCE:
                    self._upload_dir(workdir, str(stage_result.stage), prefix)
            return result

    def _upload_dir(self, workdir: Path, stage: str, prefix: str) -> None:
        # The manifest goes last: a manifest in storage means the stage's files are all there.
        files = sorted((workdir / stage).iterdir(), key=lambda p: p.name == "manifest.json")
        for path in files:
            if path.is_file():
                self._store.upload_file(path, f"{prefix}{stage}/{path.name}")

    def _advance(self, delivery: Delivery, result: RunResult) -> str:
        message = delivery.message
        stage_result = next(r for r in result.stages if r.stage == message.stage)
        index = STAGES.index(message.stage)
        next_stage = STAGES[index + 1] if index + 1 < len(STAGES) else None
        # Once the audio is known, an identical earlier job can finish this one (dedup cache).
        reused = self._reuse(message, result) if message.stage == StageName.NORMALIZE else None
        finished = False
        with self._sessions() as session:
            job = self._load(session, message)
            if job is None or job.status not in _ACTIVE:
                if job is None:
                    # Deleted while this stage ran: remove the files the stage just stored.
                    self._store.delete_prefix(job_prefix(message.user_id, str(message.job_id)))
                self._queue.ack(delivery)
                return "dropped"
            self._set_stage(
                session,
                message,
                status=StageStatus.SKIPPED
                if stage_result.status == "skipped"
                else StageStatus.SUCCEEDED,
                finished_at=_now(),
                duration_s=stage_result.duration_s,
                last_error=None,
            )
            if message.stage == StageName.NORMALIZE:
                job.audio_sha256 = result.output(NormalizedAudio).pcm_sha256
            if reused is not None:
                for stage in STAGES[index + 1 :]:
                    STAGE_RUNS.labels(stage, "cached").inc()
                    self._set_stage(
                        session,
                        message.model_copy(update={"stage": stage}),
                        status=StageStatus.CACHED,
                        attempts=0,
                        finished_at=_now(),
                        duration_s=0.0,
                    )
                self._finish(session, job, reused)
                next_stage, finished = None, True
            elif next_stage is not None:
                self._set_stage(
                    session,
                    message.model_copy(update={"stage": next_stage}),
                    status=StageStatus.QUEUED,
                    attempts=0,
                )
            else:
                self._finish(session, job, self._outputs(job, result))
                finished = True
            session.commit()

        # After the commit, so the next worker sees this stage done. If we crash before the
        # ack, the stage runs again: cache hits, then the same next message (harmless).
        if next_stage is not None:
            next_message = StageMessage(
                job_id=message.job_id,
                user_id=message.user_id,
                stage=next_stage,
                trace=inject_trace(),  # the next stage's span is a child of this one
            )
            self._queue.enqueue(
                queue_for_stage(next_stage), next_message, priority=delivery.priority
            )
        self._queue.ack(delivery)
        if finished:
            JOBS_FINISHED.labels(JobStatus.SUCCEEDED).inc()
            logger.info("job succeeded")
            self._notifier.job_finished(message.user_id, message.job_id, JobStatus.SUCCEEDED)
        return "skipped" if stage_result.status == "skipped" else "succeeded"

    @staticmethod
    def _outputs(job: Job, result: RunResult) -> _Outputs:
        prefix = job_prefix(job.user_id, str(job.id))
        tab = result.outputs.get(Tablature)
        return _Outputs(
            pipeline_version=result.pipeline_version,
            musicxml_key=prefix + result.output(Notation).musicxml.path,
            tab_musicxml_key=prefix + tab.musicxml.path if isinstance(tab, Tablature) else None,
            midi_key=prefix + result.output(QuantizedScore).midi.path,
            sync_key=prefix + result.output(Notation).sync.path,
        )

    def _finish(self, session: Session, job: Job, outputs: _Outputs) -> None:
        session.execute(
            insert(ScoreVersion)
            .values(
                job_id=job.id,
                user_id=job.user_id,
                version=0,  # the pipeline's output; the editor's saves are 1, 2, ...
                musicxml_key=outputs.musicxml_key,
                tab_musicxml_key=outputs.tab_musicxml_key,
                midi_key=outputs.midi_key,
                sync_key=outputs.sync_key,
            )
            .on_conflict_do_nothing(index_elements=["job_id", "version"])
        )
        if job.audio_sha256 is not None:
            key = result_cache_key(
                job.user_id, job.audio_sha256, outputs.pipeline_version, job.config
            )
            session.execute(
                insert(ResultCache).values(key=key, job_id=job.id).on_conflict_do_nothing()
            )
        job.status = JobStatus.SUCCEEDED
        job.pipeline_version = outputs.pipeline_version
        job.finished_at = _now()

    def _reuse(self, message: StageMessage, result: RunResult) -> _Outputs | None:
        """Copy the results of an identical earlier job of this user, if there is one.

        None (run the stages as usual) when there's no such job or its files are gone, e.g.
        removed by a storage lifecycle rule.
        """
        audio_sha256 = result.output(NormalizedAudio).pcm_sha256
        with self._sessions() as session:
            job = self._load(session, message)
            if job is None:
                return None
            key = result_cache_key(
                message.user_id, audio_sha256, self._pipeline_version, job.config
            )
            row = session.execute(
                select(Job, ScoreVersion)
                .join(ResultCache, ResultCache.job_id == Job.id)
                .join(ScoreVersion, (ScoreVersion.job_id == Job.id) & (ScoreVersion.version == 0))
                .where(
                    ResultCache.key == key,
                    Job.user_id == message.user_id,
                    Job.status == JobStatus.SUCCEEDED,
                    Job.id != message.job_id,
                )
                .limit(1)
            ).first()
        if row is None:
            return None
        cached, score = row
        if score.musicxml_key is None:
            return None

        old = job_prefix(message.user_id, str(cached.id))
        new = job_prefix(message.user_id, str(message.job_id))
        later = set(STAGES[STAGES.index(StageName.NORMALIZE) + 1 :])
        try:
            keys = [k for k in self._store.list_keys(old) if k[len(old) :].split("/")[0] in later]
            needed = {
                score.musicxml_key,
                score.midi_key,
                score.tab_musicxml_key,
                score.sync_key,
            } - {None}
            if not needed <= set(keys):
                logger.info("cached job %s has lost files; running the stages", cached.id)
                return None
            for k in keys:
                self._store.copy(k, new + k[len(old) :])
        except Exception:
            logger.exception("could not reuse job %s; running the stages", cached.id)
            return None

        def moved(k: str) -> str:
            return new + k[len(old) :]

        musicxml_key = score.musicxml_key
        logger.info("job %s reuses the results of job %s", message.job_id, cached.id)
        return _Outputs(
            pipeline_version=self._pipeline_version,
            musicxml_key=moved(musicxml_key),
            tab_musicxml_key=moved(score.tab_musicxml_key) if score.tab_musicxml_key else None,
            midi_key=moved(score.midi_key) if score.midi_key else None,
            sync_key=moved(score.sync_key) if score.sync_key else None,
        )

    def _fail(
        self,
        session: Session,
        delivery: Delivery,
        job: Job,
        failure: _Failure,
        *,
        error_code: str | None,
    ) -> str:
        message = delivery.message
        dead = not failure.retryable or message.attempt >= MAX_ATTEMPTS
        self._set_stage(
            session,
            message,
            status=StageStatus.FAILED if dead else StageStatus.QUEUED,
            attempts=min(message.attempt, MAX_ATTEMPTS),
            finished_at=_now(),
            last_error=failure.detail[:4000],
        )
        if dead:
            job.status = JobStatus.FAILED
            job.error_code = error_code or (
                "stage_failed" if failure.retryable else "invalid_input"
            )
            job.error_message = failure.user_message
            job.finished_at = _now()
        # The database first: if we crash before telling the queue, the message comes back,
        # and a failed job's message is dropped.
        session.commit()
        self._queue.fail(delivery, failure.detail, retry=failure.retryable)
        if not dead:
            return "retried"
        JOBS_FINISHED.labels(JobStatus.FAILED).inc()
        logger.warning("job failed", extra={"error_code": job.error_code})
        self._notifier.job_finished(message.user_id, message.job_id, JobStatus.FAILED)
        return "failed"

    @staticmethod
    def _load(session: Session, message: StageMessage) -> Job | None:
        query = select(Job).where(Job.id == message.job_id, Job.user_id == message.user_id)
        return session.scalars(query).first()

    @staticmethod
    def _set_stage(session: Session, message: StageMessage, **values: Any) -> None:
        session.execute(
            insert(StageRun)
            .values(job_id=message.job_id, stage=message.stage, **values)
            .on_conflict_do_update(index_elements=["job_id", "stage"], set_=values)
        )

    @contextmanager
    def _heartbeat(self, delivery: Delivery) -> Iterator[None]:
        """Keep the message ours while a long stage runs (JobQueue.extend)."""
        stop = threading.Event()

        def beat() -> None:
            while not stop.wait(self._heartbeat_s):
                try:
                    self._queue.extend(delivery)
                except LookupError:
                    logger.warning("lost the message for job %s", delivery.message.job_id)
                    return
                except Exception:
                    logger.exception("heartbeat failed; will retry")

        thread = threading.Thread(target=beat, name="heartbeat", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join()


def _classify(exc: Exception) -> _Failure:
    if isinstance(exc, StageFailedError) and not exc.retryable:
        # Bad input (not audio, too long, silent): tell the user why, without the details.
        cause = exc.__cause__
        reason = cause.user_message if isinstance(cause, InvalidInputError) else "invalid input"
        return _Failure(False, str(exc), f"This recording can't be transcribed: {reason}.")
    return _Failure(True, f"{type(exc).__name__}: {exc}", INTERNAL_ERROR_MESSAGE)


def remove_stale_tempdirs(max_age_s: float = 24 * 3600) -> None:
    """Delete work dirs a killed worker left behind in the temp directory."""
    cutoff = time.time() - max_age_s
    for path in Path(tempfile.gettempdir()).glob("tabscribe-*"):
        if path.is_dir() and path.stat().st_mtime < cutoff:
            shutil.rmtree(path, ignore_errors=True)
