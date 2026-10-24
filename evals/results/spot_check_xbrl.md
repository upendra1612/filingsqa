# XBRL question spot-check (2026-10-24)

Method: `scripts/spot_check.py` finds each question's figure in the 10-K's inline XBRL, reads the row label and the number as displayed, applies the stated scale, and compares it with the expected answer. This confirms the answer is visible in the document the retriever will search. It does not audit the company's own tagging.

## Results

- **Sample of 20** (seed 7, includes 6 bank revenue questions): 18 match, 0 wrong values, 2 not found in the document.
- **All 366 questions** (`--all`): 324 match, **0 wrong values**, 42 not found in the document.
- All 42 not-found questions belong to **WFC, USB and PGR** (14 each). Their primary 10-K document does not contain the financial statements: PGR's are in Exhibit 13 (annual report to shareholders), and WFC's and USB's primary documents carry only 2–18 tagged figures versus 1,000–10,000 for other filers. These questions are unanswerable from the current corpus until those exhibits are ingested.

## Sample of 20

| Question id | Row label in the filing | Displayed | Scale | Status |
| --- | --- | --- | --- | --- |
| `xbrl-MS-2025-12-31-revenue` | Net revenues | 70,645 | millions | match |
| `xbrl-BAC-2025-12-31-revenue` | Total revenue, net of interest expense | 113,097 | millions | match |
| `xbrl-C-2025-12-31-revenue` | Total revenues, net of interest expense(1) | 85,225 | millions | match |
| `xbrl-PNC-2024-12-31-revenue` | Total revenue | 21,555 | millions | match |
| `xbrl-NKE-2026-05-31-total_assets` | TOTAL ASSETS | 38,410 | millions | match |
| `xbrl-PRU-2025-12-31-net_income` | NET INCOME (LOSS) ATTRIBUTABLE TO PRUDENTIAL FINANCIAL, INC. | 3,576 | millions | match |
| `xbrl-MS-2025-12-31-net_income` | Net income applicable to Morgan Stanley | 16,861 | millions | match |
| `xbrl-CB-2025-12-31-eps_diluted` | Diluted earnings per share attributable to Chubb | 25.68 | units | match |
| `xbrl-COF-2025-12-31-revenue` | Total net revenue (loss)(2) | 53,434 | millions | match |
| `xbrl-JNJ-2025-12-28-operating_cash_flow` | Net cash flows from operating activities | 24,530 | millions | match |
| `xbrl-GS-2024-12-31-revenue` | Total net revenues | 53,512 | millions | match |
| `xbrl-AAPL-2024-09-28-cash` | Cash and cash equivalents | 29,943 | millions | match |
| `xbrl-PGR-2025-12-31-stockholders_equity` |  |  |  | not displayed (no visible tagged figure) |
| `xbrl-ALL-2025-12-31-eps_diluted` | Net income (loss) applicable to common shareholders per common share - Diluted | 38.06 | units | match |
| `xbrl-WFC-2024-12-31-revenue` |  |  |  | not displayed (no visible tagged figure) |
| `xbrl-JPM-2025-12-31-eps_diluted` | Diluted earnings per share | 20.02 | units | match |
| `xbrl-BAC-2025-12-31-net_income` | Net income | 30,509 | millions | match |
| `xbrl-PNC-2024-12-31-stockholders_equity` | Total shareholders’ equity | 54,425 | millions | match |
| `xbrl-MET-2024-12-31-eps_diluted` | Diluted | 5.94 | units | match |
| `xbrl-KO-2024-12-31-net_income` | Net Income Attributable to Shareowners of The Coca-Cola Company | 10,631 | millions | match |

## Findings

1. **Bank revenue wording differs from our question.** We ask for "total revenue"; the filings say "Net revenues" (MS), "Total revenue, net of interest expense" (BAC), "Total revenues, net of interest expense" (C), "Total net revenue" (COF), "Total net revenues" (GS) and "Total revenue" (PNC). Values match; the wording gap is a retrieval risk worth measuring in week 2.
2. **Net income is reported as the parent's share** where there are noncontrolling interests ("Net income applicable to Morgan Stanley", "attributable to Prudential Financial", "attributable to Shareowners of The Coca-Cola Company"). Consistent with the `NetIncomeLoss` tag.
3. **Scale:** every displayed figure was in millions except per-share values, so answer scoring must normalize scale.
4. **Corpus gap:** see above; fix in week 2 by ingesting financial-statement exhibits (e.g. EX-13).
