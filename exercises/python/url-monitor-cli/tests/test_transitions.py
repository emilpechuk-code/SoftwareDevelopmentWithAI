import asyncio
import re
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import httpx

from url_monitor.checker import CheckResult
from url_monitor.config import Config
from url_monitor.cycle import run_cycle
from url_monitor.state import Status, UrlState, apply_result
from url_monitor.window import SampleWindow

NOW = datetime(2026, 11, 8, 17, 0, 0, tzinfo=timezone.utc)
URL = "https://example.test/down"
CYCLE = timedelta(seconds=20)


def failure(status_code: int | None = 503, error: str | None = None) -> CheckResult:
    return CheckResult(URL, False, status_code, 5, error, NOW)


def success() -> CheckResult:
    return CheckResult(URL, True, 200, 10, None, NOW)


def test_first_failure_stays_unknown() -> None:
    assert apply_result(UrlState(), failure(), 3) == (UrlState(Status.UNKNOWN, 1), False)


def test_third_failure_goes_down() -> None:
    state = UrlState(Status.UNKNOWN, 2)
    assert apply_result(state, failure(), 3) == (UrlState(Status.DOWN, 3), True)


def test_failure_while_down_is_not_a_change() -> None:
    state, changed = apply_result(UrlState(Status.DOWN, 3), failure(), 3)
    assert changed is False
    assert state == UrlState(Status.DOWN, 4)


def test_success_after_down_goes_up() -> None:
    assert apply_result(UrlState(Status.DOWN, 3), success(), 3) == (UrlState(Status.UP, 0), True)


def test_success_while_up_is_not_a_change() -> None:
    state, changed = apply_result(UrlState(Status.UP, 0), success(), 3)
    assert changed is False
    assert state == UrlState(Status.UP, 0)


def test_first_success_from_unknown_goes_up() -> None:
    assert apply_result(UrlState(), success(), 3) == (UrlState(Status.UP, 0), True)


def test_threshold_one_goes_down_immediately() -> None:
    state, changed = apply_result(UrlState(Status.UP, 0), failure(), 1)
    assert changed is True
    assert state.status is Status.DOWN


def client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def queue_handler(items: list[int | Exception]):
    pending = list(items)

    def handler(request: httpx.Request) -> httpx.Response:
        item = pending.pop(0)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(item)

    return handler


def run_cycles(items: list[int | Exception], threshold: int = 3) -> str:
    buffer = StringIO()
    config = Config(urls=(URL,), log_path=Path("unused.log"), failure_threshold=threshold)

    async def once() -> None:
        states: dict[str, UrlState] = {}
        window = SampleWindow()
        moment = NOW
        async with client_with(queue_handler(items)) as client:
            for _ in items:
                await run_cycle(config, client, window, states, buffer, moment)
                moment += CYCLE

    asyncio.run(once())
    return buffer.getvalue()


def test_three_failures_print_one_down_line() -> None:
    text = run_cycles([503, 503, 503, 503])
    lines = text.splitlines()
    down = [line for line in lines if "] DOWN   " in line]
    assert down == [
        "[2026-11-08T17:00:40Z] DOWN   https://example.test/down  "
        "(3 consecutive failures, last: HTTP 503)"
    ]
    assert sum(1 for line in lines if "UPTIME" in line) == 4


def test_timeout_reason_in_down_line() -> None:
    text = run_cycles([httpx.ConnectTimeout("boom")] * 3)
    down = [line for line in text.splitlines() if "] DOWN   " in line]
    assert len(down) == 1
    assert down[0].endswith("last: timeout)")


def test_recovery_prints_one_up_line() -> None:
    text = run_cycles([503, 503, 503, 200])
    lines = text.splitlines()
    up = [line for line in lines if "] UP     " in line]
    assert len(up) == 1
    assert re.fullmatch(
        r"\[2026-11-08T17:01:00Z\] UP     https://example\.test/down  \(HTTP 200, \d+ms\)",
        up[0],
    )
    assert sum(1 for line in lines if "] DOWN   " in line) == 1


def test_no_repeat_down_while_failing() -> None:
    text = run_cycles([503] * 7)
    down = [line for line in text.splitlines() if "] DOWN   " in line]
    assert len(down) == 1
