# XBRL question spot-check

Latest run: 2026-11-14.

Method: `scripts/spot_check.py` finds each question's figure in the filing's inline XBRL, reads the row label and the number as displayed, applies the stated scale, and compares it with the expected answer. It searches every document in the filing (primary 10-K and Exhibit 13) and reads period definitions from all of them. This confirms each answer is visible in the documents the retriever searches; it does not audit the company's own tagging.

## Results

- **All 366 questions** (`--all`): **366/366 match**, 0 wrong values.
- **Sample of 20** (seed 7): 20/20 match.
- History: 2026-10-24 was 324/366; the 42 misses (WFC, USB, PGR) had financial statements in Exhibit 13, which was not downloaded. Fixed by ingesting EX-13.

## Sample of 20

| Question id | Row label in the filing | Displayed | Scale | Found in | Status |
| --- | --- | --- | --- | --- | --- |
| `xbrl-MS-2025-12-31-revenue` | Net revenues | 70,645 | millions | ms-20251231.htm | match |
| `xbrl-BAC-2025-12-31-revenue` | Total revenue, net of interest expense | 113,097 | millions | bac-20251231.htm | match |
| `xbrl-C-2025-12-31-revenue` | Total revenues, net of interest expense(1) | 85,225 | millions | c-20251231.htm | match |
| `xbrl-PNC-2024-12-31-revenue` | Total revenue | 21,555 | millions | pnc-20241231.htm | match |
| `xbrl-NKE-2026-05-31-total_assets` | TOTAL ASSETS | 38,410 | millions | nke-20260531.htm | match |
| `xbrl-PRU-2025-12-31-net_income` | NET INCOME (LOSS) ATTRIBUTABLE TO PRUDENTIAL FINANCIAL, INC. | 3,576 | millions | pru-20251231.htm | match |
| `xbrl-MS-2025-12-31-net_income` | Net income applicable to Morgan Stanley | 16,861 | millions | ms-20251231.htm | match |
| `xbrl-CB-2025-12-31-eps_diluted` | Diluted earnings per share attributable to Chubb | 25.68 | units | cb-20251231.htm | match |
| `xbrl-COF-2025-12-31-revenue` | Total net revenue (loss)(2) | 53,434 | millions | cof-20251231.htm | match |
| `xbrl-JNJ-2025-12-28-operating_cash_flow` | Net cash flows from operating activities | 24,530 | millions | jnj-20251228.htm | match |
| `xbrl-GS-2024-12-31-revenue` | Total net revenues | 53,512 | millions | gs-20241231.htm | match |
| `xbrl-AAPL-2025-09-27-cash` | Cash and cash equivalents | 35,934 | millions | aapl-20250927.htm | match |
| `xbrl-PGR-2025-12-31-stockholders_equity` | Total shareholders’ equity | 30,323 | millions | pgr-20251231_d2.htm | match |
| `xbrl-ALL-2025-12-31-eps_diluted` | Net income (loss) applicable to common shareholders per common share - Diluted | 38.06 | units | all-20251231.htm | match |
| `xbrl-WFC-2024-12-31-revenue` | Total revenue | 82,296 | millions | wfc-20241231_d2.htm | match |
| `xbrl-JPM-2025-12-31-eps_diluted` | Diluted earnings per share | 20.02 | units | jpm-20251231.htm | match |
| `xbrl-BAC-2025-12-31-net_income` | Net income | 30,509 | millions | bac-20251231.htm | match |
| `xbrl-PNC-2024-12-31-stockholders_equity` | Total shareholders’ equity | 54,425 | millions | pnc-20241231.htm | match |
| `xbrl-MET-2024-12-31-eps_diluted` | Diluted | 5.94 | units | met-20241231.htm | match |
| `xbrl-KO-2024-12-31-net_income` | Net Income Attributable to Shareowners of The Coca-Cola Company | 10,631 | millions | ko-20241231.htm | match |

## Findings

1. **Exhibit 13 holds the statements for some filers.** WFC, USB and PGR file their financial statements as Exhibit 13 (annual report to shareholders). Their figures live there, while the period definitions (iXBRL contexts) stay in the primary 10-K, so both must be read together.
2. **Bank revenue wording differs from our question.** We ask for "total revenue"; filings say "Net revenues" (MS), "Total revenue, net of interest expense" (BAC), "Total net revenue" (COF) and similar. Values match; the wording gap is a retrieval risk to measure.
3. **Net income is reported as the parent's share** where noncontrolling interests exist, consistent with the `NetIncomeLoss` tag.
4. **Scale:** displayed figures are in millions except per-share values, so answer scoring normalizes scale.
5. **Corpus drift:** the corpus keeps each company's latest two 10-Ks, so new filings change it (Apple FY2026 replaced FY2024 on 2026-11-03). Results record the git commit and question set they ran on.
