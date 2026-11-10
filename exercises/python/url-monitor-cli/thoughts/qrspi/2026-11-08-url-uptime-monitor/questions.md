# Clarifying Questions

## Project Type
greenfield

## Goal Summary
Build an application that monitors one or more URLs, checks them on a configurable interval, and measures HTTP response time. It detects outages, tracks uptime percentage, stores historical results, sends notifications on failures, and presents dashboards or reports.

## Existing Constraints
No `.cursor/rules/`, `docs/rules/`, `src/`, or `pyproject.toml`. The exercise README (`README.md`) requires **Python 3.11+** and treats this as a greenfield project whose implementation waits until Step 6. That README still illustrates a terminal CLI (`url-monitor` with `--interval`, `--timeout`, `--failure-threshold`, `--log-file`). `goal.md` now also requires history, uptime percentage, failure notifications, and dashboards or reports. Those two descriptions disagree on product surface; the questions below force that choice instead of silently picking one.

An older question set lives at `thoughts/qrspi/2026-07-29-url-monitor-cli/` and answers a narrower CLI-only goal. It is not input for this run.

## Questions

1. **Product surface**: Should this be a long-running CLI, a local web app with a dashboard, or a CLI that also serves a local dashboard?
   - *Why it matters*: A CLI only needs a poll loop and stdout. A dashboard needs an HTTP server, stored query results, and a UI. Choosing both adds a second process boundary (checker vs. viewer).
   - *Default if unanswered*: A long-running Python CLI. Reports are printed or written to a file. No web server and no browser UI.

2. **History storage**: Where do check results live so uptime percentage and reports can be computed later — SQLite, an append-only log file, or memory for the life of the process only?
   - *Why it matters*: Uptime percentage and historical reports need durable, queryable samples. A log file is simple to append and hard to aggregate. SQLite supports windows and percentages. Memory-only history disappears on exit.
   - *Default if unanswered*: One SQLite file (for example `monitor.db`) with one row per check: URL, timestamp, success, status code, response time, error.

3. **Outage rule**: What counts as an outage — any single failed check, or N consecutive failures? Is a failure a timeout, a connection error, a non-2xx status, or only specific status codes?
   - *Why it matters*: This defines the per-URL state machine (UNKNOWN / UP / DOWN), when a notification fires, and whether uptime percentage counts every failed sample or only confirmed outages.
   - *Default if unanswered*: DOWN after 3 consecutive failures. A failure is a timeout, a connection error, or any non-2xx status. One success returns the URL to UP.

4. **Notifications**: Which channels fire on failure — stdout, a log file, email, Slack, webhook — and do they fire on every failed check or only when state changes (UP to DOWN, DOWN to UP)?
   - *Why it matters*: External channels add configuration, secrets, and retry behavior. Transition-only output stays quiet; per-check alerts flood the channel during an outage.
   - *Default if unanswered*: Stdout plus an optional log file, same line on both. Notify only on state transitions. No email, Slack, or webhook.

5. **Configuration**: Where do URLs and settings come from — CLI arguments, a config file, or both — and is there one global interval and timeout or per-URL overrides?
   - *Why it matters*: CLI-only flags stay flat and global. A config file implies a schema and usually per-URL timeout, expected status, and interval. The config layer is the public interface of the tool.
   - *Default if unanswered*: URLs as positional CLI arguments. `--interval`, `--timeout`, and `--failure-threshold` apply to every URL. No config file.

6. **Uptime window**: Over what period is uptime percentage calculated — since the process started, a rolling window (for example 24 hours), or calendar periods (day / week)?
   - *Why it matters*: "Since start" can be computed from in-memory counters. A rolling or calendar window requires querying stored samples and defining how missing checks (downtime of the monitor itself) are treated.
   - *Default if unanswered*: Rolling 24 hours, equal to successful checks divided by all recorded checks for that URL in the window. Checks the monitor did not run are omitted, not counted as downtime.

7. **Check execution**: Should checks use synchronous `httpx` one URL at a time, or async `httpx` with the URLs in a cycle checked concurrently? Is response time total time to headers and body, with redirects followed?
   - *Why it matters*: Concurrency changes the scheduler, cancellation on Ctrl-C, and how tests fake time and HTTP. Response-time definition is part of the stored history and any report.
   - *Default if unanswered*: `httpx` async, URLs in one cycle checked concurrently, follow redirects, response time is total elapsed time for the request, per-request timeout from `--timeout` (default 10 seconds).
