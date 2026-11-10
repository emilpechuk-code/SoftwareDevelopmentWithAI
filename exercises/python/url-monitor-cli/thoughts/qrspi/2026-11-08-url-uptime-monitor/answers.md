# Answers

1. **Product surface**: Python CLI. Each run prints reports to the terminal and writes the same output to a new log file. The file name includes a timestamp so each run is unique and does not overwrite a previous log. No web dashboard.
   - Log name: `url-monitor-YYYYMMDDTHHMMSSZ.log` in the working directory (example: `url-monitor-20261108T171300Z.log`).

2. **History storage**: No SQLite database and no second history file. Older run logs are not read. The per-run log stores only the lines that are printed (answer 4). Raw per-check samples used to compute the 1-hour percentage are kept in memory for the current run and are not written as their own lines.

3. **Outage rule**: Default. A URL is DOWN after 3 consecutive failures (`--failure-threshold`, default 3). A failure is a timeout, a connection error, or any non-2xx HTTP status. One success returns the URL to UP.

4. **Notifications**: Terminal and the per-run log file only. The same output is written to both. No email, Slack, or webhook. What gets written is state changes and a 1-hour uptime figure only. Per-check lines are not written.

5. **Configuration**: Default, plus a help command. URLs are positional CLI arguments. `--interval`, `--timeout`, and `--failure-threshold` apply to every URL. No config file. `url-monitor --help` lists every parameter and explains what it does, including that each run creates `url-monitor-YYYYMMDDTHHMMSSZ.log` in the working directory.
   - Parameters: one or more URL arguments, `--interval` (default 20 seconds), `--timeout` (default 10 seconds), `--failure-threshold` (default 3), `--help`.

6. **Uptime window**: Rolling 1 hour, using only samples from the current run. Uptime for a URL is successful checks divided by all checks recorded for that URL in the last hour. Checks the monitor did not run are omitted. Samples older than 1 hour are dropped from the in-memory window. If the run is shorter than 1 hour, every sample in this run counts. Older log files are not read.

7. **Check execution**: Default. `httpx` async. URLs in one cycle are checked concurrently. Redirects are followed. Response time is the total elapsed time of the request. Per-request timeout comes from `--timeout` (default 10 seconds).
