"""Job queue: the `JobQueue` interface and its Redis Streams implementation (TD-3).

One message is one stage of one job. Delivery is at least once (stages are idempotent), a
failed stage is retried with exponential backoff, and after `MAX_ATTEMPTS` it goes to the
dead-letter queue. On the AWS scale-up path an SQS implementation replaces `RedisJobQueue`.
"""

import json
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

import redis
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_ATTEMPTS = 3  # per stage (CLAUDE.md)
RETRY_BASE_DELAY_S = 10.0


def retry_delay_s(attempt: int) -> float:
    """Wait before retrying after `attempt` failed: 10 s, then 40 s (then 160 s, ...)."""
    return RETRY_BASE_DELAY_S * float(4 ** (attempt - 1))


class QueueName(StrEnum):
    """Kept apart so GPU workers can take over `ML` by config (CLAUDE.md scalability rules)."""

    CPU = "cpu"
    ML = "ml"


# The pipeline's stage order (pipeline.stages.default_stages; a test keeps them in sync).
STAGES = ("normalize", "separate", "transcribe", "quantize", "notation", "tab")
ML_STAGES = frozenset({"separate", "transcribe"})
# Not a pipeline stage: render an edited score version (ADR-0011). CPU queue, after the job.
RENDER = "render"


def queue_for_stage(stage: str) -> QueueName:
    return QueueName.ML if stage in ML_STAGES else QueueName.CPU


class Priority(StrEnum):
    HIGH = "high"  # paid tier
    NORMAL = "normal"


class StageMessage(BaseModel):
    """Run `stage` of a job. `attempt` counts from 1 and goes up each time the stage fails."""

    model_config = ConfigDict(frozen=True)

    job_id: uuid.UUID
    user_id: str
    stage: str
    attempt: int = Field(default=1, ge=1)
    # For RENDER messages: the score version to render.
    version: int | None = Field(default=None, ge=1)
    # W3C trace context of the step that queued this one, so a job is one trace across workers.
    trace: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class Delivery:
    """A received message. Pass it back to `ack`, `fail` or `extend`."""

    queue: QueueName
    priority: Priority
    message: StageMessage
    receipt: str  # implementation-specific (Redis: "<stream key> <entry id> <consumer>")


class FailOutcome(StrEnum):
    RETRY = "retry"  # scheduled again after a backoff delay
    DEAD = "dead"  # moved to the dead-letter queue


@dataclass(frozen=True)
class QueueDepth:
    queue: QueueName
    priority: Priority
    ready: int  # waiting for a worker
    in_flight: int  # received, not yet acked or failed
    delayed: int  # waiting out a retry delay


@dataclass(frozen=True)
class DeadLetter:
    queue: str
    body: str  # the raw message, kept even if it doesn't parse
    error: str


class JobQueue(ABC):
    @abstractmethod
    def enqueue(
        self,
        queue: QueueName,
        message: StageMessage,
        *,
        priority: Priority = Priority.NORMAL,
        delay_s: float = 0,
    ) -> None: ...

    @abstractmethod
    def receive(self, queue: QueueName, consumer: str, *, wait_s: float) -> Delivery | None:
        """Next message, high priority first, waiting up to `wait_s`. None if there was none.

        The message stays invisible to other consumers until it is acked or failed, or until
        the visibility timeout passes without `extend` (the consumer is presumed dead, and
        that counts as a failed attempt). A message with `attempt > MAX_ATTEMPTS` means its
        consumers kept dying: fail its job and call `fail(..., retry=False)`.
        """

    @abstractmethod
    def ack(self, delivery: Delivery) -> None:
        """The stage finished; drop the message."""

    @abstractmethod
    def fail(self, delivery: Delivery, error: str, *, retry: bool = True) -> FailOutcome:
        """The stage failed. Retried with backoff unless attempts are used up or `retry` is
        False (for errors a retry can't fix, such as unreadable audio)."""

    @abstractmethod
    def extend(self, delivery: Delivery) -> None:
        """Heartbeat for a long-running stage: restart its visibility timeout.

        Raises LookupError if the delivery was already acked or given to another consumer.
        """

    @abstractmethod
    def dead_letters(self, limit: int = 100) -> list[DeadLetter]: ...

    @abstractmethod
    def depth(self) -> list[QueueDepth]:
        """Backlog of every queue and priority (the autoscaling signal)."""

    @abstractmethod
    def dead_letter_count(self) -> int: ...


# Moves due delayed messages into their streams. One script, so two workers never both move
# the same message. It writes to stream keys it isn't given in KEYS, which is fine on a single
# Redis/Valkey node but not on Redis Cluster.
_PROMOTE_DUE = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, 100)
for _, member in ipairs(due) do
  local item = cjson.decode(member)
  redis.call('XADD', item.stream, '*', 'body', item.body)
  redis.call('ZREM', KEYS[1], member)
