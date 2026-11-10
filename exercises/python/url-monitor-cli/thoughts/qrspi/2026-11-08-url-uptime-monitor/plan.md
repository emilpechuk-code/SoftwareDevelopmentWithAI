# Implementation Plan

## Overview

A foreground `url-monitor` CLI (Python 3.11+, `httpx` async) that checks each URL on an interval (default 20 seconds), marks each URL UP or DOWN (DOWN after 3 consecutive failures), prints state changes plus a 1-hour uptime line per URL every cycle, and writes the same lines to a new `url-monitor-YYYYMMDDTHHMMSSZ.log` for each run. Samples live in memory only.

## Environment

Windows, PowerShell. Run every command from the project root:

```
cd c:\Users\nzwv1v\Documents\GitHub\SoftwareDevelopmentWithAI\exercises\python\url-monitor-cli
```

Create the virtual environment once (Phase 1):

```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Test command used in every phase: `python -m pytest -v`. No linter is configured; none is added.

## Line formats (fixed by design.md)

All lines: `[<UTC ISO time>] <WORD padded to 6> <url>  <detail>`.

- `UP     https://x  (HTTP 200, 142ms)`
- `DOWN   https://x  (3 consecutive failures, last: HTTP 503)` or `last: timeout` or `last: connection error`
- `UPTIME https://x  96.7%  (29/30 checks, last 1h)`

Timestamps are `%Y-%m-%dT%H:%M:%SZ`. Log file name is `url-monitor-%Y%m%dT%H%M%SZ.log`.

---

## Phase 1: One cycle, report, and log

### Changes

#### 1. Project metadata
**File**: `pyproject.toml`
**Action**: create

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "url-monitor"
version = "0.1.0"
description = "Check URLs on a schedule and report state changes and 1-hour uptime"
requires-python = ">=3.11"
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
url-monitor = "url_monitor.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/url_monitor"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

#### 2. Package marker
**File**: `src/url_monitor/__init__.py`
**Action**: create

```python
__version__ = "0.1.0"
```

#### 3. Config value object
**File**: `src/url_monitor/config.py`
**Action**: create

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    urls: tuple[str, ...]
    log_path: Path
    interval_seconds: float = 20.0
    timeout_seconds: float = 10.0
    failure_threshold: int = 3
```

#### 4. CLI parsing and entry point
**File**: `src/url_monitor/cli.py`
**Action**: create

```python
import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from url_monitor.config import Config
from url_monitor.cycle import run_cycle
from url_monitor.window import SampleWindow


def _positive_float(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def _positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="url-monitor",
        description="Check one or more URLs and report state changes and 1-hour uptime.",
        epilog=(
            "Each run prints to the terminal and writes the same lines to a new file "
            "named url-monitor-YYYYMMDDTHHMMSSZ.log in the current directory. "
            "The timestamp is the UTC start time of the run."
        ),
    )
    parser.add_argument("urls", nargs="+", metavar="URL", help="URL to check; repeat for more")
    parser.add_argument(
        "--interval", type=_positive_float, default=20.0, metavar="SECONDS",
        help="seconds from the start of one check cycle to the next (default: 20)",
    )
    parser.add_argument(
        "--timeout", type=_positive_float, default=10.0, metavar="SECONDS",
        help="per-request timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--failure-threshold", type=_positive_int, default=3, metavar="N",
        help="consecutive failures before a URL is DOWN (default: 3)",
    )
    return parser


def parse_args(argv: list[str], now: datetime) -> Config:
    args = build_parser().parse_args(argv)
    log_name = f"url-monitor-{now.strftime('%Y%m%dT%H%M%SZ')}.log"
    return Config(
        urls=tuple(args.urls),
        log_path=Path.cwd() / log_name,
        interval_seconds=args.interval,
        timeout_seconds=args.timeout,
        failure_threshold=args.failure_threshold,
    )


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


async def _run_once(config: Config, now: datetime, log) -> None:
    window = SampleWindow()
    async with _make_client() as client:
        await run_cycle(config, client, window, log, now)


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(timezone.utc)
    # argparse exits with code 2 on bad input or --help before the log is created.
    config = parse_args(sys.argv[1:] if argv is None else argv, now)
    with config.log_path.open("x", encoding="utf-8") as log:
        asyncio.run(_run_once(config, now, log))
    return 0
```

#### 5. HTTP checker
**File**: `src/url_monitor/checker.py`
**Action**: create

```python
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

import httpx

