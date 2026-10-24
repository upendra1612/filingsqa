"""Generate numeric eval questions with exact answers from SEC XBRL company facts.

For every downloaded 10-K, look up the value the company itself tagged for a
handful of headline metrics in *that* filing and for *that* fiscal year. The
answer therefore comes from the SEC, not from a human labeler.

Usage:
    filingsqa-xbrl-questions --manifest data/manifest.jsonl \
        --out evals/golden/xbrl_numeric.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Metric:
    key: str
    label: str  # wording used in the question
    concepts: tuple[str, ...]  # us-gaap tags to try, in order
    unit: str
    duration: bool  # True = flow over the year; False = balance at year end


METRICS: tuple[Metric, ...] = (
    Metric(
        "revenue",
        "total revenue",
        (
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenuesNetOfInterestExpense",
            "SalesRevenueNet",
        ),
        "USD",
        True,
    ),
    # Fallbacks are used only when the filing does not tag the standard concept for
    # that period. They include noncontrolling interests (e.g. PNC and JNJ in their
    # FY2024-FY2025 10-Ks); each question records which concept its answer came from.
    Metric("net_income", "net income", ("NetIncomeLoss", "ProfitLoss"), "USD", True),
    Metric(
        "eps_diluted",
        "diluted earnings per share",
        ("EarningsPerShareDiluted",),
        "USD/shares",
        True,
    ),
    Metric(
        "operating_cash_flow",
        "net cash provided by operating activities",
        ("NetCashProvidedByUsedInOperatingActivities",),
        "USD",
        True,
    ),
    Metric("total_assets", "total assets", ("Assets",), "USD", False),
    Metric("total_liabilities", "total liabilities", ("Liabilities",), "USD", False),
    Metric(
        "stockholders_equity",
        "total stockholders' equity",
        (
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        "USD",
        False,
    ),
    Metric(
        "cash",
        "cash and cash equivalents",
        ("CashAndCashEquivalentsAtCarryingValue",),
        "USD",
        False,
    ),
)


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def find_fact(
    facts: dict[str, Any], metric: Metric, accession: str, period_end: str
) -> tuple[str, float] | None | str:
    """Return (concept, value) reported in this filing for this period.

    Returns None if no tag matches, or the string "ambiguous" if the filing
    reports conflicting values (we skip those rather than guess).
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in metric.concepts:
        entries = us_gaap.get(concept, {}).get("units", {}).get(metric.unit, [])
        values = set()
        for e in entries:
            if e.get("accn") != accession or e.get("end") != period_end:
                continue
            if not str(e.get("form", "")).startswith("10-K"):
                continue
            if metric.duration:
                start = e.get("start")
                if not start or not 330 <= _days(start, period_end) <= 380:
                    continue  # skip quarterly or multi-year values
            elif e.get("start"):
                continue
            values.add(e["val"])
        if len(values) == 1:
            return concept, values.pop()
        if len(values) > 1:
            return "ambiguous"
    return None


def format_period(period_end: str) -> str:
    d = date.fromisoformat(period_end)
    return f"{d:%B} {d.day}, {d.year}"


def build_questions(manifest: list[dict], facts_by_ticker: dict[str, dict]) -> tuple[list, dict]:
    questions: list[dict] = []
    stats = {"generated": 0, "missing": 0, "ambiguous": 0}
    for filing in manifest:
        facts = facts_by_ticker.get(filing["ticker"])
        period_end = filing.get("report_date")
        if not facts or not period_end:
            continue
        for metric in METRICS:
            found = find_fact(facts, metric, filing["accession"], period_end)
            if found is None:
                stats["missing"] += 1
                continue
            if found == "ambiguous":
                stats["ambiguous"] += 1
                continue
            concept, value = found
            questions.append(
                {
                    "id": f"xbrl-{filing['ticker']}-{period_end}-{metric.key}",
                    "question": (
                        f"What was {filing['company']}'s {metric.label} for the fiscal year "
                        f"ended {format_period(period_end)}?"
                    ),
                    "expected": {"value": value, "unit": metric.unit},
                    "source": {
                        "ticker": filing["ticker"],
                        "accession": filing["accession"],
                        "concept": f"us-gaap:{concept}",
                        "period_end": period_end,
                        "document": filing["local_path"],
                    },
                    "category": "numeric_extraction",
                    "difficulty": "easy",
                    "origin": "xbrl",
                }
            )
            stats["generated"] += 1
    return questions, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default="data/manifest.jsonl")
    parser.add_argument("--raw", default="data/raw")
    parser.add_argument("--out", default="evals/golden/xbrl_numeric.jsonl")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"error: {manifest_path} not found; run filingsqa-download first", file=sys.stderr)
        return 2
    manifest = [json.loads(line) for line in manifest_path.read_text().splitlines() if line]

    facts_by_ticker = {}
    for ticker in {f["ticker"] for f in manifest}:
        path = Path(args.raw) / ticker / "companyfacts.json"
        if path.is_file():
            facts_by_ticker[ticker] = json.loads(path.read_text(encoding="utf-8"))

    questions, stats = build_questions(manifest, facts_by_ticker)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for q in questions:
            fh.write(json.dumps(q) + "\n")

    print(
        f"{stats['generated']} questions -> {out} "
        f"(no matching tag: {stats['missing']}, skipped as ambiguous: {stats['ambiguous']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
