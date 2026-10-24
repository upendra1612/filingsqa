"""Structural checks on the committed eval sets. Runs offline in CI.

Content is verified against the filings by scripts/build_curated.py and
scripts/spot_check.py, which need the downloaded data.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parents[1] / "evals" / "golden"
CATEGORIES = {
    "numeric_extraction",
    "segment_extraction",
    "multi_hop",
    "qualitative",
    "not_answerable",
}
REQUIRED = {"id", "question", "expected", "source", "category", "difficulty", "origin"}


def load(name):
    path = GOLDEN / name
    if not path.is_file():
        pytest.skip(f"{name} not present")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@pytest.mark.parametrize("name", ["xbrl_numeric.jsonl", "curated.jsonl"])
def test_every_question_has_required_fields_and_unique_id(name):
    qs = load(name)
    assert qs
    for q in qs:
        assert REQUIRED <= q.keys(), q.get("id")
        assert q["category"] in CATEGORIES, q["id"]
        assert q["difficulty"] in {"easy", "medium", "hard"}, q["id"]
        assert {"ticker", "accession", "period_end", "document"} <= q["source"].keys(), q["id"]
    assert len({q["id"] for q in qs}) == len(qs)


def test_curated_set_shape():
    qs = load("curated.jsonl")
    counts = Counter(q["category"] for q in qs)
    assert len(qs) == 50
    assert counts["not_answerable"] >= 10
    for q in qs:
        exp, ev = q["expected"], q["evidence"]
        if q["category"] == "not_answerable":
            assert exp["answerable"] is False and exp["reason"]
            assert ev["absence_check"]["hits"] == 0
        elif q["category"] == "qualitative":
            assert exp["text"] and exp["key_points"] and ev["quotes"]
        else:
            assert isinstance(exp["value"], (int, float)) and exp["unit"]


def test_curated_ids_do_not_collide_with_xbrl_ids():
    ids_a = {q["id"] for q in load("xbrl_numeric.jsonl")}
    ids_b = {q["id"] for q in load("curated.jsonl")}
    assert not ids_a & ids_b
