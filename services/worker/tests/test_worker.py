"""The worker against real Postgres, Redis and S3, running the real pipeline on short clips."""

import json
import logging
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import redis
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import REGISTRY
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

import pipeline.runner
import worker.handler
from pipeline.runner import RunResult
from tabscribe_platform.db import (
    Job,
    JobStatus,
    ScoreVersion,
    StageRun,
    StageStatus,
    User,
    VersionStatus,
    make_session_factory,
)
from tabscribe_platform.jobqueue import (
    MAX_ATTEMPTS,
    RENDER,
    QueueName,
    RedisJobQueue,
    StageMessage,
)
from tabscribe_platform.observability import JsonFormatter, inject_trace
from tabscribe_platform.storage import ObjectStore, job_key, job_prefix
from worker.handler import INTERNAL_ERROR_MESSAGE, StageWorker
from worker.settings import WorkerSettings

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[3] / "packages/pipeline/tests/fixtures"
GUITAR_CLIP = FIXTURES / "guitarset/05_BN1-129-Eb_solo.flac"  # 20 s
PIANO_CLIP = FIXTURES / "piano_synth/melody_chords_100bpm.flac"


class FakeClock:
    now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, uuid.UUID, JobStatus]] = []

    def job_finished(self, user_id: str, job_id: uuid.UUID, status: JobStatus) -> None:
        self.sent.append((user_id, job_id, status))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def queue(
    redis_client: "redis.Redis", key_prefix: str, clock: FakeClock, job_queue: RedisJobQueue
) -> RedisJobQueue:
    """Same keys as `job_queue` (cleaned up afterwards), with a fake clock for retry delays."""
    return RedisJobQueue(redis_client, visibility_timeout_s=60, prefix=key_prefix, clock=clock)


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def stage_worker(
    db: Engine, object_store: ObjectStore, queue: RedisJobQueue, notifier: RecordingNotifier
) -> StageWorker:
    return StageWorker(make_session_factory(db), object_store, queue, notifier, heartbeat_s=20)


SubmitJob = Callable[..., uuid.UUID]


@pytest.fixture
def submit_job(
    db: Engine, object_store: ObjectStore, queue: RedisJobQueue, s3_user: str, tmp_path: Path
) -> SubmitJob:
    """What the API does: a queued job with its upload in storage and `normalize` enqueued."""

    def submit(
        clip: Path | bytes = GUITAR_CLIP,
        instrument: str = "guitar",
        *,
        user_id: str = s3_user,
        config: dict[str, Any] | None = None,
        **job: Any,
    ) -> uuid.UUID:
        job_id = uuid.uuid4()
        key = job_key(user_id, str(job_id), "source", "upload.flac")
        if isinstance(clip, bytes):
            path = tmp_path / f"{job_id}.flac"
            path.write_bytes(clip)
            clip = path
        object_store.upload_file(clip, key, "audio/flac")
        with Session(db) as session:
            if session.get(User, user_id) is None:
                session.add(User(id=user_id))
                session.flush()
            session.add(
                Job(
                    id=job_id,
                    user_id=user_id,
                    status=job.pop("status", JobStatus.QUEUED),
                    config={"instrument": instrument, **(config or {})},
                    source_key=key,
                    source_content_type="audio/flac",
                    source_size_bytes=clip.stat().st_size,
                )
            )
            session.commit()
        message = StageMessage(job_id=job_id, user_id=user_id, stage="normalize", **job)
        queue.enqueue(QueueName.CPU, message)
        return job_id

    return submit


def drain(stage_worker: StageWorker, queue: RedisJobQueue, limit: int = 20) -> int:
    """Handle messages from both queues until none are left; returns how many were handled."""
    handled = 0
    while handled < limit:
        delivery = queue.receive(QueueName.CPU, "w", wait_s=0.01) or queue.receive(
            QueueName.ML, "w", wait_s=0.01
        )
        if delivery is None:
            return handled
        stage_worker.handle(delivery)
        handled += 1
    raise AssertionError("queue never drained")


