"""API metrics: request latency (target: p95 under 200 ms) and the queue depth gauges."""

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, Histogram
from prometheus_client import generate_latest as render

from tabscribe_platform.jobqueue import JobQueue
from tabscribe_platform.metrics import QueueDepthCollector

REQUEST_SECONDS = Histogram(
    "tabscribe_http_request_duration_seconds",
    "API request latency",
    ["method", "route", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0),
)
_UNTIMED = frozenset({"/metrics", "/healthz", "/readyz"})


async def time_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    # The route template (/jobs/{job_id}), not the raw path: one series per endpoint.
    route = getattr(request.scope.get("route"), "path", "unmatched")
    if route not in _UNTIMED:
        REQUEST_SECONDS.labels(request.method, route, str(response.status_code)).observe(
            time.perf_counter() - start
        )
    return response


def metrics_response(queue: JobQueue) -> Response:
    """Process metrics plus the queue depth, read now. Serve it on an internal port or block
    /metrics at the ingress: it isn't meant for clients."""
    per_scrape = CollectorRegistry()
    per_scrape.register(QueueDepthCollector(queue))
    return Response(render(REGISTRY) + render(per_scrape), media_type=CONTENT_TYPE_LATEST)
