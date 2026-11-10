# Design Discussion

## Current State

Greenfield. There is no application code, no `src/`, no `pyproject.toml`, and no `.cursor/rules/` or `docs/rules/`.

Documented constraints:

- Python 3.11+ (`README.md:49`). Implementation waits until Step 6 (`README.md:44`).
- `README.md:17-27` shows a CLI shape and two example lines (DOWN with the last HTTP status, UP with status and response time). Interval `30` and `--log-file monitor.log` in that example are not the decisions for this run.
- `goal.md` asks for monitoring, response time, outage detection, uptime percentage, historical results, failure notifications, and dashboards or reports. Answers narrowed that to a CLI report.
- `thoughts/qrspi/2026-07-29-url-monitor-cli/` is an older CLI-only pass. It is not input here.

Decisions already made live in `answers.md` in this directory. This document does not reopen them.

## Desired End State

A long-running `url-monitor` command. The user passes one or more URLs and may override interval, timeout, and failure threshold. The process checks every URL on a schedule until Ctrl-C, prints state changes and a 1-hour uptime figure, and appends those same lines to a new timestamped log file created at startup.

```bash
url-monitor https://example.com https://api.example.com/health \
  --interval 20 \
  --timeout 10 \
  --failure-threshold 3
```

```
[2026-11-08T17:33:00Z] DOWN   https://example.com  (3 consecutive failures, last: HTTP 503)
[2026-11-08T17:33:20Z] UPTIME https://example.com  96.7%  (29/30 checks, last 1h)
[2026-11-08T17:34:00Z] UP     https://example.com  (HTTP 200, 142ms)
```

`url-monitor --help` lists every parameter, states each default, and explains that the run creates `url-monitor-YYYYMMDDTHHMMSSZ.log` in the working directory.

Verification: pytest, with HTTP and the clock faked. Tests cover a failure becoming DOWN at the threshold, one success returning to UP, the rolling one-hour percentage, identical terminal and log text, and `--help` mentioning each flag and the log name. No real network and no real sleep.

## Patterns to Follow

- Runtime is Python 3.11+ (`README.md:49`).
- State-change wording follows the exercise examples (`README.md:26-27`): a UTC timestamp, a status word, the URL, then a short parenthetical. UP includes the HTTP status and response time in milliseconds. DOWN includes how many consecutive failures and the last failure.
- Do not copy `README.md:19-23` literally. `--interval` defaults to 20 seconds, not 30. There is no `--log-file` flag. The log path is generated.
- Do not follow `thoughts/qrspi/2026-07-29-url-monitor-cli/`. That pass assumed a single shared log and did not define a one-hour in-memory window.
- No project coding-style rules exist. Use the standard library for argument parsing (`argparse`). The only required runtime dependency is `httpx`.

## Design Decisions

1. **Process shape**: One foreground process. A poll loop runs until Ctrl-C. No daemon, no web server.

2. **Components**:
   - **CLI** parses arguments and prints help.
   - **Config** is the parsed values: URL list, interval, timeout, failure threshold, log path.
   - **Checker** performs one HTTP GET per URL with `httpx` async, concurrently within a cycle, following redirects. Response time is total elapsed time. Timeout is the per-request `--timeout`.
   - **State tracker** keeps `UNKNOWN`, `UP`, or `DOWN` plus a consecutive-failure count per URL.
   - **Sample window** keeps in-memory check results for the last hour per URL.
   - **Notifier** formats lines and writes each line to stdout and the run log.
   - **Poll loop** starts a cycle, waits until every URL in that cycle has finished, records results, emits lines, then waits until `--interval` has elapsed since the cycle started. If a cycle runs longer than the interval, the next cycle starts immediately. Cycles never overlap.

3. **Outage state machine**: Every URL starts `UNKNOWN` with zero consecutive failures. A failed check (timeout, connection error, or non-2xx) increments the counter. Reaching `--failure-threshold` (default 3) moves the URL to `DOWN`. One successful check (final status 2xx after redirects) resets the counter and moves the URL to `UP`. Transitions, including the first leave from `UNKNOWN`, are notifications. Further failures while already `DOWN`, and further successes while already `UP`, do not emit another state line.

4. **What a line contains**: Terminal and log receive the same lines and nothing else. Two kinds:
   - State change, only when `UNKNOWN`/`UP`/`DOWN` actually changes.
   - `UPTIME`, one line per URL at the end of every cycle, using the in-memory window. A quiet URL still gets this line, so the percentage is visible without an outage.
   - No per-check line.

   DOWN reason text is `HTTP <status>`, `timeout`, or `connection error`. UP parenthetical is `HTTP <status>, <ms>ms`. Uptime is one decimal percent: successes ÷ samples in the window. A sample is one finished check. Cancelled work on shutdown is not a sample.

5. **Where the percentage comes from**: Samples live in memory (timestamp, URL, success or failure). Samples older than one hour are dropped. The log is not parsed to recompute the percentage. This revises the earlier note that the percentage would be derived by reading the log: the log only contains state and uptime lines, which is what was chosen for output. Restarting the process starts the window over. A run shorter than one hour uses every sample collected so far.

6. **History file**: Created when the process starts, before the first cycle. Name `url-monitor-YYYYMMDDTHHMMSSZ.log` in the working directory, UTC timestamp. Append-only for the rest of the run. The path is not a CLI flag.

7. **CLI parameters**:

   | Parameter | Default | Meaning |
   |---|---|---|
   | URL arguments | required, one or more | Pages to check |
   | `--interval` | 20 seconds | Time from the start of one cycle to the start of the next |
   | `--timeout` | 10 seconds | Per-request timeout |
   | `--failure-threshold` | 3 | Consecutive failures before DOWN |
   | `--help` | | Lists and explains the parameters and the log name |

   Invalid arguments or no URLs: argparse error on stderr, non-zero exit, no log file. Ctrl-C closes the log and exits 0.

8. **Streams**: Report lines go to stdout and the log. Usage errors go to stderr. A failed HTTP check is a report line, not an stderr error.

9. **Dependencies and layout**: `pyproject.toml` with a `url-monitor` console script, package under `src/`, Python 3.11+. Runtime dependency `httpx`. Dev dependency `pytest`.

## What We're NOT Doing

- A web dashboard, HTML report, or browser UI.
- SQLite or any database, and any second history file.
- Reading older `url-monitor-*.log` files.
- Email, Slack, webhooks, or any notifier besides stdout and the run log.
- A config file, per-URL intervals, per-URL timeouts, or per-URL thresholds.
- A `--log-file` flag, a `--verbose` per-check mode, or a line for every check.
- Custom headers, request bodies, TLS overrides, or matching response body text.
- Installing a system service, or retrying a URL inside a cycle beyond the single attempt.
- Treating monitor downtime (the process was not running) as failed checks.

## Open Risks

- **Uptime every cycle is chatty.** Confirmed. With `--interval 20`, each URL prints an `UPTIME` line every 20 seconds even while healthy.
- **The log cannot rebuild the percentage.** Confirmed. Samples stay in memory. After exit, the file shows transitions and the figures that were printed. A later run will not load it.
- **Slow checks shrink the gap between cycles.** A cycle that exceeds `--interval` delays the next start and can bunch timestamps. It will not run two cycles at once.
- **Redirects define success.** The status that counts is the final response. A redirect chain that ends in 200 is UP. Response time includes the whole chain.
- **First hour is a partial window.** The printed percentage still says `last 1h`, with the actual sample count in parentheses, so a 2-minute run cannot look like a full hour of data.
