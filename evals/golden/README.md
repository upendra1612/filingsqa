# Golden eval sets

All sets are JSONL, one question per line, with the same fields:

```json
{
  "id": "unique-id",
  "question": "…",
  "expected": {"value": 123, "unit": "USD"},
  "source": {"ticker": "…", "accession": "…", "period_end": "YYYY-MM-DD"},
  "category": "numeric_extraction | multi_hop | qualitative | not_answerable",
  "difficulty": "easy | medium | hard",
  "origin": "xbrl | financebench | handwritten"
}
```

For text answers, `expected` is `{"text": "…", "key_points": ["…", "…"]}`.

| File | Built by | Target size |
| --- | --- | --- |
| `xbrl_numeric.jsonl` | `filingsqa-xbrl-questions` | ~200–400 |
| `financebench.jsonl` | conversion script (week 1, after inspecting the dataset fields) | 150 |
| `handwritten.jsonl` | you, by hand, with the answer checked in the filing | 50 |
| `smoke.jsonl` | fixed random 30 from the three above, for CI | 30 |

Hand-written questions should cover what XBRL cannot: risk factors,
year-over-year comparisons, segment details, and at least 10
**not answerable** questions (the filing does not contain the answer),
so abstention can be measured.
