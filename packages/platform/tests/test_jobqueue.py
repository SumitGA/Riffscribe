import threading
import time
import uuid

import pytest
import redis

from tabscribe_platform.jobqueue import (
    MAX_ATTEMPTS,
    FailOutcome,
    Priority,
    QueueName,
    RedisJobQueue,
    StageMessage,
    queue_for_stage,
    retry_delay_s,
)


def _message(stage: str = "quantize", attempt: int = 1) -> StageMessage:
    return StageMessage(job_id=uuid.uuid4(), user_id="alice", stage=stage, attempt=attempt)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def queue(
    redis_client: "redis.Redis", key_prefix: str, clock: FakeClock, job_queue: RedisJobQueue
) -> RedisJobQueue:
    """Like `job_queue` (which deletes the keys afterwards), with a fake clock for backoff."""
    return RedisJobQueue(redis_client, visibility_timeout_s=0.2, prefix=key_prefix, clock=clock)


@pytest.mark.unit
def test_ml_stages_go_to_the_ml_queue() -> None:
    assert queue_for_stage("transcribe") is QueueName.ML
    assert queue_for_stage("separate") is QueueName.ML
    assert queue_for_stage("normalize") is QueueName.CPU
    assert queue_for_stage("tab") is QueueName.CPU


@pytest.mark.unit
def test_retry_delays() -> None:
    assert [retry_delay_s(a) for a in (1, 2)] == [10, 40]


@pytest.mark.integration
def test_enqueue_receive_ack(job_queue: RedisJobQueue) -> None:
    message = _message()
    job_queue.enqueue(QueueName.CPU, message)

    delivery = job_queue.receive(QueueName.CPU, "w1", wait_s=0.1)
    assert delivery is not None
    assert delivery.message == message
    assert delivery.priority is Priority.NORMAL
    assert job_queue.receive(QueueName.CPU, "w2", wait_s=0.1) is None  # invisible to others

    job_queue.ack(delivery)
    time.sleep(0.3)  # past the visibility timeout: an acked message never comes back
    assert job_queue.receive(QueueName.CPU, "w2", wait_s=0.1) is None


@pytest.mark.integration
def test_queues_are_separate(job_queue: RedisJobQueue) -> None:
    job_queue.enqueue(QueueName.ML, _message("transcribe"))
    assert job_queue.receive(QueueName.CPU, "w1", wait_s=0.1) is None
    assert job_queue.receive(QueueName.ML, "w1", wait_s=0.1) is not None


@pytest.mark.integration
def test_high_priority_first(job_queue: RedisJobQueue) -> None:
    free, paid = _message(), _message()
    job_queue.enqueue(QueueName.CPU, free)
    job_queue.enqueue(QueueName.CPU, paid, priority=Priority.HIGH)

    received = [job_queue.receive(QueueName.CPU, "w1", wait_s=0.1) for _ in range(2)]
    assert [d.message if d else None for d in received] == [paid, free]


@pytest.mark.integration
def test_blocking_receive_wakes_up_on_enqueue(
    job_queue: RedisJobQueue, redis_client: "redis.Redis", key_prefix: str
) -> None:
    job_queue.receive(QueueName.CPU, "w1", wait_s=0.01)  # creates the streams and group
    # Enqueue from a second connection while the first one blocks.
    other = RedisJobQueue(redis_client, visibility_timeout_s=0.2, prefix=key_prefix)
    timer = threading.Timer(0.2, other.enqueue, (QueueName.CPU, _message()))
    timer.start()
    start = time.monotonic()
    delivery = job_queue.receive(QueueName.CPU, "w1", wait_s=5)
    timer.join()
    assert delivery is not None
    assert time.monotonic() - start < 2


@pytest.mark.integration
def test_failed_stage_is_retried_after_backoff(queue: RedisJobQueue, clock: FakeClock) -> None:
    queue.enqueue(QueueName.CPU, _message())
    delivery = queue.receive(QueueName.CPU, "w1", wait_s=0.1)
    assert delivery is not None

    assert queue.fail(delivery, "boom") is FailOutcome.RETRY
    clock.now += retry_delay_s(1) - 1
    assert queue.receive(QueueName.CPU, "w1", wait_s=0.05) is None  # not due yet
    clock.now += 1
    retried = queue.receive(QueueName.CPU, "w1", wait_s=0.05)
    assert retried is not None
    assert retried.message == delivery.message.model_copy(update={"attempt": 2})


@pytest.mark.integration
def test_last_attempt_goes_to_the_dead_letter_queue(queue: RedisJobQueue) -> None:
    message = _message(attempt=MAX_ATTEMPTS)
    queue.enqueue(QueueName.CPU, message)
    delivery = queue.receive(QueueName.CPU, "w1", wait_s=0.1)
    assert delivery is not None

    assert queue.fail(delivery, "boom") is FailOutcome.DEAD
    [dead] = queue.dead_letters()
    assert StageMessage.model_validate_json(dead.body) == message
    assert dead.error == "boom"
    assert dead.queue.endswith(":cpu:normal")


