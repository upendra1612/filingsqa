"""Offline tests: no network calls, so they run in CI and without an SEC User-Agent."""

from __future__ import annotations

import pytest

from filingsqa.edgar import (
    EdgarClient,
    EdgarError,
    RateLimiter,
    archive_url,
    columns_to_rows,
    iter_filings,
    pad_cik,
    select_annual_reports,
)

UA = "Test User test@example.com"


class FakeResponse:
    def __init__(self, status: int, payload=None, headers=None, content: bytes = b""):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.content = content

    def json(self):
        return self._payload


class FakeSession:
    """Returns queued responses per URL and records every call."""

    def __init__(self, routes: dict[str, list[FakeResponse]]):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        queue = self.routes.get(url)
        if not queue:
            raise AssertionError(f"unexpected request: {url}")
        return queue.pop(0) if len(queue) > 1 else queue[0]


def make_client(tmp_path, routes, **kwargs) -> EdgarClient:
    return EdgarClient(
        user_agent=UA,
        cache_dir=tmp_path / "cache",
        session=FakeSession(routes),
        sleep=lambda s: None,
        **kwargs,
    )


def test_pad_cik_and_archive_url():
    assert pad_cik(320193) == "0000320193"
    assert (
        archive_url(320193, "0000320193-24-000123", "aapl-20240928.htm")
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    )


@pytest.mark.parametrize("bad", ["", "no-email-here", "Your Name your.email@example.com"])
def test_user_agent_is_required(tmp_path, monkeypatch, bad):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(EdgarError):
        EdgarClient(user_agent=bad, cache_dir=tmp_path)


def test_user_agent_header_is_sent(tmp_path):
    client = make_client(tmp_path, {})
    assert client.session.headers["User-Agent"] == UA


def test_rate_limiter_spaces_calls():
    now = [0.0]
    slept: list[float] = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    limiter = RateLimiter(rps=8, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        limiter.wait()
    assert slept == pytest.approx([0.125, 0.125])


def test_rate_limiter_rejects_rates_above_sec_ceiling():
    with pytest.raises(ValueError):
        RateLimiter(rps=11)


def test_retries_on_429_then_succeeds(tmp_path):
    url = "https://example.test/x"
    client = make_client(
        tmp_path,
        {url: [FakeResponse(429, headers={"Retry-After": "1"}), FakeResponse(200, {"ok": True})]},
    )
    assert client.get_json(url) == {"ok": True}
    assert client.session.calls == [url, url]


def test_gives_up_after_max_retries(tmp_path):
    url = "https://example.test/down"
    client = make_client(tmp_path, {url: [FakeResponse(503)]}, max_retries=2)
    with pytest.raises(EdgarError):
        client.get_json(url)
    assert len(client.session.calls) == 3


def test_does_not_retry_on_404(tmp_path):
    url = "https://example.test/missing"
    client = make_client(tmp_path, {url: [FakeResponse(404)]})
    with pytest.raises(EdgarError):
        client.get_json(url)
    assert len(client.session.calls) == 1


def test_json_cache_avoids_second_request(tmp_path):
    url = "https://example.test/data"
    client = make_client(tmp_path, {url: [FakeResponse(200, {"n": 1})]})
    assert client.get_json(url, cache_name="data.json") == {"n": 1}
    assert client.get_json(url, cache_name="data.json") == {"n": 1}
    assert len(client.session.calls) == 1


def test_columns_to_rows():
    rows = list(
        columns_to_rows({"form": ["10-K", "8-K"], "filingDate": ["2025-02-01", "2025-01-15"]})
    )
    assert rows == [
        {"form": "10-K", "filingDate": "2025-02-01"},
        {"form": "8-K", "filingDate": "2025-01-15"},
    ]


def _cols(rows):
    return {k: [r[k] for r in rows] for k in rows[0]}


def test_select_annual_reports_excludes_amendments_and_stops_early(tmp_path):
    recent = [
        {
            "form": "10-K/A",
            "filingDate": "2026-03-01",
            "accessionNumber": "a0",
            "primaryDocument": "x.htm",
        },
        {
            "form": "10-K",
            "filingDate": "2026-02-10",
            "accessionNumber": "a1",
            "primaryDocument": "k26.htm",
        },
        {
            "form": "8-K",
            "filingDate": "2025-10-01",
            "accessionNumber": "a2",
            "primaryDocument": "e.htm",
        },
    ]
    older = [
        {
            "form": "10-K",
            "filingDate": "2025-02-12",
            "accessionNumber": "a3",
            "primaryDocument": "k25.htm",
        },
    ]
    subs_url = "https://data.sec.gov/submissions/CIK0000000001.json"
    page_url = "https://data.sec.gov/submissions/CIK0000000001-submissions-001.json"
    client = make_client(
        tmp_path,
        {
            subs_url: [
                FakeResponse(
                    200,
                    {
                        "filings": {
                            "recent": _cols(recent),
                            "files": [{"name": "CIK0000000001-submissions-001.json"}],
                        }
                    },
                )
            ],
            page_url: [FakeResponse(200, _cols(older))],
        },
    )
    picked = select_annual_reports(iter_filings(client, 1), limit=2)
    assert [f["accessionNumber"] for f in picked] == ["a1", "a3"]

    # With limit=1 the older page is never requested.
    client2 = make_client(tmp_path / "c2", {subs_url: client.session.routes[subs_url]})
    select_annual_reports(iter_filings(client2, 1), limit=1)
    assert page_url not in client2.session.calls
