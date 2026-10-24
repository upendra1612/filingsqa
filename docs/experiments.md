# Experiment log

One entry per experiment, written the day it runs, including failures.
Format: **Tried X → measured Y → kept or dropped because Z.** Link the results file.

| Date | Change | Result (metric: before → after) | Decision and why | Results file |
| --- | --- | --- | --- | --- |
| 2026-10-24 | XBRL question generation: add fallback tags `ProfitLoss` (net income) and `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` (equity), used only when the standard tag is absent for that filing and period | Questions 362 → 366; missing 38 → 34; ambiguous 0 → 0 | Kept. PNC and JNJ tag only the broader concepts in their FY2024–FY2025 10-Ks, confirmed by listing every tagged value in each filing; the standard tag still wins when present (unit-tested), so other companies are unaffected. Caveat: both fallbacks include noncontrolling interests | `evals/golden/xbrl_numeric.jsonl` (commit 6ab4c90) |
| 2026-10-24 | Spot-check XBRL questions against the displayed figures in each 10-K (`scripts/spot_check.py`): sample of 20, then all 366 | 324/366 match, 0 wrong values; 42 not found, all from WFC, USB and PGR | Found a corpus gap: those three file their financial statements in exhibits (PGR: Exhibit 13), not the primary document we download. Their 42 questions are unanswerable until week 2 ingests those exhibits; exclude them from scoring until then. Also found bank revenue labels differ from our "total revenue" wording (e.g. "Total revenue, net of interest expense") | `evals/results/spot_check_xbrl.md`, `evals/results/full_check_xbrl.json` |
| | Baseline: fixed 800-token chunks, dense top-5, one LLM call | | | |
