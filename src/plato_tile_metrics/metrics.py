"""Tile metrics — counters, gauges, histograms, percentiles, time windows."""
import time
import math
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

@dataclass
class Metric:
    name: str
    value: float = 0.0
    timestamp: float = field(default_factory=time.time)
    tags: dict = field(default_factory=dict)

@dataclass
class HistogramBucket:
    le: float  # less-than-or-equal
    count: int = 0

class TileMetrics:
    def __init__(self, retention: int = 10000):
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._time_series: dict[str, list[Metric]] = defaultdict(list)
        self.retention = retention

    # Counters
    def increment(self, name: str, amount: float = 1.0, tags: dict = None) -> float:
        self._counters[name] += amount
        return self._counters[name]

    def decrement(self, name: str, amount: float = 1.0) -> float:
        return self.increment(name, -amount)

    def get_counter(self, name: str) -> float:
        return self._counters[name]

    def reset_counter(self, name: str):
        self._counters[name] = 0.0

    # Gauges
    def set_gauge(self, name: str, value: float, tags: dict = None):
        self._gauges[name] = value
        m = Metric(name=name, value=value, tags=tags or {})
        self._append_series(name, m)

    def get_gauge(self, name: str) -> float:
        return self._gauges.get(name, 0.0)

    # Histograms
    def record(self, name: str, value: float):
        hist = self._histograms[name]
        hist.append(value)
        if len(hist) > self.retention:
            self._histograms[name] = hist[-self.retention:]

    def histogram_stats(self, name: str) -> dict:
        values = self._histograms.get(name, [])
        if not values:
            return {"count": 0, "min": 0, "max": 0, "mean": 0, "p50": 0, "p95": 0, "p99": 0, "stddev": 0}
        n = len(values)
        values_sorted = sorted(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        stddev = math.sqrt(variance)
        return {"count": n, "min": values_sorted[0], "max": values_sorted[-1],
                "mean": round(mean, 4),
                "p50": round(values_sorted[int(n * 0.50)], 4),
                "p90": round(values_sorted[int(n * 0.90)], 4),
                "p95": round(values_sorted[int(n * 0.95)], 4),
                "p99": round(values_sorted[min(int(n * 0.99), n - 1)], 4),
                "stddev": round(stddev, 4)}

    def percentile(self, name: str, p: float) -> float:
        values = sorted(self._histograms.get(name, []))
        if not values:
            return 0.0
        idx = min(int(len(values) * p), len(values) - 1)
        return values[idx]

    # Time series
    def _append_series(self, name: str, metric: Metric):
        series = self._time_series[name]
        series.append(metric)
        if len(series) > self.retention:
            self._time_series[name] = series[-self.retention:]

    def record_ts(self, name: str, value: float, tags: dict = None):
        m = Metric(name=name, value=value, tags=tags or {})
        self._append_series(name, m)

    def trend(self, name: str, window: float = 3600.0) -> dict:
        """Trend analysis over a time window."""
        series = self._time_series.get(name, [])
        now = time.time()
        recent = [m for m in series if now - m.timestamp < window]
        if len(recent) < 2:
            return {"direction": "insufficient_data", "samples": len(recent)}
        values = [m.value for m in recent]
        first_half = values[:len(values) // 2]
        second_half = values[len(values) // 2:]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        change = (avg_second - avg_first) / max(abs(avg_first), 0.001)
        direction = "up" if change > 0.01 else ("down" if change < -0.01 else "stable")
        return {"direction": direction, "change_pct": round(change * 100, 2),
                "samples": len(recent), "window_s": window,
                "avg_first": round(avg_first, 4), "avg_second": round(avg_second, 4)}

    def aggregate(self, prefix: str = "") -> dict:
        """Aggregate all metrics matching prefix."""
        result = {}
        for name, val in self._counters.items():
            if not prefix or name.startswith(prefix):
                result[f"counter:{name}"] = val
        for name, val in self._gauges.items():
            if not prefix or name.startswith(prefix):
                result[f"gauge:{name}"] = val
        for name in self._histograms:
            if not prefix or name.startswith(prefix):
                result[f"hist:{name}"] = self.histogram_stats(name)
        return result

    def snapshot(self) -> dict:
        return {"counters": dict(self._counters), "gauges": dict(self._gauges),
                "histograms": {k: self.histogram_stats(k) for k in self._histograms},
                "time_series": {k: len(v) for k, v in self._time_series.items()}}

    @property
    def stats(self) -> dict:
        return {"counters": len(self._counters), "gauges": len(self._gauges),
                "histograms": len(self._histograms),
                "time_series": len(self._time_series),
                "retention": self.retention}