ErrorKind = Literal["timeout", "connection error"]


@dataclass(frozen=True)
class CheckResult:
    url: str
    ok: bool
    status_code: int | None
    response_time_ms: int
    error: ErrorKind | None
    checked_at: datetime


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


async def _check_one(
    client: httpx.AsyncClient, url: str, timeout: float, checked_at: datetime
) -> CheckResult:
    start = time.perf_counter()
    try:
        response = await client.get(url, timeout=timeout, follow_redirects=True)
    except httpx.TimeoutException:
        return CheckResult(url, False, None, _elapsed_ms(start), "timeout", checked_at)
    except (httpx.RequestError, httpx.InvalidURL):
        return CheckResult(url, False, None, _elapsed_ms(start), "connection error", checked_at)
    ok = 200 <= response.status_code < 300
    return CheckResult(url, ok, response.status_code, _elapsed_ms(start), None, checked_at)


async def check_urls(
    urls: Sequence[str], timeout: float, client: httpx.AsyncClient, now: datetime
) -> list[CheckResult]:
    results = await asyncio.gather(*(_check_one(client, u, timeout, now) for u in urls))
    return list(results)
```

Note: `gather` keeps the order of `urls` in the returned list.

#### 6. Sliding sample window (in memory)
**File**: `src/url_monitor/window.py`
**Action**: create

```python
from dataclasses import dataclass
from datetime import datetime


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
        return sum(1 for s in samples if s.ok), len(samples)
```

#### 7. Line formatting and terminal + log output
**File**: `src/url_monitor/notifier.py`
**Action**: create

```python
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
```

#### 8. One cycle
**File**: `src/url_monitor/cycle.py`
**Action**: create

```python
from datetime import datetime
from typing import TextIO

import httpx

from url_monitor.checker import check_urls
from url_monitor.config import Config
from url_monitor.notifier import emit, format_up, format_uptime
from url_monitor.window import Sample, SampleWindow


async def run_cycle(
    config: Config,
    client: httpx.AsyncClient,
    window: SampleWindow,
    log: TextIO,
    now: datetime,
) -> None:
    results = await check_urls(config.urls, config.timeout_seconds, client, now)
    for result in results:
        window.record(Sample(result.url, result.ok, result.checked_at))
    # Phase 1 rule: a successful check prints UP. Phase 2 replaces this with transitions.
    for result in results:
        if result.ok:
            emit(format_up(result), log)
    for result in results:
        successes, total = window.uptime(result.url)
        emit(format_uptime(result.url, successes, total, now), log)
```

### Verification

#### Automated
- [x] `python -m pip install -e ".[dev]"` completes without errors
- [x] `python -m pytest tests/test_one_cycle.py -v` passes (all tests in the file)

Test file: **`tests/test_one_cycle.py`** (create). Use `httpx.MockTransport` so no network is used. Tests are sync functions that call `asyncio.run(...)`, so no pytest-asyncio is needed.

Helper used in the tests:

```python
def client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))
```

Test cases:
- [x] `test_200_prints_up_and_uptime`: handler returns `httpx.Response(200)` for `https://example.test/ok`. `run_cycle` with `now = 2026-11-08T17:00:00Z`. Stdout has exactly 2 lines: `[2026-11-08T17:00:00Z] UP     https://example.test/ok  (HTTP 200, <N>ms)` and `[2026-11-08T17:00:00Z] UPTIME https://example.test/ok  100.0%  (1/1 checks, last 1h)`. Use `capsys`; `N` is any non-negative integer (regex).
- [x] `test_503_prints_only_uptime`: handler returns 503. Stdout has exactly one line, the UPTIME line `0.0%  (0/1 checks, last 1h)`. No `UP` line.
- [x] `test_timeout_is_failure`: handler raises `httpx.ConnectTimeout("boom")`. `check_urls` result has `ok=False`, `status_code=None`, `error="timeout"`.
- [x] `test_connection_error_is_failure`: handler raises `httpx.ConnectError("refused")`. Result has `ok=False`, `error="connection error"`.
- [x] `test_redirect_final_status_decides`: handler returns `httpx.Response(301, headers={"Location": "https://example.test/final"})` for `/start` and `httpx.Response(200)` for `/final`. Result has `ok=True`, `status_code=200`.
- [x] `test_results_keep_input_order`: three URLs, results come back in the same order as the input.
- [x] `test_help_lists_flags_and_log_name`: `cli.main(["--help"])` raises `SystemExit` with code `0`. Captured stdout contains `--interval`, `--timeout`, `--failure-threshold`, and `url-monitor-YYYYMMDDTHHMMSSZ.log`.
- [x] `test_no_url_exits_2_and_creates_no_log`: with `monkeypatch.chdir(tmp_path)`, `cli.main([])` raises `SystemExit` with code `2`. `tmp_path` contains no `url-monitor-*.log` file.
- [x] `test_main_log_matches_stdout`: with `monkeypatch.chdir(tmp_path)` and `monkeypatch.setattr(cli, "_make_client", lambda: client_with(lambda r: httpx.Response(200)))`, `cli.main(["https://example.test/ok"])` returns `0`. Exactly one file matching `url-monitor-\d{8}T\d{6}Z\.log` exists. Its text equals captured stdout.

