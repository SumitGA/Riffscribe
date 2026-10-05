import json
import logging
import sys

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tabscribe_platform.observability import (
    JsonFormatter,
    LogSettings,
    configure_logging,
    extract_trace,
    inject_trace,
    log_context,
)

pytestmark = pytest.mark.unit


def _record(message: str = "hello", **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, message, (), None)
    record.__dict__.update(extra)
    return record


def test_json_lines_carry_the_bound_context_and_extras() -> None:
    formatter = JsonFormatter("worker")
    with log_context(job_id="j1", stage="tab"), log_context(attempt=2):
        entry = json.loads(formatter.format(_record(duration_s=1.5)))
    assert entry["message"] == "hello"
    assert entry["service"] == "worker"
    assert entry["level"] == "INFO"
    assert (entry["job_id"], entry["stage"], entry["attempt"]) == ("j1", "tab", 2)
    assert entry["duration_s"] == 1.5
    assert "trace_id" not in entry  # no span: no IDs
    # The context ends with the block.
    assert "job_id" not in json.loads(formatter.format(_record()))


def test_json_lines_carry_the_trace(spans: InMemorySpanExporter) -> None:
    formatter = JsonFormatter("api")
    with trace.get_tracer("test").start_as_current_span("work") as span:
        entry = json.loads(formatter.format(_record()))
    ids = span.get_span_context()
    assert entry["trace_id"] == format(ids.trace_id, "032x")
    assert entry["span_id"] == format(ids.span_id, "016x")


def test_exceptions_are_one_field() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "t", logging.ERROR, __file__, 1, "failed", (), exc_info=sys.exc_info()
        )
    entry = json.loads(JsonFormatter("api").format(record))
    assert "ValueError: boom" in entry["exception"]


def test_trace_crosses_the_queue(spans: InMemorySpanExporter) -> None:
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("api submit"):
        carrier = inject_trace()
    assert "traceparent" in carrier
    with tracer.start_as_current_span("stage normalize", context=extract_trace(carrier)):
        pass
    submit, stage = sorted(spans.get_finished_spans(), key=lambda s: s.name)
    assert stage.context.trace_id == submit.context.trace_id
    assert stage.parent is not None and stage.parent.span_id == submit.context.span_id


def test_configure_logging(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        configure_logging("api", LogSettings(level="WARNING", format="json"))
        logging.getLogger("x").info("hidden")
        logging.getLogger("x").warning("shown", extra={"job_id": "j9"})
        [line] = capsys.readouterr().err.strip().splitlines()
        assert json.loads(line)["job_id"] == "j9"
    finally:
        root.handlers[:], level = saved
        root.setLevel(level)
