"""Structured logs and traces for the API and the worker (CLAUDE.md: both carry `job_id`).

- Logs: one JSON object per line on stderr. Fields bound with `log_context(job_id=...)` are added
  to every record logged inside the block, including the pipeline's own logs, together with the
  current trace and span IDs, so a log line leads to its trace and back.
- Traces: OpenTelemetry, configured by the standard OTEL_* variables. Spans are exported only
  when OTEL_EXPORTER_OTLP_ENDPOINT is set; otherwise they still give log lines their trace IDs.
  A job's trace crosses the queue in `StageMessage.trace` (`inject_trace` / `extract_trace`).
"""

import contextvars
import json
import logging
import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_context: contextvars.ContextVar[Mapping[str, Any]] = contextvars.ContextVar(
    "log_context", default=MappingProxyType({})
)

# Attributes every LogRecord has; anything else was passed with `extra=` and is logged as a field.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class LogSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOG_", frozen=True, extra="ignore")

    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    format: Literal["json", "text"] = "json"  # `text` is easier to read in a dev terminal


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Add `fields` to every log record inside the block (nested blocks add to the outer one)."""
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def current_log_context() -> Mapping[str, Any]:
    return _context.get()


def _trace_ids() -> dict[str, str]:
    span = trace.get_current_span().get_span_context()
    if not span.is_valid:
        return {}
    return {"trace_id": format(span.trace_id, "032x"), "span_id": format(span.span_id, "016x")}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
            **_context.get(),
            **_trace_ids(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields = {**_context.get()}
        fields.update(
            (k, v)
            for k, v in record.__dict__.items()
            if k not in _STANDARD_ATTRS and not k.startswith("_")
        )
        return f"{line}  {' '.join(f'{k}={v}' for k, v in fields.items())}" if fields else line


def configure_logging(service: str, settings: LogSettings | None = None) -> None:
    settings = settings or LogSettings()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        JsonFormatter(service)
        if settings.format == "json"
        else _TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.level)
    # Uvicorn installs its own handlers; route its logs through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True


def configure_tracing(service: str) -> None:
    """Install the global tracer provider. OTEL_SERVICE_NAME, if set, overrides `service`."""
    resource = Resource.create({SERVICE_NAME: os.environ.get("OTEL_SERVICE_NAME", service)})
    provider = TracerProvider(resource=resource)
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
    ):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def inject_trace() -> dict[str, str]:
    """The current trace context (W3C `traceparent`), to put in a queue message."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def extract_trace(carrier: Mapping[str, str]) -> otel_context.Context:
    """Context to start a span in, continuing the trace in `carrier`."""
    return propagate.extract(dict(carrier))
