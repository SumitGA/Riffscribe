"""Prometheus metrics shared by the API and the worker.

Queue depth is read from the queue at scrape time rather than counted, so it is right whichever
instance is scraped. Every API instance reports the same numbers: aggregate with `max`, not `sum`.
"""

import logging
from collections.abc import Iterator

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from tabscribe_platform.jobqueue import JobQueue

logger = logging.getLogger(__name__)


class QueueDepthCollector(Collector):
    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue

    def collect(self) -> Iterator[GaugeMetricFamily]:
        depth = GaugeMetricFamily(
            "tabscribe_queue_messages",
            "Stage messages per queue, priority and state (ready, in_flight, delayed)",
            labels=["queue", "priority", "state"],
        )
        dead = GaugeMetricFamily(
            "tabscribe_queue_dead_letters", "Messages in the dead-letter queue"
        )
        try:
            for d in self._queue.depth():
                for state, value in (
                    ("ready", d.ready),
                    ("in_flight", d.in_flight),
                    ("delayed", d.delayed),
                ):
                    depth.add_metric([d.queue, d.priority, state], value)
            dead.add_metric([], self._queue.dead_letter_count())
        except Exception:
            # A scrape must not fail because Redis is down; the series just go missing.
            logger.warning("could not read queue depth", exc_info=True)
            return
        yield depth
        yield dead
