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