def load(db: Engine, job_id: uuid.UUID) -> tuple[Job, dict[str, StageRun]]:
    with Session(db) as session:
        job = session.get_one(Job, job_id)
        runs = session.scalars(select(StageRun).where(StageRun.job_id == job_id)).all()
        session.expunge_all()
    return job, {run.stage: run for run in runs}


def test_guitar_job_runs_every_stage(
    stage_worker: StageWorker,
    queue: RedisJobQueue,
    submit_job: SubmitJob,
    db: Engine,
    object_store: ObjectStore,
    notifier: RecordingNotifier,
    s3_user: str,
) -> None:
    job_id = submit_job()
    assert drain(stage_worker, queue) == 6  # one message per stage

    job, runs = load(db, job_id)
    assert job.status is JobStatus.SUCCEEDED
    assert job.pipeline_version and job.audio_sha256 and job.finished_at
    assert job.error_code is None
    assert {stage: run.status for stage, run in runs.items()} == dict.fromkeys(
        ["normalize", "separate", "transcribe", "quantize", "notation", "tab"],
        StageStatus.SUCCEEDED,
    )
    assert all(run.attempts == 1 and run.duration_s is not None for run in runs.values())

    with Session(db) as session:
        score = session.scalars(select(ScoreVersion).where(ScoreVersion.job_id == job_id)).one()
    assert score.version == 0
    for key in (score.musicxml_key, score.tab_musicxml_key, score.midi_key, score.sync_key):
        assert key is not None and object_store.head(key) is not None
    keys = object_store.list_keys(job_prefix(s3_user, str(job_id)))
    # ADR-0009: the audio is gone once the job is over (the upload and the normalized copy);
    # the scores and the stages' other files stay.
    assert not [k for k in keys if "/source/" in k or k.endswith("/normalize/audio.flac")]
    assert any(k.endswith("/quantize/quantized.json") for k in keys)
    assert notifier.sent == [(s3_user, job_id, JobStatus.SUCCEEDED)]


def test_piano_job_skips_tab(
    stage_worker: StageWorker, queue: RedisJobQueue, submit_job: SubmitJob, db: Engine
) -> None:
    job_id = submit_job(PIANO_CLIP, instrument="piano")
    drain(stage_worker, queue)
    job, runs = load(db, job_id)
    assert job.status is JobStatus.SUCCEEDED
    assert runs["tab"].status is StageStatus.SKIPPED
    with Session(db) as session:
        score = session.scalars(select(ScoreVersion).where(ScoreVersion.job_id == job_id)).one()
    assert score.tab_musicxml_key is None


def test_a_failed_job_deletes_its_audio_too(
    stage_worker: StageWorker,
    queue: RedisJobQueue,
    submit_job: SubmitJob,
    object_store: ObjectStore,
    s3_user: str,
) -> None:
    job_id = submit_job(b"not audio")
    drain(stage_worker, queue)

    assert object_store.list_keys(job_prefix(s3_user, str(job_id)) + "source/") == []


def test_bad_input_fails_the_job_without_retrying(
    stage_worker: StageWorker,
    queue: RedisJobQueue,
    submit_job: SubmitJob,
    db: Engine,
    notifier: RecordingNotifier,
) -> None:
    job_id = submit_job(b"this is not audio")
    assert drain(stage_worker, queue) == 1

    job, runs = load(db, job_id)
    assert job.status is JobStatus.FAILED
    assert job.error_code == "invalid_input"
    # Only the reason: ffmpeg's output (with server paths) stays in stage_runs and the logs.
    assert job.error_message == "This recording can't be transcribed: could not decode audio."
    last_error = runs["normalize"].last_error or ""
    assert last_error.startswith("stage 'normalize' failed: could not decode audio: ")
    assert runs["normalize"].status is StageStatus.FAILED
    assert len(queue.dead_letters()) == 1
    assert notifier.sent[-1][2] is JobStatus.FAILED


