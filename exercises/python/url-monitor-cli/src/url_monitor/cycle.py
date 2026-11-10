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
    for result in results:
        if result.ok:
            emit(format_up(result), log)
    for result in results:
        successes, total = window.uptime(result.url)
        emit(format_uptime(result.url, successes, total, now), log)