Expected: 9 tests pass.

#### Manual
- [x] `.\.venv\Scripts\url-monitor.exe --help` lists `--interval`, `--timeout`, `--failure-threshold`, and the log file name pattern.
- [x] `.\.venv\Scripts\url-monitor.exe https://example.com` prints one `UP` line and one `UPTIME` line (`100.0%  (1/1 checks, last 1h)`), exits, and creates one new `url-monitor-*.log` with the same two lines.
- [x] Run it twice in a row. Two different log files exist (the names differ by start time).

---

## Phase 2: Outage transitions

### Changes

#### 1. Per-URL state machine
**File**: `src/url_monitor/state.py`
**Action**: create

```python
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
```

#### 2. DOWN line
**File**: `src/url_monitor/notifier.py`
**Action**: modify (add function)

```python
def format_down(result: CheckResult, consecutive_failures: int) -> str:
    reason = (
        f"HTTP {result.status_code}"
        if result.status_code is not None
        else result.error
    )
    return (
        f"[{_ts(result.checked_at)}] {'DOWN':<6} {result.url}  "
        f"({consecutive_failures} consecutive failures, last: {reason})"
    )
```

#### 3. Cycle uses transitions
**File**: `src/url_monitor/cycle.py`
**Action**: modify. Add the `states` parameter and replace the Phase 1 UP rule.

```python
from url_monitor.notifier import emit, format_down, format_up, format_uptime
from url_monitor.state import Status, UrlState, apply_result


async def run_cycle(
    config: Config,
    client: httpx.AsyncClient,
    window: SampleWindow,
    states: dict[str, UrlState],
    log: TextIO,
    now: datetime,
) -> None:
    results = await check_urls(config.urls, config.timeout_seconds, client, now)
    for result in results:
        window.record(Sample(result.url, result.ok, result.checked_at))
    for result in results:
        previous = states.get(result.url, UrlState())
        state, changed = apply_result(previous, result, config.failure_threshold)
        states[result.url] = state
        if changed:
            if state.status is Status.UP:
                emit(format_up(result), log)
            else:
                emit(format_down(result, state.consecutive_failures), log)
    for result in results:
        successes, total = window.uptime(result.url)
        emit(format_uptime(result.url, successes, total, now), log)
```

#### 4. CLI passes the state dict
**File**: `src/url_monitor/cli.py`
**Action**: modify

```python
from url_monitor.state import UrlState

async def _run_once(config: Config, now: datetime, log) -> None:
    window = SampleWindow()
    states: dict[str, UrlState] = {}
    async with _make_client() as client:
        await run_cycle(config, client, window, states, log, now)
```

Phase 1 tests call `run_cycle` without `states`. Add `states={}` to those calls. This is a mechanical signature change only; the Phase 1 expectations stay the same except that a 200 from `UNKNOWN` still prints `UP`.

### Verification

#### Automated
- [x] `python -m pytest tests/test_one_cycle.py -v` still passes (9 tests)
- [x] `python -m pytest tests/test_transitions.py -v` passes

Test file: **`tests/test_transitions.py`** (create).

Unit tests for `apply_result` with threshold 3 unless noted. Build results with `CheckResult(...)` directly.
- [x] `test_first_failure_stays_unknown`: `UrlState()` + failure gives `(UrlState(UNKNOWN, 1), False)`.
- [x] `test_third_failure_goes_down`: from `UNKNOWN` with 2 failures, a third failure gives `(UrlState(DOWN, 3), True)`.
- [x] `test_failure_while_down_is_not_a_change`: from `DOWN`, failure gives `changed == False` and the counter increments.
- [x] `test_success_after_down_goes_up`: from `DOWN`, success gives `(UrlState(UP, 0), True)`.
- [x] `test_success_while_up_is_not_a_change`: from `UP`, success gives `changed == False`.
- [x] `test_first_success_from_unknown_goes_up`: from `UNKNOWN`, success gives `(UrlState(UP, 0), True)`.
- [x] `test_threshold_one_goes_down_immediately`: from `UP`, failure with threshold 1 gives `DOWN` and `True`.

