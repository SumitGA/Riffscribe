"""Collects finished spans in memory. OpenTelemetry allows one global tracer provider per process,
so it is installed once and the exporter is emptied before each test."""

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_exporter = InMemorySpanExporter()


def _install() -> None:
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(_exporter))


@pytest.fixture(scope="session")
def _tracing_installed() -> None:
    _install()


@pytest.fixture
def spans(_tracing_installed: None) -> Iterator[InMemorySpanExporter]:
    """Spans finished during the test: `spans.get_finished_spans()`."""
    _exporter.clear()
    yield _exporter
    _exporter.clear()
