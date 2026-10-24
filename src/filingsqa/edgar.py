"""Minimal SEC EDGAR client.

Follows the SEC fair-access policy (https://www.sec.gov/os/accessing-edgar-data):
a declared User-Agent with contact details, and fewer than 10 requests per second.
Adds retries with backoff for 429/5xx responses and a local JSON cache so
re-runs do not hit the SEC again.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import requests

SEC_MAX_RPS = 10  # SEC ceiling; treat as a limit, not a target
DEFAULT_RPS = 8

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"

RETRY_STATUSES = {429, 500, 502, 503, 504}
ONE_DAY_S = 24 * 60 * 60


class EdgarError(RuntimeError):
    """Raised for configuration errors and failed requests."""


def pad_cik(cik: int | str) -> str:
    """CIKs are zero-padded to 10 digits on data.sec.gov."""
    return f"{int(cik):010d}"


def archive_url(cik: int | str, accession: str, document: str) -> str:
    """URL of a document inside a filing, e.g. the 10-K's primary HTML file."""
    return ARCHIVE_URL.format(cik=int(cik), acc_nodash=accession.replace("-", ""), doc=document)


class RateLimiter:
    """Spaces calls at least 1/rps seconds apart; safe across threads."""

    def __init__(
        self,
        rps: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not 0 < rps <= SEC_MAX_RPS:
            raise ValueError(f"rps must be in (0, {SEC_MAX_RPS}]")
        self.min_interval = 1.0 / rps
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if now < self._next_allowed:
                self._sleep(self._next_allowed - now)
                now = self._next_allowed
            self._next_allowed = now + self.min_interval


class EdgarClient:
    def __init__(
        self,
        user_agent: str | None = None,
        cache_dir: str | Path = "data/cache",
        rps: float = DEFAULT_RPS,
        session: requests.Session | None = None,
        max_retries: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        ua = (user_agent or os.environ.get("SEC_USER_AGENT", "")).strip()
        if not ua or "@" not in ua or ua.startswith("Your Name"):
            raise EdgarError(
                'Set SEC_USER_AGENT to "First Last your.email@example.com" '
                "(required by the SEC fair-access policy). See .env.example."
            )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self._sleep = sleep
        self.limiter = RateLimiter(rps, sleep=sleep)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
        self.request_count = 0

    # ---- low-level -------------------------------------------------------

    def _get(self, url: str) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            self.request_count += 1
            retry_after: float | None = None
            try:
                resp = self.session.get(url, timeout=60)
            except requests.RequestException as exc:  # network blip: retry
                last_error = exc
            else:
                if resp.status_code == 200:
                    return resp
                if resp.status_code not in RETRY_STATUSES:
                    raise EdgarError(f"GET {url} returned {resp.status_code}")
                last_error = EdgarError(f"GET {url} returned {resp.status_code}")
                header = resp.headers.get("Retry-After")
                if header and header.isdigit():
                    retry_after = float(header)
            if attempt == self.max_retries:
                break
            self._sleep(min(retry_after if retry_after is not None else 2.0**attempt, 60.0))
        raise EdgarError(f"GET {url} failed after {self.max_retries + 1} attempts") from last_error

    def get_bytes(self, url: str) -> bytes:
        return self._get(url).content

    def get_json(
        self, url: str, cache_name: str | None = None, max_age_s: float | None = None
    ) -> Any:
        """Fetch JSON, reusing a cached copy if it exists and is fresh enough."""
        cache_path = self.cache_dir / cache_name if cache_name else None
        if cache_path and cache_path.is_file():
            age = time.time() - cache_path.stat().st_mtime
            if max_age_s is None or age < max_age_s:
                return json.loads(cache_path.read_text(encoding="utf-8"))
        data = self._get(url).json()
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data), encoding="utf-8")
        return data

    # ---- EDGAR endpoints -------------------------------------------------

    def ticker_map(self) -> dict[str, dict[str, Any]]:
        """Upper-case ticker -> {"cik": int, "title": str}."""
        raw = self.get_json(TICKERS_URL, "company_tickers.json", max_age_s=ONE_DAY_S)
        return {
            row["ticker"].upper(): {"cik": int(row["cik_str"]), "title": row["title"]}
            for row in raw.values()
        }

    def submissions(self, cik: int | str) -> dict[str, Any]:
        cik10 = pad_cik(cik)
        return self.get_json(
            SUBMISSIONS_URL.format(cik10=cik10), f"submissions/CIK{cik10}.json", ONE_DAY_S
        )

    def submissions_page(self, name: str) -> dict[str, Any]:
        """Older filings live in extra pages listed under filings.files."""
        return self.get_json(SUBMISSIONS_PAGE_URL.format(name=name), f"submissions/{name}")

    def company_facts(self, cik: int | str) -> dict[str, Any]:
        cik10 = pad_cik(cik)
        return self.get_json(
            COMPANYFACTS_URL.format(cik10=cik10), f"companyfacts/CIK{cik10}.json", ONE_DAY_S
        )


# ---- filing selection (pure functions, easy to test) ---------------------


def columns_to_rows(columns: dict[str, list[Any]]) -> Iterator[dict[str, Any]]:
    """EDGAR returns filings as parallel arrays; turn them into one dict per filing."""
    keys = list(columns)
    if not keys:
        return
    for i in range(len(columns[keys[0]])):
        yield {k: columns[k][i] for k in keys}


def iter_filings(client: EdgarClient, cik: int | str) -> Iterator[dict[str, Any]]:
    """Every filing for a company: the recent block first, then any older pages."""
    subs = client.submissions(cik)
    filings = subs.get("filings", {})
    yield from columns_to_rows(filings.get("recent", {}))
    for page in filings.get("files", []):
        yield from columns_to_rows(client.submissions_page(page["name"]))


def select_annual_reports(
    filings: Iterator[dict[str, Any]], form: str = "10-K", limit: int = 2
) -> list[dict[str, Any]]:
    """Latest `limit` original annual reports (amendments such as 10-K/A are excluded).

    EDGAR lists filings newest first, so we stop as soon as we have enough. That
    matters for large banks: they file thousands of prospectus supplements, and
    their 10-Ks can sit in older pages that we then never need to download.
    """
    chosen: list[dict[str, Any]] = []
    for f in filings:
        if f.get("form") == form and f.get("primaryDocument"):
            chosen.append(f)
            if len(chosen) >= limit:
                break
    chosen.sort(key=lambda f: f.get("filingDate", ""), reverse=True)
    return chosen
