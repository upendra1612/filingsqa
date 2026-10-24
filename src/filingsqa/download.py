"""Download recent 10-K filings and XBRL company facts for a list of tickers.

Usage:
    filingsqa-download --companies config/companies.txt --per-company 2

Writes:
    data/raw/<TICKER>/<accession>/<primary document>   the 10-K HTML
    data/raw/<TICKER>/companyfacts.json                 XBRL facts (ground truth)
    data/manifest.jsonl                                 one line per filing
Files that already exist are not downloaded again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .edgar import EdgarClient, EdgarError, archive_url, iter_filings, select_annual_reports
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


def download_company(
    client: EdgarClient, ticker: str, info: dict, out_dir: Path, per_company: int
) -> list[dict]:
    cik = info["cik"]
    company_dir = out_dir / ticker
    company_dir.mkdir(parents=True, exist_ok=True)

    facts_path = company_dir / "companyfacts.json"
    if not facts_path.exists():
        facts_path.write_text(json.dumps(client.company_facts(cik)), encoding="utf-8")

    records = []
    for filing in select_annual_reports(iter_filings(client, cik), limit=per_company):
        accession = filing["accessionNumber"]
        doc = filing["primaryDocument"]
        url = archive_url(cik, accession, doc)
        local = company_dir / accession / Path(doc).name
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(client.get_bytes(url))
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
                "url": url,
                "local_path": local.as_posix(),
                "bytes": local.stat().st_size,
                "sha256": sha256_file(local),
            }
        )
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--companies", default="config/companies.txt")
    parser.add_argument("--per-company", type=int, default=2, help="10-Ks per company")
    parser.add_argument("--out", default="data/raw")
    parser.add_argument("--manifest", default="data/manifest.jsonl")
    args = parser.parse_args(argv)

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
            records = download_company(client, ticker, info, out_dir, args.per_company)
        except EdgarError as exc:
            print(f"[fail] {ticker}: {exc}", file=sys.stderr)
            failures.append(ticker)
            continue
        manifest.extend(records)
        found = ", ".join(r["report_date"] or "?" for r in records) or "none found"
        print(f"[ok]   {ticker}: {len(records)} 10-K(s), periods {found}")

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
