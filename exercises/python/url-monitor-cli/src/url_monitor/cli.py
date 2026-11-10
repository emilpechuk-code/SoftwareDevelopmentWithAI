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
        "--interval",
        type=_positive_float,
        default=20.0,
        metavar="SECONDS",
        help="seconds from the start of one check cycle to the next (default: 20)",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=10.0,
        metavar="SECONDS",
        help="per-request timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--failure-threshold",
        type=_positive_int,
        default=3,
        metavar="N",
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