Integration tests through `run_cycle` (handler returns a queue of responses, one per call; `now` advances by a cycle each time):
- [x] `test_three_failures_print_one_down_line`: responses `503, 503, 503, 503`, four cycles. Across all stdout, exactly one line starts with `DOWN` and it is `[...] DOWN   https://example.test/down  (3 consecutive failures, last: HTTP 503)`. Four UPTIME lines appear in total.
- [x] `test_timeout_reason_in_down_line`: `httpx.ConnectTimeout` three times. The DOWN line ends with `last: timeout)`.
- [x] `test_recovery_prints_one_up_line`: `503, 503, 503, 200`. The last cycle prints `UP` with `(HTTP 200, <N>ms)`. No extra state line appears in the cycles that follow a success.
- [x] `test_no_repeat_down_while_failing`: `503` seven times. Exactly one DOWN line in total.

Phase 1 tests must still pass.

Expected: 7 unit tests and 4 integration tests pass, and 9 Phase 1 tests still pass.

#### Manual
- [x] `.\.venv\Scripts\url-monitor.exe http://127.0.0.1:9/` (closed port) runs one cycle and exits. It prints only `UPTIME http://127.0.0.1:9/  0.0%  (0/1 checks, last 1h)`. No `DOWN` line appears, because a single run cannot reach the threshold of 3. This is expected until Phase 3.

---

## Phase 3: Continuous monitoring

### Changes

#### 1. Drop samples older than one hour
**File**: `src/url_monitor/window.py`
**Action**: modify (add method)

```python
from datetime import timedelta

    def drop_older_than(self, now: datetime, window: timedelta = timedelta(hours=1)) -> None:
        cutoff = now - window
        for url, samples in self._samples.items():
            self._samples[url] = [s for s in samples if s.checked_at >= cutoff]
```

#### 2. Prune before reporting
**File**: `src/url_monitor/cycle.py`
**Action**: modify. The structure outline said this should happen before each uptime figure but did not list `cycle.py` under Phase 3. This one line is the change.

```python
    for result in results:
        window.record(Sample(result.url, result.ok, result.checked_at))
    window.drop_older_than(now)
```

#### 3. Loop with interval and clock
**File**: `src/url_monitor/loop.py`
**Action**: create

```python
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TextIO

import httpx

from url_monitor.config import Config
from url_monitor.cycle import run_cycle
from url_monitor.state import UrlState
from url_monitor.window import SampleWindow


async def run_until_stopped(
    config: Config,
    client: httpx.AsyncClient,
    window: SampleWindow,
    states: dict[str, UrlState],
    log: TextIO,
    sleep: Callable[[float], Awaitable[None]],
    clock: Callable[[], datetime],
) -> None:
    while True:
        started = clock()
        await run_cycle(config, client, window, states, log, started)
        elapsed = (clock() - started).total_seconds()
        # Cycles run one after another, so they never overlap. An overrun starts the next cycle now.
        await sleep(max(0.0, config.interval_seconds - elapsed))
```

The structure outline showed only `config, client, sleep, clock`. The window, states, and log are also needed to run a cycle, so they are passed explicitly.

#### 4. Long-running entry point and clean Ctrl-C
**File**: `src/url_monitor/cli.py`
**Action**: modify. Replace `_run_once` and `main`.

```python
from url_monitor.loop import run_until_stopped


async def _monitor(config: Config, log) -> None:
    window = SampleWindow()
    states: dict[str, UrlState] = {}
    async with _make_client() as client:
        await run_until_stopped(
            config,
            client,
            window,
            states,
            log,
            asyncio.sleep,
            lambda: datetime.now(timezone.utc),
        )


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(timezone.utc)
    config = parse_args(sys.argv[1:] if argv is None else argv, now)
    with config.log_path.open("x", encoding="utf-8") as log:
        try:
            asyncio.run(_monitor(config, log))
        except KeyboardInterrupt:
            pass
    return 0
```

The log file is still created before the first cycle. Ctrl-C closes it through the `with` block and returns `0`.

### Verification

