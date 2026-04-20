"""Tile metrics — aggregation, histograms, percentiles, anomaly detection, windowed stats."""
import time
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum

class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"

@dataclass
class MetricPoint:
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: dict = field(default_factory=dict)
    metric_type: MetricType = MetricType.GAUGE

@dataclass
class HistogramBucket:
    le: float   # less-than-or-equal boundary
    count: int = 0

@dataclass
class MetricSnapshot:
    name: str
    count: int = 0
    sum_val: float = 0.0
    min_val: float = float('inf')
    max_val: float = float('-inf')
    avg_val: float = 0.0
    p50: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    std_dev: float = 0.0
    timestamp: float = field(default_factory=time.time)

@dataclass
class AnomalyEvent:
    metric: str
    value: float
    expected_min: float
    expected_max: float
    severity: str
    timestamp: float = field(default_factory=time.time)

class TileMetrics:
    def __init__(self, retention: int = 10000):
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._timeline: deque = deque(maxlen=retention)
        self._windows: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._anomalies: list[AnomalyEvent] = []
        self._baselines: dict[str, dict] = {}

    def counter(self, name: str, value: float = 1.0, tags: dict = None):
        key = self._key(name, tags)
        self._counters[key] += value
        self._timeline.append(MetricPoint(name, value, tags=tags or {}, metric_type=MetricType.COUNTER))

    def gauge(self, name: str, value: float, tags: dict = None):
        key = self._key(name, tags)
        self._gauges[key] = value
        self._timeline.append(MetricPoint(name, value, tags=tags or {}, metric_type=MetricType.GAUGE))
        self._check_anomaly(name, value)

    def histogram(self, name: str, value: float, tags: dict = None):
        key = self._key(name, tags)
        self._histograms[key].append(value)
        self._timeline.append(MetricPoint(name, value, tags=tags or {}, metric_type=MetricType.HISTOGRAM))

    def timing(self, name: str, start_time: float, tags: dict = None):
        elapsed = (time.time() - start_time) * 1000  # ms
        self.histogram(name, elapsed, tags)

    def get_counter(self, name: str, tags: dict = None) -> float:
        return self._counters.get(self._key(name, tags), 0.0)

    def get_gauge(self, name: str, tags: dict = None) -> Optional[float]:
        return self._gauges.get(self._key(name, tags))

    def get_histogram_stats(self, name: str, tags: dict = None) -> MetricSnapshot:
        key = self._key(name, tags)
        values = self._histograms.get(key, [])
        if not values:
            return MetricSnapshot(name=name)
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        mean = sum(sorted_vals) / n
        variance = sum((v - mean) ** 2 for v in sorted_vals) / n if n > 0 else 0
        return MetricSnapshot(
            name=name, count=n, sum_val=sum(sorted_vals),
            min_val=sorted_vals[0], max_val=sorted_vals[-1], avg_val=mean,
            p50=self._percentile(sorted_vals, 0.50),
            p90=self._percentile(sorted_vals, 0.90),
            p95=self._percentile(sorted_vals, 0.95),
            p99=self._percentile(sorted_vals, 0.99),
            std_dev=math.sqrt(variance)
        )

    def window(self, name: str, duration: float = 60.0) -> list[MetricPoint]:
        cutoff = time.time() - duration
        return [p for p in self._timeline if p.name == name and p.timestamp >= cutoff]

    def window_aggregate(self, name: str, duration: float = 60.0) -> dict:
        points = self.window(name, duration)
        if not points:
            return {"count": 0, "sum": 0, "avg": 0, "min": 0, "max": 0}
        values = [p.value for p in points]
        return {"count": len(values), "sum": sum(values), "avg": sum(values)/len(values),
                "min": min(values), "max": max(values)}

    def rate(self, name: str, window_s: float = 60.0) -> float:
        points = self.window(name, window_s)
        if len(points) < 2:
            return 0.0
        duration = points[-1].timestamp - points[0].timestamp
        if duration <= 0:
            return 0.0
        return sum(p.value for p in points) / duration

    def set_baseline(self, name: str, mean: float, std: float, k: float = 3.0):
        self._baselines[name] = {"mean": mean, "std": std, "k": k}

    def learn_baseline(self, name: str, window_s: float = 300.0):
        points = self.window(name, window_s)
        values = [p.value for p in points]
        if len(values) < 10:
            return
        mean = sum(values) / len(values)
        std = math.sqrt(sum((v - mean)**2 for v in values) / len(values))
        self.set_baseline(name, mean, std)

    def _check_anomaly(self, name: str, value: float):
        baseline = self._baselines.get(name)
        if not baseline:
            return
        mean, std, k = baseline["mean"], baseline["std"], baseline["k"]
        expected_min = mean - k * std
        expected_max = mean + k * std
        if value < expected_min or value > expected_max:
            severity = "warning" if abs(value - mean) < 2 * k * std else "critical"
            self._anomalies.append(AnomalyEvent(
                metric=name, value=value, expected_min=expected_min,
                expected_max=expected_max, severity=severity
            ))

    def anomalies(self, limit: int = 20) -> list[AnomalyEvent]:
        return self._anomalies[-limit:]

    def all_metrics(self) -> dict:
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {k: len(v) for k, v in self._histograms.items()},
            "baselines": self._baselines,
            "anomaly_count": len(self._anomalies),
        }

    def _key(self, name: str, tags: dict = None) -> str:
        if tags:
            tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
            return f"{name}|{tag_str}"
        return name

    @staticmethod
    def _percentile(sorted_vals: list[float], p: float) -> float:
        if not sorted_vals:
            return 0.0
        idx = int(len(sorted_vals) * p)
        idx = min(idx, len(sorted_vals) - 1)
        return sorted_vals[idx]

    @property
    def stats(self) -> dict:
        return {"counters": len(self._counters), "gauges": len(self._gauges),
                "histograms": len(self._histograms), "timeline_points": len(self._timeline),
                "baselines": len(self._baselines), "anomalies": len(self._anomalies)}
