# Structure Outline

## Approach

Build the confirmed CLI in three vertical slices. Each slice parses or reuses config, checks URLs, updates in-memory results, and writes the same lines to stdout and the timestamped log. There is no `research.md`; this is greenfield. Phase 1 runs a single cycle and exits. Phase 3 is what turns that into the long-running process. No per-check line is added in any phase.

## Phase 1: One cycle, report, and log

One invocation checks every URL once, concurrently, then exits. A successful check prints an `UP` line (the one-sample case of leaving `UNKNOWN`). A failed check prints no state line. Every URL prints one `UPTIME` line from the in-memory sample just recorded. Both streams receive the same text. `--help` documents the flags and the log name. Usage errors go to stderr and do not create a log.

**Files**: `pyproject.toml`, `src/url_monitor/__init__.py`, `src/url_monitor/cli.py`, `src/url_monitor/config.py`, `src/url_monitor/checker.py`, `src/url_monitor/window.py`, `src/url_monitor/notifier.py`, `src/url_monitor/cycle.py`, `tests/test_one_cycle.py`

**Key changes**:

- `Config { urls: tuple[str, ...], interval_seconds: float = 20, timeout_seconds: float = 10, failure_threshold: int = 3, log_path: Path }` — new
- `parse_args(argv: list[str], now: datetime) -> Config` — new. `now` stamps `log_path` as `url-monitor-YYYYMMDDTHHMMSSZ.log` in the working directory.
- `CheckResult { url: str, ok: bool, status_code: int | None, response_time_ms: int, error: Literal["timeout", "connection error"] | None, checked_at: datetime }` — new
- `check_urls(urls: Sequence[str], timeout: float, client: httpx.AsyncClient, now: datetime) -> list[CheckResult]` — new. Concurrent GETs, redirects followed, final status decides `ok`.
- `Sample { url: str, ok: bool, checked_at: datetime }` — new
- `SampleWindow.record(sample: Sample) -> None` — new
- `SampleWindow.uptime(url: str) -> tuple[int, int]` — new. Returns `(successes, total)` for samples held so far.
- `format_up(result: CheckResult) -> str` — new
- `format_uptime(url: str, successes: int, total: int, at: datetime) -> str` — new. One decimal percent and `(successes/total checks, last 1h)`.
- `emit(line: str, log: TextIO) -> None` — new. Writes the line to stdout and `log`.
- `run_cycle(config: Config, client: httpx.AsyncClient, window: SampleWindow, log: TextIO, now: datetime) -> None` — new

**Verify**: `pytest tests/test_one_cycle.py` passes. A mocked 200 prints one `UP` line and one `UPTIME` line, and the log file matches stdout. A mocked 503 prints only `UPTIME` (`0.0% (0/1 checks, last 1h)`). `--help` mentions `--interval`, `--timeout`, `--failure-threshold`, and `url-monitor-YYYYMMDDTHHMMSSZ.log`. No URL argument exits non-zero on stderr and creates no log.

---

## Phase 2: Outage transitions

Replace the one-sample "success prints UP" rule with the state tracker. Repeated cycles on the same tracker emit `DOWN` at the threshold and `UP` on the next success. Further failures while `DOWN`, and further successes while `UP`, emit no extra state line. The CLI still runs one cycle; tests drive the threshold by calling `run_cycle` again.

**Files**: `src/url_monitor/state.py`, `src/url_monitor/cycle.py`, `src/url_monitor/notifier.py`, `tests/test_transitions.py`

**Key changes**:

- `Status(Enum)` — `UNKNOWN`, `UP`, `DOWN`
- `UrlState { status: Status = UNKNOWN, consecutive_failures: int = 0 }` — new
- `apply_result(state: UrlState, result: CheckResult, threshold: int) -> tuple[UrlState, bool]` — new. The bool is true only when `status` changes. One success yields `UP` and resets the counter. A failure increments the counter and yields `DOWN` once `consecutive_failures >= threshold`.
- `format_down(result: CheckResult, consecutive_failures: int) -> str` — new. Reason text is `HTTP <status>`, `timeout`, or `connection error`.
- `run_cycle(..., states: dict[str, UrlState]) -> None` — modified. Emits `format_up` or `format_down` only when `apply_result` reports a change, then always emits `UPTIME`.

**Verify**: `pytest tests/test_transitions.py` passes. Three mocked failures then print one `DOWN` line on the third cycle and none on a fourth failure. The next mocked 200 prints one `UP` line. Phase 1 tests still pass. A live one-shot run still will not show `DOWN`; that needs the loop in Phase 3.

---

## Phase 3: Continuous monitoring

The command loops until Ctrl-C. Cycles start `--interval` seconds apart and never overlap. A cycle that overruns starts the next one immediately. The sample window drops samples older than one hour before each uptime figure. Ctrl-C closes the log and exits 0. Samples are not read back from the log.

**Files**: `src/url_monitor/loop.py`, `src/url_monitor/cli.py`, `src/url_monitor/window.py`, `tests/test_loop.py`

**Key changes**:

- `SampleWindow.drop_older_than(now: datetime, window: timedelta = timedelta(hours=1)) -> None` — new
- `run_until_stopped(config: Config, client: httpx.AsyncClient, sleep: Callable[[float], Awaitable[None]], clock: Callable[[], datetime]) -> None` — new. Calls `run_cycle`, then sleeps the remaining interval. `asyncio.CancelledError` / `KeyboardInterrupt` ends the loop.
- `cli.main(argv: list[str]) -> int` — modified. Opens the log, installs the Ctrl-C handler, calls `run_until_stopped`, returns 0.

**Verify**: `pytest tests/test_loop.py` passes with a fake clock and fake sleep. Two cycles produce two `UPTIME` lines per URL and only the real state changes. A sample stamped 61 minutes earlier is excluded from the percentage. A cycle longer than the interval does not start a second cycle in parallel, and the next sleep is 0. `pytest` passes overall. Manually: `url-monitor https://example.com --interval 20` prints `UPTIME` about every 20 seconds, writes the same lines to a new timestamped log, and Ctrl-C stops it with exit code 0. Pointing at a closed port prints `DOWN` on the third failure.

## Testing Checkpoints

- After Phase 1: one cycle, `UP` on success, `UPTIME` always, stdout matches the log, `--help` and usage errors behave.
- After Phase 2: threshold, recovery, and no repeat state lines, still with one CLI cycle.
- After Phase 3: scheduled loop, one-hour window, clean Ctrl-C. This is the design's end state.
