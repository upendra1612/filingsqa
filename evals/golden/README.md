# Golden eval sets

All sets are JSONL, one question per line, with the same fields:

```json
{
  "id": "unique-id",
  "question": "…",
  "expected": {"value": 123, "unit": "USD"},
  "source": {"ticker": "…", "accession": "…", "period_end": "YYYY-MM-DD"},
  "category": "numeric_extraction | segment_extraction | multi_hop | qualitative | not_answerable",
  "difficulty": "easy | medium | hard",
  "origin": "xbrl | financebench | curated"
}
```

For text answers, `expected` is `{"text": "…", "key_points": ["…", "…"]}`.
For questions the filing cannot answer, it is `{"answerable": false, "reason": "…"}`.
Curated questions also carry `evidence`: verbatim quotes, the tagged figure and row label,
the inputs to a calculation, or the keyword searches that found no answer.

| File | Built by | Size |
| --- | --- | --- |
| `xbrl_numeric.jsonl` | `filingsqa-xbrl-questions` | 366 |
| `curated.jsonl` | `python scripts/build_curated.py` (AI-drafted, machine-verified; see below) | 50 |
| `financebench.jsonl` | conversion script (week 2, after inspecting the dataset fields) | 150 |
| `smoke.jsonl` | fixed random 30 from the sets above, for CI | 30 |

## `curated.jsonl`

50 questions covering what XBRL company facts cannot: 19 qualitative (workforce,
segments, disclosures), 10 segment-level figures, 10 year-over-year calculations and
11 questions the filing **cannot** answer, so abstention can be measured.

How they were made, stated plainly: the questions were drafted with an AI assistant
from the downloaded 10-K text and then checked by script, not by hand. The build fails
unless every quote appears in its filing, every figure matches the filing's displayed
inline-XBRL table (single unambiguous value), every percentage is recomputed from the
two displayed figures, and every not-answerable question returns zero hits for its
keyword searches. Review them yourself before relying on them; a keyword search can
miss an answer phrased differently.

Known gap: questions for WFC, USB and PGR in `xbrl_numeric.jsonl` are currently
unanswerable from the corpus, because those companies' financial statements are in
exhibits we do not download yet (see `evals/results/spot_check_xbrl.md`). Exclude them
from scoring until the exhibits are ingested.
