import asyncio
import re
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import httpx
import pytest

from url_monitor import cli
from url_monitor.checker import check_urls
from url_monitor.config import Config
from url_monitor.cycle import run_cycle
from url_monitor.window import SampleWindow

NOW = datetime(2026, 11, 8, 17, 0, 0, tzinfo=timezone.utc)
OK_URL = "https://example.test/ok"
UP_LINE = re.compile(
    r"\[2026-11-08T17:00:00Z\] UP     https://example\.test/ok  \(HTTP 200, \d+ms\)"
)
UPTIME_OK = (
    "[2026-11-08T17:00:00Z] UPTIME https://example.test/ok  100.0%  (1/1 checks, last 1h)"
)
UPTIME_FAIL = (
    "[2026-11-08T17:00:00Z] UPTIME https://example.test/ok  0.0%  (0/1 checks, last 1h)"
)


def client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def config_for(*urls: str) -> Config:
    return Config(urls=urls, log_path=Path("unused.log"))


def run(handler, *urls: str) -> str:
    buffer = StringIO()

    async def once() -> None:
        async with client_with(handler) as client:
            await run_cycle(config_for(*urls), client, SampleWindow(), {}, buffer, NOW)

    asyncio.run(once())
    return buffer.getvalue()


def test_200_prints_up_and_uptime(capsys: pytest.CaptureFixture[str]) -> None:
    text = run(lambda request: httpx.Response(200), OK_URL)
    lines = text.splitlines()
    assert len(lines) == 2
    assert UP_LINE.fullmatch(lines[0])
    assert lines[1] == UPTIME_OK
    assert capsys.readouterr().out == text


def test_503_prints_only_uptime() -> None:
    text = run(lambda request: httpx.Response(503), OK_URL)
    assert text.splitlines() == [UPTIME_FAIL]


def test_timeout_is_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    async def once():
        async with client_with(handler) as client:
            return await check_urls((OK_URL,), 10, client, NOW)

    result = asyncio.run(once())[0]
    assert result.ok is False
    assert result.status_code is None
    assert result.error == "timeout"


def test_connection_error_is_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async def once():
        async with client_with(handler) as client:
            return await check_urls((OK_URL,), 10, client, NOW)

    result = asyncio.run(once())[0]
    assert result.ok is False
    assert result.error == "connection error"


def test_redirect_final_status_decides() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(301, headers={"Location": "https://example.test/final"})
        return httpx.Response(200)

    async def once():
        async with client_with(handler) as client:
            return await check_urls(("https://example.test/start",), 10, client, NOW)

    result = asyncio.run(once())[0]
    assert result.ok is True
    assert result.status_code == 200


def test_results_keep_input_order() -> None:
    urls = (
        "https://example.test/a",
        "https://example.test/b",
        "https://example.test/c",
    )

    async def once():
        async with client_with(lambda request: httpx.Response(200)) as client:
            return await check_urls(urls, 10, client, NOW)

    results = asyncio.run(once())
    assert [result.url for result in results] == list(urls)


def test_help_lists_flags_and_log_name(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["--help"])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    assert "--interval" in output
    assert "--timeout" in output
    assert "--failure-threshold" in output
    assert "url-monitor-YYYYMMDDTHHMMSSZ.log" in output


def test_no_url_exits_2_and_creates_no_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as caught:
        cli.main([])
    assert caught.value.code == 2
    assert list(tmp_path.glob("url-monitor-*.log")) == []


def test_main_log_matches_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_make_client", lambda: client_with(lambda request: httpx.Response(200)))
    assert cli.main(["https://example.test/ok"]) == 0
    logs = list(tmp_path.glob("url-monitor-*.log"))
    assert len(logs) == 1
    assert re.fullmatch(r"url-monitor-\d{8}T\d{6}Z\.log", logs[0].name)
    assert logs[0].read_text(encoding="utf-8") == capsys.readouterr().out
