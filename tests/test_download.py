import json

from filingsqa.download import download_company, read_tickers
from filingsqa.edgar import EdgarClient

from .test_edgar import UA, FakeResponse, FakeSession


def test_read_tickers_ignores_comments_and_duplicates(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("# banks\njpm\nBAC  # inline comment\n\nJPM\n")
    assert read_tickers(p) == ["JPM", "BAC"]


def test_download_company_writes_files_and_is_idempotent(tmp_path):
    subs = {
        "filings": {
            "recent": {
                "form": ["10-K"],
                "filingDate": ["2026-02-10"],
                "reportDate": ["2025-12-31"],
                "accessionNumber": ["0000000001-26-000010"],
                "primaryDocument": ["tst-20251231.htm"],
            },
            "files": [],
        }
    }
    doc_url = "https://www.sec.gov/Archives/edgar/data/1/000000000126000010/tst-20251231.htm"
    routes = {
        "https://data.sec.gov/submissions/CIK0000000001.json": [FakeResponse(200, subs)],
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json": [
            FakeResponse(200, {"facts": {}})
        ],
        doc_url: [FakeResponse(200, content=b"<html>10-K</html>")],
    }
    session = FakeSession(routes)
    client = EdgarClient(
        user_agent=UA, cache_dir=tmp_path / "cache", session=session, sleep=lambda s: None
    )
    info = {"cik": 1, "title": "Test Corp"}

    records = download_company(client, "TST", info, tmp_path / "raw", per_company=2)
    assert len(records) == 1
    rec = records[0]
    assert rec["report_date"] == "2025-12-31"
    assert rec["url"] == doc_url
    assert (tmp_path / "raw/TST/0000000001-26-000010/tst-20251231.htm").read_bytes() == (
        b"<html>10-K</html>"
    )
    assert json.loads((tmp_path / "raw/TST/companyfacts.json").read_text()) == {"facts": {}}

    calls_before = len(session.calls)
    download_company(client, "TST", info, tmp_path / "raw", per_company=2)
    assert len(session.calls) == calls_before  # everything came from disk or cache
