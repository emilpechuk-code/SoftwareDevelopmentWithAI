import sys
from datetime import datetime
from typing import TextIO

from url_monitor.checker import CheckResult


def _ts(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_up(result: CheckResult) -> str:
    return (
        f"[{_ts(result.checked_at)}] {'UP':<6} {result.url}  "
        f"(HTTP {result.status_code}, {result.response_time_ms}ms)"
    )


def format_down(result: CheckResult, consecutive_failures: int) -> str:
    reason = (
        f"HTTP {result.status_code}" if result.status_code is not None else result.error
    )
    return (
        f"[{_ts(result.checked_at)}] {'DOWN':<6} {result.url}  "
        f"({consecutive_failures} consecutive failures, last: {reason})"
    )


def format_uptime(url: str, successes: int, total: int, at: datetime) -> str:
    percent = successes / total * 100
    return (
        f"[{_ts(at)}] {'UPTIME':<6} {url}  {percent:.1f}%  "
        f"({successes}/{total} checks, last 1h)"
    )


def emit(line: str, log: TextIO, out: TextIO | None = None) -> None:
    target = out if out is not None else sys.stdout
    print(line, file=target)
    target.flush()
    log.write(line + "\n")
    log.flush()