end
return #due
"""

_GROUP = "workers"

type _Entry = tuple[str, str, dict[str, str]]  # stream key, entry id, fields


class RedisJobQueue(JobQueue):
    """Streams `{prefix}:{queue}:{priority}` read by one consumer group, plus a sorted set of
    delayed messages (Streams have no delayed delivery) and a dead-letter stream."""

    def __init__(
        self,
        client: "redis.Redis",
        *,
        visibility_timeout_s: float,
        prefix: str = "tabscribe:queue",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis = client
        self._visibility_ms = int(visibility_timeout_s * 1000)
        self._prefix = prefix
        self._clock = clock
        self._delayed_key = f"{prefix}:delayed"
        self._dlq_key = f"{prefix}:dlq"
        self._promote_due = client.register_script(_PROMOTE_DUE)
        self._groups_ready: set[str] = set()

    @classmethod
    def from_url(cls, url: str, *, visibility_timeout_s: float) -> "RedisJobQueue":
        client = redis.Redis.from_url(url, decode_responses=True)
        return cls(client, visibility_timeout_s=visibility_timeout_s)

    def _stream(self, queue: QueueName, priority: Priority) -> str:
        return f"{self._prefix}:{queue}:{priority}"

    def _ensure_group(self, stream: str) -> None:
        if stream in self._groups_ready:
            return
        try:
            self._redis.xgroup_create(stream, _GROUP, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):  # BUSYGROUP: the group exists already
                raise
        self._groups_ready.add(stream)

    def enqueue(
        self,
        queue: QueueName,
        message: StageMessage,
        *,
        priority: Priority = Priority.NORMAL,
        delay_s: float = 0,
    ) -> None:
        stream = self._stream(queue, priority)
        body = message.model_dump_json()
        if delay_s > 0:
            self._schedule(self._redis, stream, body, delay_s)
        else:
            self._redis.xadd(stream, {"body": body})

    def _schedule(self, client: "redis.Redis", stream: str, body: str, delay_s: float) -> None:
        # The nonce keeps two identical messages from collapsing into one set member.
        member = json.dumps({"stream": stream, "body": body, "nonce": uuid.uuid4().hex})
        client.zadd(self._delayed_key, {member: self._clock() + delay_s})

    def receive(self, queue: QueueName, consumer: str, *, wait_s: float) -> Delivery | None:
        streams = [self._stream(queue, p) for p in (Priority.HIGH, Priority.NORMAL)]
        for stream in streams:
            self._ensure_group(stream)
        self._promote_due(keys=[self._delayed_key], args=[self._clock()])
        for stream in streams:
            self._reclaim_stale(queue, stream, consumer)

        # Non-blocking pass, high priority first; then block on both.
        for stream in streams:
            if delivery := self._read(queue, consumer, [stream], block_ms=None):
                return delivery
        return self._read(queue, consumer, streams, block_ms=max(1, int(wait_s * 1000)))

    def _read(
        self, queue: QueueName, consumer: str, streams: list[str], block_ms: int | None
    ) -> Delivery | None:
        response = cast(
            list[tuple[str, list[tuple[str, dict[str, str]]]]] | None,
            self._redis.xreadgroup(
                _GROUP, consumer, dict.fromkeys(streams, ">"), count=1, block=block_ms
            ),
        )
        # `streams` is in priority order; Redis may answer in any order.
        by_stream = dict(response or [])
        entries: list[_Entry] = [
            (stream, entry_id, fields)
            for stream in streams
            for entry_id, fields in by_stream.get(stream, [])
        ]
        if not entries:
            return None
        # A blocking read over two streams can return one entry from each. Keep the first and
        # put the others back at the end of their stream, so they don't sit with this consumer
        # until the visibility timeout.
        for stream, entry_id, fields in entries[1:]:
            with self._redis.pipeline() as pipe:
                pipe.xadd(stream, {"body": fields["body"]})
                self._remove(pipe, stream, entry_id)
                pipe.execute()
        return self._delivery(queue, consumer, entries[0])

    def _delivery(self, queue: QueueName, consumer: str, entry: _Entry) -> Delivery | None:
        stream, entry_id, fields = entry
        body = fields.get("body", "")
        try:
            message = StageMessage.model_validate_json(body)
        except ValidationError as exc:
            self._dead_letter(stream, entry_id, body, f"unreadable message: {exc}")
            return None
        priority = Priority(stream.rsplit(":", 1)[1])
        return Delivery(queue, priority, message, f"{stream} {entry_id} {consumer}")

    def _reclaim_stale(self, queue: QueueName, stream: str, consumer: str) -> None:
        """Messages whose consumer stopped responding count as a failed attempt."""
        response = self._redis.xautoclaim(
            stream, _GROUP, consumer, min_idle_time=self._visibility_ms, count=10
        )
        for entry_id, fields in response[1]:
            if fields is None:  # deleted from the stream meanwhile
                continue
            delivery = self._delivery(queue, consumer, (stream, entry_id, fields))
            if delivery is None:
                continue
            # Never dead-lettered here: the worker must see the message to fail its job, so
            # after the last attempt it comes back at once with attempt > MAX_ATTEMPTS.
            attempt = delivery.message.attempt
            delay = retry_delay_s(attempt) if attempt < MAX_ATTEMPTS else 0.0
            self._requeue(delivery, delay)

    @staticmethod
    def _remove(pipe: "redis.client.Pipeline", stream: str, entry_id: str) -> None:
        # Acked entries are deleted too, so the streams only hold work that isn't done.
        pipe.xack(stream, _GROUP, entry_id)
        pipe.xdel(stream, entry_id)

    @staticmethod
    def _parse_receipt(delivery: Delivery) -> tuple[str, str, str]:
        stream, entry_id, consumer = delivery.receipt.split(" ")
        return stream, entry_id, consumer

    def ack(self, delivery: Delivery) -> None:
        stream, entry_id, _consumer = self._parse_receipt(delivery)
        with self._redis.pipeline() as pipe:
            self._remove(pipe, stream, entry_id)
            pipe.execute()

    def fail(self, delivery: Delivery, error: str, *, retry: bool = True) -> FailOutcome:
        stream, entry_id, _consumer = self._parse_receipt(delivery)
        attempt = delivery.message.attempt
        if not retry or attempt >= MAX_ATTEMPTS:
            self._dead_letter(stream, entry_id, delivery.message.model_dump_json(), error)
            return FailOutcome.DEAD
        self._requeue(delivery, retry_delay_s(attempt))
        return FailOutcome.RETRY

    def _requeue(self, delivery: Delivery, delay_s: float) -> None:
        """Put the message back as its next attempt, after `delay_s`."""
        stream, entry_id, _consumer = self._parse_receipt(delivery)
        body = delivery.message.model_copy(update={"attempt": delivery.message.attempt + 1})
        with self._redis.pipeline() as pipe:  # MULTI/EXEC: requeued and removed together
            if delay_s > 0:
                self._schedule(pipe, stream, body.model_dump_json(), delay_s)
            else:
                pipe.xadd(stream, {"body": body.model_dump_json()})
            self._remove(pipe, stream, entry_id)
            pipe.execute()

    def _dead_letter(self, stream: str, entry_id: str, body: str, error: str) -> None:
        with self._redis.pipeline() as pipe:
            pipe.xadd(self._dlq_key, {"queue": stream, "body": body, "error": error[:2000]})
            self._remove(pipe, stream, entry_id)
            pipe.execute()

    def extend(self, delivery: Delivery) -> None:
        stream, entry_id, consumer = self._parse_receipt(delivery)
        pending = cast(
            list[dict[str, Any]],
            self._redis.xpending_range(stream, _GROUP, min=entry_id, max=entry_id, count=1),
        )
        if not pending or pending[0]["consumer"] != consumer:
            raise LookupError(f"delivery {delivery.receipt} is no longer ours")
        # Claiming our own entry with min idle 0 resets its idle time; JUSTID skips the payload.
        self._redis.xclaim(stream, _GROUP, consumer, 0, [entry_id], justid=True)

    def dead_letters(self, limit: int = 100) -> list[DeadLetter]:
        entries = cast(
            list[tuple[str, dict[str, str]]], self._redis.xrange(self._dlq_key, count=limit)
        )
        return [DeadLetter(f["queue"], f["body"], f["error"]) for _id, f in entries]

    def depth(self) -> list[QueueDepth]:
        delayed: dict[str, int] = {}
        for member in cast(list[str], self._redis.zrange(self._delayed_key, 0, -1)):
            stream = json.loads(member)["stream"]
            delayed[stream] = delayed.get(stream, 0) + 1
        depths = []
        for queue in QueueName:
            for priority in Priority:
                stream = self._stream(queue, priority)
                self._ensure_group(stream)
                with self._redis.pipeline(transaction=False) as pipe:
                    pipe.xlen(stream)
                    pipe.xpending(stream, _GROUP)
                    length, pending = pipe.execute()
                in_flight = int(pending["pending"])
                # Acked entries are deleted, so the stream holds exactly the unfinished ones.
                depths.append(
                    QueueDepth(
                        queue, priority, int(length) - in_flight, in_flight, delayed.get(stream, 0)
                    )
                )
        return depths

    def dead_letter_count(self) -> int:
        return int(self._redis.xlen(self._dlq_key))
