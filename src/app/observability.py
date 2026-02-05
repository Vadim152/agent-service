"""Минимальные метрики и трейсинг для self-healing."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Iterator


@dataclass
class MetricSnapshot:
    values: dict[str, int]


class InMemoryMetrics:
    def __init__(self) -> None:
        self._counter: Counter[str] = Counter()

    def inc(self, name: str, value: int = 1) -> None:
        self._counter[name] += value

    def snapshot(self) -> MetricSnapshot:
        return MetricSnapshot(values=dict(self._counter))


metrics = InMemoryMetrics()


@contextmanager
def traced_span(name: str) -> Iterator[None]:
    _ = name
    _started = perf_counter()
    try:
        yield
    finally:
        elapsed_ms = int((perf_counter() - _started) * 1000)
        metrics.inc(f"trace.{name}.count")
        metrics.inc(f"trace.{name}.elapsed_ms_total", elapsed_ms)
