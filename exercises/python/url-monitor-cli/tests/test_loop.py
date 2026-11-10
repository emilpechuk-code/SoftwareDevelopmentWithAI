import asyncio
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import httpx
import pytest

from url_monitor.config import Config
from url_monitor.cycle import run_cycle
from url_monitor.loop import run_until_stopped
from url_monitor.state import UrlState
from url_monitor.window import Sample, SampleWindow

NOW = datetime(2026, 11, 8, 17, 0, 0, tzinfo=timezone.utc)
URL_A = "https://example.test/a"
URL_B = "https://example.test/b"


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class StopLoop(Exception):
    pass


def make_sleep(clock: FakeClock, sleeps: list[float], stop_after: int):
    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)
        if len(sleeps) >= stop_after:
            raise StopLoop

    return sleep


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run_loop(handler, clock: FakeClock, sleeps: list[float], stop_after: int, *urls: str,
             interval: float = 20.0) -> str:
    buffer = StringIO()
    config = Config(urls=urls, log_path=Path("unused.log"), interval_seconds=interval)

    async def once() -> None:
        async with make_client(handler) as client:
            await run_until_stopped(
                config,
                client,
                SampleWindow(),
                {},
                buffer,
                make_sleep(clock, sleeps, stop_after),
                clock,
            )

    with pytest.raises(StopLoop):
        asyncio.run(once())
    return buffer.getvalue()


def test_two_cycles_give_two_uptime_lines_per_url(capsys: pytest.CaptureFixture[str]) -> None:
    clock = FakeClock(NOW)
    sleeps: list[float] = []
    text = run_loop(lambda request: httpx.Response(200), clock, sleeps, 2, URL_A, URL_B)
    lines = text.splitlines()
    assert sum(1 for line in lines if "] UPTIME " in line) == 4
    assert sum(1 for line in lines if "] UP     " in line) == 2
    assert capsys.readouterr().out == text


def test_sleeps_remaining_interval() -> None:
    clock = FakeClock(NOW)
    sleeps: list[float] = []
    run_loop(lambda request: httpx.Response(200), clock, sleeps, 2, URL_A, interval=20.0)
    assert sleeps == [20.0, 20.0]


def test_overrun_sleeps_zero() -> None:
    clock = FakeClock(NOW)
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        clock.advance(25)
        return httpx.Response(200)

    run_loop(handler, clock, sleeps, 2, URL_A, interval=20.0)
    assert sleeps == [0.0, 0.0]
    assert calls == 2


def test_old_sample_excluded_from_uptime() -> None:
    buffer = StringIO()
    window = SampleWindow()
    window.record(Sample(URL_A, True, NOW - timedelta(minutes=61)))
    config = Config(urls=(URL_A,), log_path=Path("unused.log"))

    async def once() -> None:
        async with make_client(lambda request: httpx.Response(503)) as client:
            await run_cycle(config, client, window, {}, buffer, NOW)

    asyncio.run(once())
    assert buffer.getvalue().splitlines()[-1] == (
        "[2026-11-08T17:00:00Z] UPTIME https://example.test/a  0.0%  (0/1 checks, last 1h)"
    )


def test_sample_inside_hour_kept() -> None:
    buffer = StringIO()
    window = SampleWindow()
    window.record(Sample(URL_A, True, NOW - timedelta(minutes=59)))
    config = Config(urls=(URL_A,), log_path=Path("unused.log"))

    async def once() -> None:
        async with make_client(lambda request: httpx.Response(503)) as client:
            await run_cycle(config, client, window, {}, buffer, NOW)

    asyncio.run(once())
    assert buffer.getvalue().splitlines()[-1] == (
        "[2026-11-08T17:00:00Z] UPTIME https://example.test/a  50.0%  (1/2 checks, last 1h)"
    )


def test_drop_older_than_removes_only_old_samples() -> None:
    window = SampleWindow()
    window.record(Sample(URL_A, True, NOW - timedelta(minutes=61)))
    window.record(Sample(URL_A, False, NOW - timedelta(minutes=59)))
    window.record(Sample(URL_A, True, NOW))
    window.drop_older_than(NOW)
    assert window.uptime(URL_A) == (1, 2)
