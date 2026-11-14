import json

from filingsqa.download import download_company, read_tickers
from filingsqa.edgar import EdgarClient, parse_filing_index

from .test_edgar import UA, FakeResponse, FakeSession

# Shaped like a real EDGAR filing index page (Wells Fargo FY2024 10-K, trimmed).
INDEX_HTML = """<html><body>
<table class="tableFile" summary="Document Format Files">
<tr><th scope="col">Seq</th><th scope="col">Description</th><th scope="col">Document</th>
<th scope="col">Type</th><th scope="col">Size</th></tr>
<tr><td scope="row">1</td><td scope="row">FORM 10-K</td>
<td scope="row"><a href="/ix?doc=/Archives/edgar/data/1/000000000126000010/tst-20251231.htm">
tst-20251231.htm</a> &nbsp;&nbsp;<span>iXBRL</span></td><td scope="row">10-K</td>
<td scope="row">1552078</td></tr>
<tr><td scope="row">7</td><td scope="row">EX-13</td>
<td scope="row"><a href="/ix?doc=/Archives/edgar/data/1/000000000126000010/tst-20251231_d2.htm">
tst-20251231_d2.htm</a> <span>iXBRL</span></td><td scope="row">EX-13</td>
<td scope="row">10903343</td></tr>
<tr><td scope="row">21</td><td scope="row">EX-21</td>
<td scope="row"><a href="/Archives/edgar/data/1/000000000126000010/tst-ex21.htm">
tst-ex21.htm</a></td>
<td scope="row">EX-21</td><td scope="row">10902</td></tr>
</table>
<table class="tableFile" summary="Data Files">
<tr><th scope="col">Seq</th><th scope="col">Description</th><th scope="col">Document</th>
<th scope="col">Type</th><th scope="col">Size</th></tr>
<tr><td scope="row">19</td><td scope="row">XBRL TAXONOMY EXTENSION SCHEMA DOCUMENT</td>
<td scope="row"><a href="/Archives/edgar/data/1/000000000126000010/tst-20251231.xsd">
tst-20251231.xsd</a></td>
<td scope="row">EX-101.SCH</td><td scope="row">268558</td></tr>
</table></body></html>"""


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
    base = "https://www.sec.gov/Archives/edgar/data/1/000000000126000010/"
    doc_url = base + "tst-20251231.htm"
    routes = {
        base + "0000000001-26-000010-index.html": [FakeResponse(200, content=INDEX_HTML.encode())],
        base + "tst-20251231_d2.htm": [FakeResponse(200, content=b"<html>EX-13</html>")],
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
    # EX-13 downloaded, EX-21 and data files ignored
    assert [e["type"] for e in rec["exhibits"]] == ["EX-13"]
    assert rec["documents"] == [
        rec["local_path"],
        (tmp_path / "raw/TST/0000000001-26-000010/tst-20251231_d2.htm").as_posix(),
    ]

    calls_before = len(session.calls)
    download_company(client, "TST", info, tmp_path / "raw", per_company=2)
    assert len(session.calls) == calls_before  # everything came from disk or cache


def test_parse_filing_index_reads_types_and_unwraps_ixbrl_links():
    docs = parse_filing_index(INDEX_HTML)
    assert [(d["type"], d["document"]) for d in docs] == [
        ("10-K", "tst-20251231.htm"),
        ("EX-13", "tst-20251231_d2.htm"),
        ("EX-21", "tst-ex21.htm"),
        ("EX-101.SCH", "tst-20251231.xsd"),
    ]
    assert docs[1]["path"] == "/Archives/edgar/data/1/000000000126000010/tst-20251231_d2.htm"


def test_no_exhibits_requested_means_no_index_request(tmp_path):
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
    base = "https://www.sec.gov/Archives/edgar/data/1/000000000126000010/"
    session = FakeSession(
        {
            "https://data.sec.gov/submissions/CIK0000000001.json": [FakeResponse(200, subs)],
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json": [
                FakeResponse(200, {"facts": {}})
            ],
            base + "tst-20251231.htm": [FakeResponse(200, content=b"x")],
        }
    )
    client = EdgarClient(
        user_agent=UA, cache_dir=tmp_path / "cache", session=session, sleep=lambda s: None
    )
    [rec] = download_company(
        client, "TST", {"cik": 1, "title": "T"}, tmp_path / "raw", 1, exhibit_types=()
    )
    assert rec["exhibits"] == [] and rec["documents"] == [rec["local_path"]]
