"""`python -m worker`: consume stage messages until SIGTERM/SIGINT.

On a stop signal the current stage finishes first (it can take minutes), then the process exits.
"""

import logging
import signal
import threading
from types import FrameType

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from prometheus_client import start_http_server

from tabscribe_platform.db import make_engine, make_session_factory
from tabscribe_platform.jobqueue import JobQueue, RedisJobQueue
from tabscribe_platform.observability import configure_logging, configure_tracing
from tabscribe_platform.settings import get_settings
from tabscribe_platform.storage import ObjectStore
from worker.handler import StageWorker, remove_stale_tempdirs
from worker.notify import ExpoPushNotifier, LogNotifier, Notifier, expo_sender
from worker.settings import WorkerSettings

logger = logging.getLogger("worker")


def serve(
    worker: StageWorker, queue: JobQueue, settings: WorkerSettings, stop: threading.Event
) -> None:
    while not stop.is_set():
        for name in settings.queues:
            delivery = queue.receive(name, settings.id, wait_s=settings.poll_s)
            if delivery is not None:
                worker.handle(delivery)
            if stop.is_set():
                break


def main() -> None:
    configure_logging("worker")
    configure_tracing("worker")
    settings = get_settings()
    worker_settings = WorkerSettings()
    if worker_settings.metrics_port:
        start_http_server(worker_settings.metrics_port)
    queue = RedisJobQueue.from_url(
        str(settings.redis_url), visibility_timeout_s=settings.queue_visibility_timeout_s
    )
    sessions = make_session_factory(make_engine(str(settings.database_url)))
    notifier: Notifier = LogNotifier()
    if worker_settings.notifier == "expo":
        token = worker_settings.expo_access_token
        notifier = ExpoPushNotifier(
            sessions, expo_sender(token.get_secret_value() if token else None)
        )
    worker = StageWorker(
        sessions,
        ObjectStore(settings),
        queue,
        notifier,
        # Three heartbeats per timeout: one can be late without losing the message.
        heartbeat_s=settings.queue_visibility_timeout_s / 3,
    )

    stop = threading.Event()

    def request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("%s: stopping after the current stage", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    remove_stale_tempdirs()
    logger.info("worker %s serving %s", worker_settings.id, ", ".join(worker_settings.queues))
    serve(worker, queue, worker_settings, stop)
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()  # flush the last spans


if __name__ == "__main__":
    main()
