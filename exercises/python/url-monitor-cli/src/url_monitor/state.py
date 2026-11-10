from dataclasses import dataclass
from enum import Enum

from url_monitor.checker import CheckResult


class Status(Enum):
    UNKNOWN = "UNKNOWN"
    UP = "UP"
    DOWN = "DOWN"


@dataclass(frozen=True)
class UrlState:
    status: Status = Status.UNKNOWN
    consecutive_failures: int = 0


def apply_result(
    state: UrlState, result: CheckResult, threshold: int
) -> tuple[UrlState, bool]:
    if result.ok:
        new = UrlState(Status.UP, 0)
    else:
        failures = state.consecutive_failures + 1
        status = Status.DOWN if failures >= threshold else state.status
        new = UrlState(status, failures)
    return new, new.status is not state.status
