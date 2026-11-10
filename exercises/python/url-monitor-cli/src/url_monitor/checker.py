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
    results = await asyncio.gather(*(_check_one(client, url, timeout, now) for url in urls))
    return list(results)
