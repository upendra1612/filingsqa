"""Grade the question-answering system on the golden question sets.

Usage:
    filingsqa-eval --set smoke              # 30 questions, quick check
    filingsqa-eval --set dev                # 120 questions, day-to-day comparisons
    filingsqa-eval --set full               # every verified question

Grading is deterministic, with no LLM judge:
- amounts: the first stated amount must equal the filing's figure at the precision the
  answer claims ("$41,162 million" must match to the million; "$41.45 billion" must
  round correctly)
- percentages: within 0.15 percentage points, with the right direction
- text facts: every key point must appear in the answer
- not-answerable questions: correct only if the system says NOT_FOUND
Answers are cached per question and configuration, so an interrupted run resumes
where it stopped and re-runs cost nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

GOLDEN = Path("evals/golden")
SPLITS = GOLDEN / "splits.json"
SCALES = {"trillion": 1e12, "billion": 1e9, "bn": 1e9, "million": 1e6, "thousand": 1e3}
NEG_CUES = ("decrease", "decline", "fell", "lower", "down", "drop", "-", "−", "–", "(")

NUM_RE = re.compile(
    r"(?P<neg>[-−–(])?\s*(?P<cur>\$)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<pct>%|percent\b)?\s*(?P<scale>trillion|billion|bn|million|thousand)?",
    re.I,
)


# ---------------------------------------------------------------- loading


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def load_questions() -> dict[str, dict]:
    qs = {}
    for name in ("xbrl_numeric.jsonl", "curated.jsonl"):
        if (GOLDEN / name).is_file():
            for q in load_jsonl(GOLDEN / name):
                qs[q["id"]] = q
    return qs


def make_splits(questions: dict[str, dict], seed: int = 13) -> dict[str, list[str]]:
    """Fixed id lists, so a set never drifts when golden files are regenerated.

    dev   = all curated questions + 70 XBRL questions spread across companies and metrics
    smoke = 30 of dev, for CI and quick checks
    """
    rng = random.Random(seed)
    curated = sorted(i for i, q in questions.items() if q.get("origin") == "curated")
    xbrl = sorted(i for i, q in questions.items() if q.get("origin") == "xbrl")
    rng.shuffle(xbrl)
    picked, seen_pair, seen_ticker = [], set(), {}
    for qid in xbrl:  # one per (company, metric), at most 3 per company
        q = questions[qid]
        pair = (q["source"]["ticker"], qid.rsplit("-", 1)[1])
        if pair in seen_pair or seen_ticker.get(pair[0], 0) >= 3:
            continue
        picked.append(qid)
        seen_pair.add(pair)
        seen_ticker[pair[0]] = seen_ticker.get(pair[0], 0) + 1
        if len(picked) == 70:
            break
    dev = sorted(curated + picked)
    smoke = sorted(rng.sample(dev, 30))
    return {"dev": dev, "smoke": smoke}


def select(questions: dict[str, dict], set_name: str, unverified: set[str]) -> list[dict]:
    if set_name == "full":
        ids = sorted(questions)
    else:
        ids = json.loads(SPLITS.read_text())[set_name]
    return [questions[i] for i in ids if i in questions and i not in unverified]


def unverified_ids(spot_check_path: Path) -> set[str]:
    """XBRL questions whose figure was not found in the filing text: unanswerable as built."""
    if not spot_check_path.is_file():
        return set()
    data = json.loads(spot_check_path.read_text())
    return {r["id"] for r in data["results"] if r["status"] != "match"}


# ---------------------------------------------------------------- grading


def numbers_in(text: str) -> list[dict]:
    out = []
    for m in NUM_RE.finditer(text):
        raw = m.group("num").replace(",", "")
        scale = SCALES[m.group("scale").lower()] if m.group("scale") else 1.0
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        out.append(
            {
                "value": float(raw) * scale,
                # smallest step the answer states, e.g. "$41.45 billion" -> $10 million
                "precision": scale * 10**-decimals,
                "pct": bool(m.group("pct")),
                "money": bool(m.group("cur") or m.group("scale")),
                "neg": bool(m.group("neg")),
            }
        )
    return out


def normalize(text: str) -> str:
    t = text.lower().replace("’", "'").replace("&", " and ")
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    t = re.sub(r"[^a-z0-9%.' ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def grade(q: dict, answer: str, abstained: bool) -> dict:
    exp, cat = q["expected"], q["category"]
    if cat == "not_answerable":
        return {"correct": abstained, "answered": not abstained}
    if abstained:
        return {"correct": False, "answered": False}
    if "text" in exp:
        ans = normalize(answer)
        hits = [kp for kp in exp["key_points"] if normalize(kp) in ans]
        return {
            "correct": len(hits) == len(exp["key_points"]),
            "answered": True,
            "key_point_recall": round(len(hits) / len(exp["key_points"]), 3),
        }
    nums = numbers_in(answer)
    target = float(exp["value"])
    if exp["unit"] == "percent":
        pcts = [n for n in nums if n["pct"]]
        if not pcts:
            return {"correct": False, "answered": True, "parsed": None}
        got = pcts[-1]  # the result usually comes last, after the inputs
        sign_ok = target >= 0 or got["neg"] or any(c in answer.lower() for c in NEG_CUES)
        ok = abs(got["value"] - abs(target)) <= exp.get("tolerance", 0.1) + 0.05 and sign_ok
        return {"correct": ok, "answered": True, "parsed": got["value"]}
    money = [n for n in nums if n["money"]] or nums
    if not money:
        return {"correct": False, "answered": True, "parsed": None}
    got = money[0]
    # Correct if the stated figure is the filing's figure rounded to the stated precision.
    # A 0.5% tolerance was tried first and wrongly accepted $41,162M for $41,139M.
    tol = got["precision"] / 2 + 1e-9 * max(abs(target), 1.0)
    ok = abs(got["value"] - abs(target)) <= tol
    return {"correct": ok, "answered": True, "parsed": got["value"]}


def evidence_strings(q: dict) -> list[str]:
    """Text that must appear in a retrieved passage for retrieval to count as a hit."""
    ev, exp = q.get("evidence", {}), q["expected"]
    if "quotes" in ev:
        return [" ".join(s.split())[:60] for s in ev["quotes"]]
    if "current" in ev:
        return [ev["current"]["displayed"], ev["prior"]["displayed"]]
    if "displayed" in ev:
        return [ev["displayed"]]
    if "value" in exp:  # XBRL questions: filings show amounts in millions
        v = float(exp["value"])
        return [f"{v / 1e6:,.0f}"] if exp["unit"] == "USD" and abs(v) >= 1e6 else [f"{v:g}"]
    return []


def retrieval_hits(q: dict, hits: list[dict]) -> dict:
    """filing_hit: a passage from the exact filing was retrieved.
    evidence_hit: the expected figure or quote appears in a retrieved passage from the
    same company, from any year, because later 10-Ks repeat prior-year figures."""
    src = q["source"]
    same_filing = [
        h for h in hits if h["ticker"] == src["ticker"] and h["period_end"] == src["period_end"]
    ]
    if q["category"] == "not_answerable":
        return {"filing_hit": bool(same_filing), "evidence_hit": None}
    needles = evidence_strings(q)
    text = " ".join(" ".join(h["text"].split()) for h in hits if h["ticker"] == src["ticker"])
    return {
        "filing_hit": bool(same_filing),
        "evidence_hit": bool(needles) and all(n in text for n in needles),
    }


# ---------------------------------------------------------------- running


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p * (len(values) - 1))))]


def summarize(items: list[dict]) -> dict:
    def rate(rows, key):
        rows = [r for r in rows if r.get(key) is not None]
        return round(sum(bool(r[key]) for r in rows) / len(rows), 3) if rows else None

    answerable = [r for r in items if r["category"] != "not_answerable"]
    na = [r for r in items if r["category"] == "not_answerable"]
    lat = [r.get("llm_latency_ms") or r["latency_ms"] for r in items]
    wall = [r["latency_ms"] for r in items]
    by_cat = {}
    for cat in sorted({r["category"] for r in items}):
        rows = [r for r in items if r["category"] == cat]
        by_cat[cat] = {"n": len(rows), "accuracy": rate(rows, "correct")}
    return {
        "n": len(items),
        "accuracy": rate(items, "correct"),
        "answerable_accuracy": rate(answerable, "correct"),
        "wrong_answer_rate": round(
            sum(r["answered"] and not r["correct"] for r in answerable) / len(answerable), 3
        )
        if answerable
        else None,
        "abstention_rate_answerable": round(
            sum(not r["answered"] for r in answerable) / len(answerable), 3
        )
        if answerable
        else None,
        "not_answerable_correct": rate(na, "correct"),
        "filing_hit_at_k": rate(answerable, "filing_hit"),
        "evidence_hit_at_k": rate(answerable, "evidence_hit"),
        "latency_p50_ms": pct(lat, 0.5),  # model call only
        "latency_p95_ms": pct(lat, 0.95),
        "wall_p50_ms": pct(wall, 0.5),  # including free-tier rate-limit waits
        "prompt_tokens": sum(r["prompt_tokens"] for r in items),
        "completion_tokens": sum(r["completion_tokens"] for r in items),
        "by_category": by_cat,
    }


def run(questions: list[dict], answer_fn, cache_dir: Path, progress=print) -> list[dict]:
    """answer_fn(question_text) -> rag.Answer. Cached per question id in cache_dir."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for i, q in enumerate(questions, 1):
        path = cache_dir / f"{q['id']}.json"
        if path.is_file():
            item = json.loads(path.read_text(encoding="utf-8"))
        else:
            a = answer_fn(q["question"])
            hits = [{**h.meta, "score": round(h.score, 4)} for h in a.hits]
            item = {
                "id": q["id"],
                "category": q["category"],
                "question": q["question"],
                "expected": q["expected"],
                "answer": a.answer,
                "abstained": a.abstained,
                "citations": a.citations,
                "hits": hits,
                "latency_ms": a.latency_ms,
                "llm_latency_ms": a.llm_latency_ms,
                "prompt_tokens": a.prompt_tokens,
                "completion_tokens": a.completion_tokens,
                "model": a.model,
            }
            path.write_text(json.dumps(item), encoding="utf-8")
        item.update(grade(q, item["answer"], item["abstained"]))
        item.update(retrieval_hits(q, item["hits"]))
        items.append(item)
        progress(f"  [{i}/{len(questions)}] {'OK ' if item['correct'] else 'X  '} {q['id']}")
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", default="dev", choices=["smoke", "dev", "full"])
    ap.add_argument("--index", default="baseline")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions")
    ap.add_argument(
        "--spot-check",
        default="evals/results/full_check_xbrl.json",
        help="exclude XBRL questions this spot-check could not verify",
    )
    ap.add_argument("--make-splits", action="store_true", help="(re)write evals/golden/splits.json")
    ap.add_argument(
        "--regrade", metavar="RESULTS_JSON", help="re-score saved answers, no LLM calls"
    )
    args = ap.parse_args(argv)

    if args.regrade:
        regrade(Path(args.regrade))
        return 0

    questions = load_questions()
    if args.make_splits:
        SPLITS.write_text(json.dumps(make_splits(questions), indent=1) + "\n")
        print(f"wrote {SPLITS}")
        return 0

    from qdrant_client import QdrantClient

    from .embeddings import FastEmbedder
    from .env import load_dotenv
    from .index import QDRANT_PATH
    from .llm import ChatClient, DailyLimitError, extra_params
    from .rag import SYSTEM_PROMPT, Retriever, answer_question

    load_dotenv()
    info_path = Path("data/index") / args.index / "index_info.json"
    if not info_path.is_file():
        print(f"error: index '{args.index}' not built; run filingsqa-index first", file=sys.stderr)
        return 2
    info = json.loads(info_path.read_text())
    llm = ChatClient()
    llm.check_model()
    retriever = Retriever(
        QdrantClient(path=QDRANT_PATH), FastEmbedder(info["embedding_model"]), args.index
    )
    # Only settings that change answers go in the cache key. Build timings and
    # cache statistics differ on every rebuild and must not invalidate cached answers.
    index_settings = {
        k: info[k]
        for k in ("name", "embedding_model", "chunker", "chunk_words", "overlap", "chunks")
    }
    config = {
        "index": index_settings,
        "k": args.k,
        "model": llm.model,
        "base_url": llm.base_url,
        "llm_params": extra_params(llm.model),
        "prompt_sha": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:10],
    }
    key = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:12]

    excluded = unverified_ids(Path(args.spot_check))
    qs = select(questions, args.set, excluded)
    if args.limit:
        qs = qs[: args.limit]
    print(
        f"{len(qs)} questions ({args.set}), index={args.index}, k={args.k}, model={llm.model}"
        f"{f', excluding {len(excluded)} unverified' if excluded else ''}"
    )
    started = time.time()
    cache_dir = Path("data/eval_cache") / key
    try:
        items = run(qs, lambda text: answer_question(text, retriever, llm, args.k), cache_dir)
    except DailyLimitError as exc:
        done = len(list(cache_dir.glob("*.json")))
        print(
            f"\nStopped: {exc}. {done}/{len(qs)} answers are saved; re-run the same "
            "command after the limit resets to continue."
        )
        return 3
    summary = summarize(items)
    write_results(items, summary, config, key, args.set, args.index, excluded)
    print(f"{time.time() - started:.0f}s total")
    return 0


