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
python scripts/build_curated.py
python scripts/spot_check.py --all --out evals/results/full_check_xbrl.json
```

## How the XBRL questions are built

For each downloaded 10-K, `filingsqa-xbrl-questions` looks up eight headline metrics
(revenue, net income, diluted EPS, operating cash flow, total assets, total
liabilities, stockholders' equity, cash). A value is used only if it was reported
**in that same filing** (matching accession number) **for that filing's fiscal year
end**, and annual metrics must cover 330–380 days. Conflicting values are skipped,
not guessed. Each question records the exact `us-gaap` concept it came from.

Known limits, documented rather than hidden:

- Revenue was found for all 50 filings, but banks label it differently from our
  question wording (e.g. "Total revenue, net of interest expense"); see the spot-check.
- Cash and cash equivalents is missing for 13 banks, card issuers and insurers, which
  tag cash differently; total liabilities is missing for AMZN, KO, NKE and WMT, whose
  balance sheets show no "Total liabilities" line. Skipping these is correct.
- **WFC, USB and PGR** put their financial statements in exhibits (PGR: Exhibit 13), not
  in the primary 10-K document we download. Their 42 XBRL questions are unanswerable from
  the current corpus until those exhibits are ingested.
- XBRL values are in full units (e.g. 1,234,000,000), while 10-K tables usually
  say "in millions". Answer scoring must normalize scale.
- Some filers tag only the broader concept for a line. Net income falls back to
  `ProfitLoss` and equity to `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`
  (both include noncontrolling interests) only when the standard tag is absent for
  that filing and period; this applies to PNC and JNJ in the current corpus.
- XBRL `companyfacts` excludes dimensional (segment-level) facts, so segment
  questions come from the curated set.

## Verification

- `python scripts/spot_check.py --all` checks every XBRL question against the figure
  displayed in the 10-K. Latest run: 324/366 match, 0 wrong values, 42 not found (all
  WFC, USB, PGR). Report: `evals/results/spot_check_xbrl.md`.
- `python scripts/build_curated.py` rebuilds `evals/golden/curated.jsonl` and fails if any
  quote, figure or absence check does not hold. The curated questions were drafted with
  AI assistance and verified by these checks, not hand-labeled.
