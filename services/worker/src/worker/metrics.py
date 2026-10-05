"""Worker metrics, served on WORKER_METRICS_PORT for Prometheus. Queue depth comes from the API's
/metrics (it reads the queue itself), so it isn't repeated here."""

from prometheus_client import Counter, Histogram

STAGE_SECONDS = Histogram(
    "tabscribe_stage_duration_seconds",
    "Time to handle one stage message, by stage and outcome",
    ["stage", "outcome"],
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
)
# outcome: succeeded, skipped, retried, failed, dropped (stale message), cached (dedup reuse).
# Failure rate: rate(...{outcome=~"retried|failed"}) / rate(...).
STAGE_RUNS = Counter(
    "tabscribe_stage_runs", "Stage messages handled, by outcome", ["stage", "outcome"]
)
JOBS_FINISHED = Counter("tabscribe_jobs_finished", "Jobs finished, by final status", ["status"])
