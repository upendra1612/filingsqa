"""Spot-check XBRL eval questions against the 10-K document itself.

For each sampled question, find the number in the filing's inline XBRL (the
tagged figure a reader sees in the HTML table), and report:
  - the row label printed next to it (e.g. "Total net revenue")
  - the figure as displayed (e.g. "182,447") and the scale (e.g. millions)
  - whether displayed figure x scale equals the expected answer

This confirms the answer is visible in the document a retriever will search,
and surfaces wording mismatches between our question and the filing's label.
It does not independently audit the company's own tagging.

Usage:
    python spot_check.py --questions evals/golden/xbrl_numeric.jsonl --n 20 --seed 7
"""

from __future__ import annotations

import argparse
import functools
import json
import random
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

IX = "{http://www.xbrl.org/2013/inlineXBRL}"
XBRLI = "{http://www.xbrl.org/2003/instance}"
XHTML = "{http://www.w3.org/1999/xhtml}"
SCALE_WORD = {0: "units", 3: "thousands", 6: "millions", 9: "billions"}
BANKS = {"JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC"}


def text_of(el: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _period(period: ET.Element, tag: str) -> str | None:
    return (period.findtext(f"{XBRLI}{tag}") or "").strip() or None


def load_contexts(root: ET.Element) -> dict[str, dict]:
    """contextRef id -> {"start", "end", "instant", "has_dims"}."""
    ctx = {}
    for c in root.iter(f"{XBRLI}context"):
        period = c.find(f"{XBRLI}period")
        if period is None:
            continue
        ctx[c.get("id")] = {
            "start": _period(period, "startDate"),
            "end": _period(period, "endDate") or _period(period, "instant"),
            "instant": _period(period, "instant") is not None,
            "has_dims": c.find(f".//{XBRLI}segment") is not None,
        }
    return ctx


def displayed_value(el: ET.Element) -> float | None:
    raw = text_of(el)
    if el.get("format", "").endswith(("fixed-zero", "zerodash")) or raw in {"—", "-", "–"}:
        num = 0.0
    else:
        digits = re.sub(r"[^\d.]", "", raw)
        if not digits:
            return None
        num = float(digits)
    scale = int(el.get("scale", "0"))
    sign = -1 if el.get("sign") == "-" else 1
    return sign * num * 10**scale


def find_row_label(el: ET.Element, parents: dict) -> str:
    node = el
    while node is not None and node.tag != f"{XHTML}tr":
        node = parents.get(node)
    if node is None:
        return "(not in a table)"
    for cell in node:
        t = text_of(cell)
        if t and not re.fullmatch(r"[\s$()\d,.%—–-]*", t):
            return t[:80]
    return "(no label)"


@functools.lru_cache(maxsize=4)
def parse_document(path: str):
    """Parse once per document; questions are processed grouped by document."""
    root = ET.parse(path).getroot()
    contexts = load_contexts(root)
    parents = {child: parent for parent in root.iter() for child in parent}
    hidden = {e for h in root.iter(f"{IX}hidden") for e in h.iter()}
    return root, contexts, parents, hidden


def check(question: dict, project: Path) -> dict:
    src = question["source"]
    concept = src["concept"]  # e.g. us-gaap:Revenues
    path = project / src["document"]
    out = {"id": question["id"], "ticker": src["ticker"], "expected": question["expected"]["value"]}
    if not path.is_file():
        return {**out, "status": "missing document"}
    try:
        root, contexts, parents, hidden = parse_document(str(path))
    except ET.ParseError as exc:
        return {**out, "status": f"parse error: {exc}"}

    candidates = []
    for el in root.iter(f"{IX}nonFraction"):
        if el.get("name") != concept or el in hidden:
            continue
        c = contexts.get(el.get("contextRef"), {})
        if c.get("has_dims") or c.get("end") != src["period_end"]:
            continue
        candidates.append(el)
    if not candidates:
        return {**out, "status": "not displayed (no visible tagged figure)"}

    el = candidates[0]  # first occurrence = usually the primary statement
    value = displayed_value(el)
    scale = int(el.get("scale", "0"))
    match = value is not None and abs(value - out["expected"]) <= max(
        1.0, abs(out["expected"]) * 1e-9
    )
    return {
        **out,
        "status": "match" if match else "MISMATCH",
        "label_in_filing": find_row_label(el, parents),
        "displayed": text_of(el),
        "scale": SCALE_WORD.get(scale, f"10^{scale}"),
        "occurrences": len(candidates),
        "question": question["question"],
    }


def sample(questions: list[dict], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    bank_rev = [
        q for q in questions if q["source"]["ticker"] in BANKS and q["id"].endswith("-revenue")
    ]
    picked = rng.sample(bank_rev, min(4, len(bank_rev)))
    rest = [q for q in questions if q not in picked]
    # spread the remainder across companies
    rng.shuffle(rest)
    seen: dict[str, int] = {}
    for q in rest:
        if len(picked) >= n:
            break
        t = q["source"]["ticker"]
        if seen.get(t, 0) < 1:
            picked.append(q)
            seen[t] = seen.get(t, 0) + 1
    for q in rest:  # top up if fewer companies than n
        if len(picked) >= n:
            break
        if q not in picked:
            picked.append(q)
    return picked


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--questions", default="evals/golden/xbrl_numeric.jsonl")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--all", action="store_true", help="check every question, not a sample")
    ap.add_argument("--out", default="evals/results/spot_check_xbrl.json")
    args = ap.parse_args(argv)
    project = Path(args.project)
    qs = [json.loads(line) for line in (project / args.questions).read_text().splitlines() if line]
    chosen = (
        sorted(qs, key=lambda q: q["source"]["document"])
        if args.all
        else sample(qs, args.n, args.seed)
    )
    results = [check(q, project) for q in chosen]
    for r in results:
        print(
            f"[{r['status']}] {r['id']}: {r.get('label_in_filing', '')} | "
            f"{r.get('displayed', '')} ({r.get('scale', '')}) vs {r['expected']:,}"
        )
    out = project / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"seed": args.seed, "results": results}, indent=2))
    ok = sum(r["status"] == "match" for r in results)
    print(f"\n{ok}/{len(results)} match -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
