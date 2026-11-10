from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Sample:
    url: str
    ok: bool
    checked_at: datetime


class SampleWindow:
    def __init__(self) -> None:
        self._samples: dict[str, list[Sample]] = {}

    def record(self, sample: Sample) -> None:
        self._samples.setdefault(sample.url, []).append(sample)

    def uptime(self, url: str) -> tuple[int, int]:
        samples = self._samples.get(url, [])
        return sum(1 for sample in samples if sample.ok), len(samples)

    def drop_older_than(self, now: datetime, window: timedelta = timedelta(hours=1)) -> None:
        cutoff = now - window
        for url, samples in self._samples.items():
            self._samples[url] = [s for s in samples if s.checked_at >= cutoff]
