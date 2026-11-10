from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    urls: tuple[str, ...]
    log_path: Path
    interval_seconds: float = 20.0
    timeout_seconds: float = 10.0
    failure_threshold: int = 3