@pytest.fixture
def flaky_pipeline(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """Makes the next N pipeline runs raise, N being the list's one value (default 1)."""
    failures = [1]
    real = pipeline.runner.run_pipeline

    def run(*args: Any, **kwargs: Any) -> RunResult:
        if failures[0] > 0:
            failures[0] -= 1
            raise ConnectionError("storage hiccup")
        return real(*args, **kwargs)

    monkeypatch.setattr(worker.handler, "run_pipeline", run)
    yield failures


def test_transient_failure_is_retried(
    stage_worker: StageWorker,
    queue: RedisJobQueue,
    submit_job: SubmitJob,
    db: Engine,
    clock: FakeClock,
    flaky_pipeline: list[int],
) -> None:
    job_id = submit_job()
    assert drain(stage_worker, queue) == 1
    job, runs = load(db, job_id)
    assert job.status is JobStatus.RUNNING
    assert runs["normalize"].status is StageStatus.QUEUED
    assert runs["normalize"].last_error == "ConnectionError: storage hiccup"

    clock.now += 10  # the retry delay
    drain(stage_worker, queue)
    job, runs = load(db, job_id)
    assert job.status is JobStatus.SUCCEEDED
    assert runs["normalize"].attempts == 2
    assert runs["normalize"].last_error is None


def test_failing_every_attempt_fails_the_job(
    stage_worker: StageWorker,
    queue: RedisJobQueue,
    submit_job: SubmitJob,
    db: Engine,
    clock: FakeClock,
    flaky_pipeline: list[int],
) -> None:
    flaky_pipeline[0] = MAX_ATTEMPTS
    job_id = submit_job()
    for _ in range(MAX_ATTEMPTS):
        drain(stage_worker, queue)
        clock.now += 1000
    job, runs = load(db, job_id)
    assert job.status is JobStatus.FAILED
    assert (job.error_code, job.error_message) == ("stage_failed", INTERNAL_ERROR_MESSAGE)
    assert runs["normalize"].attempts == MAX_ATTEMPTS
    assert len(queue.dead_letters()) == 1


def test_worker_that_kept_dying_fails_the_job(
    stage_worker: StageWorker, queue: RedisJobQueue, submit_job: SubmitJob, db: Engine
) -> None:
    job_id = submit_job(attempt=MAX_ATTEMPTS + 1)
    drain(stage_worker, queue)
    job, _ = load(db, job_id)
    assert (job.status, job.error_code) == (JobStatus.FAILED, "stage_failed")


def test_message_for_a_finished_job_is_dropped(
    stage_worker: StageWorker, queue: RedisJobQueue, submit_job: SubmitJob, db: Engine
) -> None:
    job_id = submit_job(status=JobStatus.FAILED)
    assert drain(stage_worker, queue) == 1
    job, runs = load(db, job_id)
    assert job.status is JobStatus.FAILED
    assert runs == {}
    assert queue.dead_letters() == []


def test_identical_upload_reuses_the_results(
    stage_worker: StageWorker,
    queue: RedisJobQueue,
    submit_job: SubmitJob,
    db: Engine,
    object_store: ObjectStore,
    notifier: RecordingNotifier,
) -> None:
    first = submit_job()
    drain(stage_worker, queue)
    second = submit_job()
    assert drain(stage_worker, queue) == 1  # normalize only; the rest is copied

    job, runs = load(db, second)
    assert job.status is JobStatus.SUCCEEDED
    assert job.pipeline_version == load(db, first)[0].pipeline_version
    assert runs["normalize"].status is StageStatus.SUCCEEDED
    later = ["separate", "transcribe", "quantize", "notation", "tab"]
    assert [runs[s].status for s in later] == [StageStatus.CACHED] * len(later)
    with Session(db) as session:
        score = session.scalars(select(ScoreVersion).where(ScoreVersion.job_id == second)).one()
    for key in (score.musicxml_key, score.tab_musicxml_key, score.midi_key, score.sync_key):
        assert key is not None and f"/jobs/{second}/" in key  # its own copy
        assert object_store.head(key) is not None
    assert notifier.sent[-1] == (job.user_id, second, JobStatus.SUCCEEDED)


def test_different_options_are_not_reused(
    stage_worker: StageWorker, queue: RedisJobQueue, submit_job: SubmitJob
) -> None:
    submit_job()
    drain(stage_worker, queue)
    submit_job(config={"capo": 2})
    assert drain(stage_worker, queue) == 6


def test_another_users_results_are_not_reused(
    stage_worker: StageWorker,
    queue: RedisJobQueue,
    submit_job: SubmitJob,
    object_store: ObjectStore,
    s3_user: str,
) -> None:
    submit_job()
    drain(stage_worker, queue)
    other = f"{s3_user}-b"
    try:
        submit_job(user_id=other)
        assert drain(stage_worker, queue) == 6
    finally:
        object_store.delete_prefix(f"users/{other}/")


def test_lost_files_mean_running_the_stages(
    stage_worker: StageWorker,
    queue: RedisJobQueue,
    submit_job: SubmitJob,
    db: Engine,
    object_store: ObjectStore,
    s3_user: str,
) -> None:
    first = submit_job()
    drain(stage_worker, queue)
    object_store.delete_prefix(f"{job_prefix(s3_user, str(first))}notation/")  # e.g. lifecycle
    second = submit_job()
    assert drain(stage_worker, queue) == 6
    assert load(db, second)[0].status is JobStatus.SUCCEEDED


def test_a_job_is_one_trace_with_metrics_and_logs(
    stage_worker: StageWorker,
    queue: RedisJobQueue,
    submit_job: SubmitJob,
    spans: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def runs(outcome: str) -> float:
        value = REGISTRY.get_sample_value(
            "tabscribe_stage_runs_total", {"stage": "transcribe", "outcome": outcome}
        )
        return value or 0.0

    before = runs("succeeded")
    with trace.get_tracer("test").start_as_current_span("api submit") as submit:
        job_id = submit_job(trace=inject_trace())
    caplog.handler.setFormatter(JsonFormatter("worker"))
    with caplog.at_level(logging.INFO):
        drain(stage_worker, queue)

    stage_spans = [s for s in spans.get_finished_spans() if s.name.startswith("stage ")]
    assert [s.name for s in stage_spans] == [
        f"stage {name}"
        for name in ("normalize", "separate", "transcribe", "quantize", "notation", "tab")
    ]
    assert {s.context.trace_id for s in stage_spans} == {submit.get_span_context().trace_id}
    assert all(s.attributes and s.attributes["job.id"] == str(job_id) for s in stage_spans)
    assert runs("succeeded") == before + 1

    lines = [json.loads(line) for line in caplog.text.splitlines()]
    pipeline_lines = [e for e in lines if e["logger"] == "pipeline.runner"]
    assert pipeline_lines  # the pipeline's own logs get the job's fields too
    assert all(e["job_id"] == str(job_id) and "trace_id" in e for e in pipeline_lines)
    assert any(e["message"] == "job succeeded" for e in lines)


@pytest.mark.unit
def test_queues_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_QUEUES", "ml")
    assert WorkerSettings().queues == [QueueName.ML]
    monkeypatch.setenv("WORKER_QUEUES", "cpu, ml")
    assert WorkerSettings().queues == [QueueName.CPU, QueueName.ML]


def add_edit(
    db: Engine, queue: RedisJobQueue, job_id: uuid.UUID, user_id: str, number: int, edits: list[Any]
) -> None:
    """What the API does on save: a pending version and a RENDER message (ADR-0011)."""
    with Session(db) as session:
        session.add(
            ScoreVersion(
                job_id=job_id,
                user_id=user_id,
                version=number,
                status=VersionStatus.PENDING,
                base_version=number - 1,
                edits={"edits": edits},
            )
        )
        session.commit()
    queue.enqueue(
        QueueName.CPU, StageMessage(job_id=job_id, user_id=user_id, stage=RENDER, version=number)
    )


def version(db: Engine, job_id: uuid.UUID, number: int) -> ScoreVersion:
    with Session(db) as session:
        return session.scalars(
            select(ScoreVersion).where(
                ScoreVersion.job_id == job_id, ScoreVersion.version == number
            )
        ).one()


def test_edits_render_new_versions_on_top_of_each_other(
    stage_worker: StageWorker,
    queue: RedisJobQueue,
    submit_job: SubmitJob,
    db: Engine,
    object_store: ObjectStore,
    s3_user: str,
    tmp_path: Path,
) -> None:
    job_id = submit_job()
    drain(stage_worker, queue)
    object_store.download_file(
        job_key(s3_user, str(job_id), "quantize", "quantized.json"), tmp_path / "q.json"
    )
    notes = json.loads((tmp_path / "q.json").read_text())["notes"]
    first = {"onset_beats": notes[0]["onset_beats"], "pitch": notes[0]["pitch"]}

    add_edit(db, queue, job_id, s3_user, 1, [{"op": "delete", "note": first}])
    assert drain(stage_worker, queue) == 1
    v1 = version(db, job_id, 1)
    assert v1.status is VersionStatus.READY and v1.error_message is None
    for key in (v1.document_key, v1.musicxml_key, v1.tab_musicxml_key, v1.midi_key, v1.sync_key):
        assert key is not None and f"/jobs/{job_id}/versions/1/" in key
        assert object_store.head(key) is not None

    # Version 2 builds on version 1's document, not on the pipeline's output.
    added = {"op": "add", "onset_beats": "0", "duration_beats": "1", "pitch": 64, "string": 1}
    add_edit(db, queue, job_id, s3_user, 2, [added])
    drain(stage_worker, queue)
    v2 = version(db, job_id, 2)
    assert v2.status is VersionStatus.READY and v2.document_key is not None
    object_store.download_file(v2.document_key, tmp_path / "v2.json")
    v2_notes = json.loads((tmp_path / "v2.json").read_text())["score"]["notes"]
    assert len(v2_notes) == len(notes)  # one deleted, one added
    assert version(db, job_id, 0).status is VersionStatus.READY  # the original is untouched


def test_a_bad_edit_fails_the_version_with_a_message(
    stage_worker: StageWorker, queue: RedisJobQueue, submit_job: SubmitJob, db: Engine, s3_user: str
) -> None:
    job_id = submit_job()
    drain(stage_worker, queue)

    gone = {"op": "delete", "note": {"onset_beats": "999", "pitch": 60}}
    add_edit(db, queue, job_id, s3_user, 1, [gone])
    drain(stage_worker, queue)

    v1 = version(db, job_id, 1)
    assert v1.status is VersionStatus.FAILED and v1.musicxml_key is None
    assert v1.error_message == (
        "These changes can't be saved: Change 1: that note isn't in this version any more."
    )
    assert all(d.ready == 0 for d in queue.depth())  # not retried: retrying can't fix it
    assert queue.dead_letter_count() == 0


def test_a_render_message_for_a_finished_version_is_dropped(
    stage_worker: StageWorker, queue: RedisJobQueue, submit_job: SubmitJob, db: Engine, s3_user: str
) -> None:
    job_id = submit_job()
    drain(stage_worker, queue)
    add_edit(db, queue, job_id, s3_user, 1, [])  # an empty edit is a plain copy
    drain(stage_worker, queue)
    rendered = version(db, job_id, 1)
    assert rendered.status is VersionStatus.READY

    replay = StageMessage(job_id=job_id, user_id=s3_user, stage=RENDER, version=1)
    queue.enqueue(QueueName.CPU, replay)  # a duplicate delivery
    assert drain(stage_worker, queue) == 1
    assert version(db, job_id, 1).musicxml_key == rendered.musicxml_key