@pytest.mark.integration
def test_non_retryable_failure_goes_straight_to_the_dlq(queue: RedisJobQueue) -> None:
    queue.enqueue(QueueName.CPU, _message())
    delivery = queue.receive(QueueName.CPU, "w1", wait_s=0.1)
    assert delivery is not None
    assert queue.fail(delivery, "not audio", retry=False) is FailOutcome.DEAD
    assert len(queue.dead_letters()) == 1


@pytest.mark.integration
def test_crashed_worker_counts_as_a_failed_attempt(queue: RedisJobQueue, clock: FakeClock) -> None:
    queue.enqueue(QueueName.CPU, _message())
    assert queue.receive(QueueName.CPU, "crashed", wait_s=0.1) is not None
    time.sleep(0.3)  # the visibility timeout passes without ack or heartbeat

    assert queue.receive(QueueName.CPU, "w2", wait_s=0.05) is None  # reclaimed, backing off
    clock.now += retry_delay_s(1)
    retried = queue.receive(QueueName.CPU, "w2", wait_s=0.05)
    assert retried is not None
    assert retried.message.attempt == 2


@pytest.mark.integration
def test_heartbeat_keeps_a_long_stage(job_queue: RedisJobQueue) -> None:
    job_queue.enqueue(QueueName.CPU, _message())
    delivery = job_queue.receive(QueueName.CPU, "w1", wait_s=0.1)
    assert delivery is not None
    for _ in range(3):
        time.sleep(0.12)
        job_queue.extend(delivery)
    assert job_queue.receive(QueueName.CPU, "w2", wait_s=0.05) is None
    job_queue.ack(delivery)
    with pytest.raises(LookupError):
        job_queue.extend(delivery)


@pytest.mark.integration
def test_unreadable_message_is_dead_lettered(
    job_queue: RedisJobQueue, redis_client: "redis.Redis", key_prefix: str
) -> None:
    job_queue.receive(QueueName.CPU, "w1", wait_s=0.01)
    redis_client.xadd(f"{key_prefix}:cpu:normal", {"body": "{not json"})
    assert job_queue.receive(QueueName.CPU, "w1", wait_s=0.05) is None
    [dead] = job_queue.dead_letters()
    assert dead.body == "{not json"
    assert dead.error.startswith("unreadable message")


@pytest.mark.integration
def test_delayed_enqueue(queue: RedisJobQueue, clock: FakeClock) -> None:
    queue.enqueue(QueueName.CPU, _message(), delay_s=30)
    assert queue.receive(QueueName.CPU, "w1", wait_s=0.05) is None
    clock.now += 30
    assert queue.receive(QueueName.CPU, "w1", wait_s=0.05) is not None


@pytest.mark.integration
def test_crash_on_the_last_attempt_comes_back_to_a_worker(queue: RedisJobQueue) -> None:
    queue.enqueue(QueueName.CPU, _message(attempt=MAX_ATTEMPTS))
    assert queue.receive(QueueName.CPU, "crashed", wait_s=0.1) is not None
    time.sleep(0.3)

    # Not silently dead-lettered: a worker gets it, sees the attempts are used up, fails the job.
    delivery = queue.receive(QueueName.CPU, "w2", wait_s=0.05)
    assert delivery is not None
    assert delivery.message.attempt == MAX_ATTEMPTS + 1
    assert queue.fail(delivery, "worker kept crashing") is FailOutcome.DEAD
    assert queue.dead_letters()[0].error == "worker kept crashing"


@pytest.mark.integration
def test_depth_counts_ready_in_flight_delayed(queue: RedisJobQueue) -> None:
    for _ in range(3):
        queue.enqueue(QueueName.CPU, _message())
    queue.enqueue(QueueName.ML, _message("transcribe"), priority=Priority.HIGH, delay_s=30)
    delivery = queue.receive(QueueName.CPU, "w1", wait_s=0.1)
    assert delivery is not None

    depth = {(d.queue, d.priority): d for d in queue.depth()}
    cpu = depth[QueueName.CPU, Priority.NORMAL]
    assert (cpu.ready, cpu.in_flight, cpu.delayed) == (2, 1, 0)
    ml = depth[QueueName.ML, Priority.HIGH]
    assert (ml.ready, ml.in_flight, ml.delayed) == (0, 0, 1)
    assert len(depth) == len(QueueName) * len(Priority)

    queue.fail(delivery, "boom", retry=False)
    assert queue.dead_letter_count() == 1
    assert depth[QueueName.CPU, Priority.NORMAL].in_flight == 1  # the old snapshot
    assert {(d.queue, d.priority): d.in_flight for d in queue.depth()}[
        QueueName.CPU, Priority.NORMAL
    ] == 0
