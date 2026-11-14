"""Download recent 10-K filings and XBRL company facts for a list of tickers.

Usage:
    filingsqa-download --companies config/companies.txt --per-company 2

Writes:
    data/raw/<TICKER>/<accession>/<primary document>   the 10-K HTML
    data/raw/<TICKER>/<accession>/<exhibit>            EX-13 and other requested exhibits
    data/raw/<TICKER>/companyfacts.json                 XBRL facts (ground truth)
    data/manifest.jsonl                                 one line per filing
Files that already exist are not downloaded again.

Some companies (e.g. Wells Fargo, Progressive) put their financial statements in
Exhibit 13, the annual report to shareholders, instead of the primary 10-K document.
EX-13 is downloaded by default so those statements are in the corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .edgar import (
    EdgarClient,
    EdgarError,
    archive_url,
    iter_filings,
    select_annual_reports,
)
from .env import load_dotenv


def read_tickers(path: str | Path) -> list[str]:
    tickers = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            tickers.append(line.upper())
    return list(dict.fromkeys(tickers))  # de-duplicate, keep order


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


DEFAULT_EXHIBITS = ("EX-13",)
SEC_BASE = "https://www.sec.gov"


def _fetch(client: EdgarClient, url: str, local: Path) -> dict:
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(client.get_bytes(url))
    return {
        "url": url,
        "local_path": local.as_posix(),
        "bytes": local.stat().st_size,
        "sha256": sha256_file(local),
    }


def download_exhibits(
    client: EdgarClient,
    cik: int,
    accession: str,
    folder: Path,
    primary: str,
    exhibit_types: tuple[str, ...],
) -> list[dict]:
    wanted = {t.upper() for t in exhibit_types}
    out = []
    for doc in client.filing_index(cik, accession):
        if doc["type"].upper() not in wanted or doc["document"] == primary:
            continue
        url = (
            SEC_BASE + doc["path"]
            if doc["path"].startswith("/")
            else archive_url(cik, accession, doc["document"])
        )
        out.append(
            {
                "type": doc["type"],
                "document": doc["document"],
                **_fetch(client, url, folder / doc["document"]),
            }
        )
    return out


def download_company(
    client: EdgarClient,
    ticker: str,
    info: dict,
    out_dir: Path,
    per_company: int,
    exhibit_types: tuple[str, ...] = DEFAULT_EXHIBITS,
) -> list[dict]:
    cik = info["cik"]
    company_dir = out_dir / ticker
    company_dir.mkdir(parents=True, exist_ok=True)

    # Refreshed on every run (the client caches it for a day): when a company files a
    # new 10-K, its figures must be here too, or no questions are built for that year.
    facts_path = company_dir / "companyfacts.json"
    facts_path.write_text(json.dumps(client.company_facts(cik)), encoding="utf-8")

    records = []
    for filing in select_annual_reports(iter_filings(client, cik), limit=per_company):
        accession = filing["accessionNumber"]
        doc = filing["primaryDocument"]
        folder = company_dir / accession
        primary = _fetch(client, archive_url(cik, accession, doc), folder / Path(doc).name)
        exhibits = (
            download_exhibits(client, cik, accession, folder, Path(doc).name, exhibit_types)
            if exhibit_types
            else []
        )
        records.append(
            {
                "ticker": ticker,
                "cik": cik,
                "company": info["title"],
                "form": filing["form"],
                "accession": accession,
                "filing_date": filing.get("filingDate"),
                "report_date": filing.get("reportDate"),
                "primary_document": doc,
                **primary,
                "exhibits": exhibits,
                # every document that belongs to this filing, primary first
                "documents": [primary["local_path"]] + [e["local_path"] for e in exhibits],
            }
        )
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--companies", default="config/companies.txt")
    parser.add_argument("--per-company", type=int, default=2, help="10-Ks per company")
    parser.add_argument("--out", default="data/raw")
    parser.add_argument("--manifest", default="data/manifest.jsonl")
    parser.add_argument(
        "--exhibits",
        default=",".join(DEFAULT_EXHIBITS),
        help="comma-separated exhibit types to download (empty string for none)",
    )
    args = parser.parse_args(argv)
    exhibit_types = tuple(t.strip() for t in args.exhibits.split(",") if t.strip())

    load_dotenv()
    try:
        client = EdgarClient()
    except EdgarError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    tickers = read_tickers(args.companies)
    ticker_map = client.ticker_map()
    out_dir = Path(args.out)
    manifest: list[dict] = []
    failures: list[str] = []

    for ticker in tickers:
        info = ticker_map.get(ticker)
        if info is None:
            print(f"[skip] {ticker}: not found in SEC ticker list", file=sys.stderr)
            failures.append(ticker)
            continue
        try:
            records = download_company(
                client, ticker, info, out_dir, args.per_company, exhibit_types
            )
        except EdgarError as exc:
            print(f"[fail] {ticker}: {exc}", file=sys.stderr)
            failures.append(ticker)
            continue
        manifest.extend(records)
        found = ", ".join(r["report_date"] or "?" for r in records) or "none found"
        ex = sum(len(r["exhibits"]) for r in records)
        extra = (
            f", {ex} exhibit(s): "
            + ", ".join(sorted({e["type"] for r in records for e in r["exhibits"]}))
            if ex
            else ""
        )
        print(f"[ok]   {ticker}: {len(records)} 10-K(s), periods {found}{extra}")

    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as fh:
        for rec in manifest:
            fh.write(json.dumps(rec) + "\n")

    print(
        f"\n{len(manifest)} filings from {len(tickers) - len(failures)} companies "
        f"-> {manifest_path} ({client.request_count} SEC requests)"
    )
    if failures:
        print(f"failed or skipped: {', '.join(failures)}", file=sys.stderr)
    return 0 if manifest else 1


if __name__ == "__main__":
    raise SystemExit(main())