def write_results(items, summary, config, key, set_name, index, excluded, suffix=""):
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = Path("evals/results") / f"{stamp}_{git_sha()}_{index}_{set_name}{suffix}.json"
    payload = {
        "config": config,
        "config_key": key,
        "set": set_name,
        "git_sha": git_sha(),
        "excluded": sorted(excluded),
        "summary": summary,
        "items": items,
    }
    out.write_text(json.dumps(payload, indent=1))
    print_summary(summary, config.get("k", 5))
    print(f"-> {out}")
    return out


def print_summary(s: dict, k: int) -> None:
    def p(v):
        return "n/a" if v is None else f"{v:.1%}"

    print(
        f"\nAccuracy {p(s['accuracy'])} | wrong answers {p(s['wrong_answer_rate'])} | "
        f"abstained on answerable {p(s['abstention_rate_answerable'])} | "
        f"not-answerable caught {p(s['not_answerable_correct'])}"
    )
    print(
        f"Retrieval: right filing in top-{k} {p(s['filing_hit_at_k'])}, "
        f"evidence in top-{k} {p(s['evidence_hit_at_k'])}"
    )
    print(
        f"Model latency p50 {s['latency_p50_ms']} ms, p95 {s['latency_p95_ms']} ms "
        f"(wall clock incl. rate-limit waits p50 {s.get('wall_p50_ms', 'n/a')} ms); "
        f"tokens {s['prompt_tokens']:,} in / {s['completion_tokens']:,} out"
    )
    for cat, v in s["by_category"].items():
        print(f"  {cat:20} n={v['n']:3}  accuracy {p(v['accuracy'])}")


def regrade(path: Path) -> Path:
    """Re-score saved answers with the current grader. No retrieval or LLM calls."""
    data = json.loads(path.read_text())
    questions = load_questions()
    items = []
    for item in data["items"]:
        q = questions[item["id"]]
        item = {k: v for k, v in item.items() if k not in ("key_point_recall", "parsed")}
        item.update(grade(q, item["answer"], item["abstained"]))
        item.update(retrieval_hits(q, item["hits"]))
        items.append(item)
    summary = summarize(items)
    return write_results(
        items,
        summary,
        data["config"],
        data["config_key"],
        data["set"],
        data["config"]["index"]["name"],
        set(data.get("excluded", [])),
        suffix="_regraded",
    )


if __name__ == "__main__":
    raise SystemExit(main())
