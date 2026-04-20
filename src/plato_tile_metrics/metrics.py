"""Fleet tile analytics."""

import time
from collections import Counter

class TileMetrics:
    def __init__(self):
        self._tiles: list[dict] = []

    def record(self, tile: dict):
        self._tiles.append(tile)

    def record_batch(self, tiles: list[dict]):
        self._tiles.extend(tiles)

    def domain_distribution(self) -> dict[str, int]:
        return dict(Counter(t.get("domain", "unknown") for t in self._tiles))

    def confidence_histogram(self, buckets: int = 10) -> dict[str, int]:
        hist = {}
        for t in self._tiles:
            conf = t.get("confidence", 0.5)
            bucket = f"{int(conf * buckets) / buckets:.1f}"
            hist[bucket] = hist.get(bucket, 0) + 1
        return hist

    def avg_confidence(self) -> float:
        if not self._tiles: return 0.0
        return sum(t.get("confidence", 0) for t in self._tiles) / len(self._tiles)

    def quality_score(self) -> float:
        if not self._tiles: return 0.0
        conf = self.avg_confidence()
        domains = len(self.domain_distribution())
        diversity = min(domains / 10, 1.0)
        return conf * 0.7 + diversity * 0.3

    def growth_rate(self) -> float:
        if len(self._tiles) < 2: return 0.0
        times = sorted(t.get("timestamp", t.get("created_at", 0)) for t in self._tiles)
        span = times[-1] - times[0] if times[-1] != times[0] else 1
        return len(self._tiles) / (span / 3600) if span > 0 else 0.0

    def coverage_score(self, required_domains: list[str] = None) -> float:
        required = required_domains or ["constraint-theory", "tiles", "governance", "forge", "fleet"]
        present = set(self.domain_distribution().keys())
        return len(present & set(required)) / len(required)

    @property
    def stats(self) -> dict:
        return {"total": len(self._tiles), "domains": len(self.domain_distribution()),
                "avg_confidence": self.avg_confidence(), "quality": self.quality_score(),
                "coverage": self.coverage_score()}
