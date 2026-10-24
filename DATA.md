# Data sources

No downloaded data is committed. Everything under `data/` is rebuilt by the scripts.

| Source | What it is | How it is used | Terms |
| --- | --- | --- | --- |
| [SEC EDGAR](https://www.sec.gov/edgar/sec-api-documentation) 10-K filings | Annual reports, primary HTML document | Retrieval corpus | Public; automated access must follow the [fair-access policy](https://www.sec.gov/os/accessing-edgar-data): declared User-Agent, under 10 requests/second |
| EDGAR XBRL `companyfacts` | Numbers each company tagged in its own filings | Ground truth for numeric eval questions | Same as above |
| [FinanceBench](https://github.com/patronus-ai/financebench) open set | 150 human-annotated questions with answers and evidence | External benchmark | Check the repository license before redistributing |

## Rebuild

```bash
filingsqa-download --companies config/companies.txt --per-company 2
filingsqa-xbrl-questions
```

## How the XBRL questions are built

For each downloaded 10-K, `filingsqa-xbrl-questions` looks up eight headline metrics
(revenue, net income, diluted EPS, operating cash flow, total assets, total
liabilities, stockholders' equity, cash). A value is used only if it was reported
**in that same filing** (matching accession number) **for that filing's fiscal year
end**, and annual metrics must cover 330–380 days. Conflicting values are skipped,
not guessed. Each question records the exact `us-gaap` concept it came from.

Known limits, documented rather than hidden:

- Banks and insurers often do not tag a single "revenue" line, so revenue
  coverage is lower for them. That is expected.
- XBRL values are in full units (e.g. 1,234,000,000), while 10-K tables usually
  say "in millions". Answer scoring must normalize scale.
- XBRL `companyfacts` excludes dimensional (segment-level) facts, so segment
  questions come from the hand-written set.