#### Automated
- [x] `python -m pytest -v` passes across all three test files

Test file: **`tests/test_loop.py`** (create). Helpers:

```python
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
```

Test cases:
- [x] `test_two_cycles_give_two_uptime_lines_per_url`: two URLs, handler always 200, `stop_after=2`. The run raises `StopLoop`. Stdout has 4 UPTIME lines (2 per URL) and 2 UP lines (one per URL, from `UNKNOWN`). The log text equals stdout.
- [x] `test_sleeps_remaining_interval`: handler returns 200 without advancing the clock. `interval_seconds=20`. `sleeps == [20.0, 20.0]`.
- [x] `test_overrun_sleeps_zero`: handler advances the clock by 25 seconds during each request. `interval_seconds=20`. `sleeps == [0.0, 0.0]`, and the handler is called once per cycle (no overlap).
- [x] `test_old_sample_excluded_from_uptime`: record a `Sample(url, True, now - 61 minutes)` in the window, then `run_cycle` with a 503. The UPTIME line says `0.0%  (0/1 checks, last 1h)`.
- [x] `test_sample_inside_hour_kept`: record a `Sample(url, True, now - 59 minutes)` in the window, then `run_cycle` with a 503. The UPTIME line says `50.0%  (1/2 checks, last 1h)`.
- [x] `test_drop_older_than_removes_only_old_samples`: window with samples at -61 min, -59 min, and now. After `drop_older_than(now)`, `uptime(url)` returns the count of the last two.

Expected: 6 tests pass, plus all earlier tests.

#### Manual
- [x] `.\.venv\Scripts\url-monitor.exe https://example.com --interval 20` prints an UPTIME line roughly every 20 seconds (watch the timestamps for 60+ seconds). Its log file contains the same lines.
- [x] Press Ctrl-C. The process stops, prints nothing extra, and `$LASTEXITCODE` is `0` in the same PowerShell session.
- [x] `.\.venv\Scripts\url-monitor.exe http://127.0.0.1:9/ --interval 5 --failure-threshold 3` prints `DOWN` on the third failed cycle, about 10 to 15 seconds in, with `last: connection error`, and then nothing else until it is stopped.
- [x] `.\.venv\Scripts\url-monitor.exe https://example.com --interval 0` exits with code 2 and prints an argparse error. No log file is created.

---

## Deviations from structure.md

Each is small and tactical. Confirm or redirect before implementation.

1. **`check_urls` and `run_cycle` are `async`.** httpx's async client is the approved choice (design decision 7), so the functions that call it must be async too.
2. **Phase 1 `run_cycle` already accepts `states` in Phase 2.** Phase 1 tests get a mechanical `states={}` update. The structure implied the signature changes in Phase 2 but did not show the Phase 1 test impact.
3. **`cycle.py` changes in Phase 3** to add `drop_older_than`. The structure mentioned pruning but did not list this file for Phase 3.
4. **`run_until_stopped` takes `window`, `states`, and `log`** in addition to the structure's `config, client, sleep, clock`.
5. **Invalid numbers are rejected by argparse**: `--interval`, `--timeout` must be greater than 0, and `--failure-threshold` must be at least 1. Design was silent on this.
6. **`httpx.InvalidURL` counts as a "connection error".** A malformed URL is treated as a failed check rather than a crash. Design was silent on this.
7. **Log file opened with mode `x`.** Two runs that start in the same UTC second would collide, and the second one fails with `FileExistsError` before any check runs. Acceptable for this exercise; the alternative is a random suffix, which is a new naming decision.
8. **Tests use `asyncio.run` in sync test functions** instead of adding `pytest-asyncio`. Keeps dev dependencies to `pytest` only.
9. **Sleep goes through `cli._sleep`.** `main` now loops, so the Phase 1 test `test_main_log_matches_stdout` would never return. The test monkeypatches `cli._sleep` to raise `KeyboardInterrupt`, which is the same path a real Ctrl-C takes. Production code still uses `asyncio.sleep`.

## Testing Checkpoints

- After Phase 1: `python -m pytest tests/test_one_cycle.py` passes (9 tests). A single run prints `UP` on success and `UPTIME` every time, and the log matches stdout.
- After Phase 2: `python -m pytest` passes for both test files (20 tests). A third consecutive failure prints one `DOWN`. A success after that prints one `UP`.
- After Phase 3: all 26 tests pass. The command loops, sleeps the remainder of each interval, prunes samples older than one hour, and exits 0 on Ctrl-C.
