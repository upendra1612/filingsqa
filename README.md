# FilingsQA: cited answers from SEC 10-K filings, measured on a public benchmark

> Status: **week 2 of 7** — baseline measured; next: company/year filtering and better chunking.

[Demo video — coming week 7] · [Live app — coming week 2] · [Blog post — coming week 7]

## Results

| Config | Eval set | Accuracy | Wrong-answer rate | Abstained (answerable) | Not-answerable caught | Right filing in top-5 | Evidence in top-5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline: 400-word chunks, bge-small, dense top-5, gpt-oss-120b | smoke (30) | 56.7% | 10.7% | 35.7% | 2/2 | 89.3% | 57.1% |

Eval sets: 366 XBRL-derived questions (each verified against the figure displayed in its filing) + 50 curated questions, including 11 the filings cannot answer. Fixed subsets: smoke (30) and dev (120). FinanceBench (150) is planned as an external benchmark.
Every number in this table comes from a results file in `evals/results/` (baseline: `20261116-0030_8e0981e_baseline_smoke_regraded.json`).

## What I learned

- **Retrieval, not the LLM, limits the baseline.** When the right passage was retrieved, answers were correct 14 times out of 16; when it was not, 1 time out of 12.
- **It declines rather than guesses.** All 10 answerable questions it declined were ones where search had not found the evidence, and it caught both unanswerable questions.
- **The grader needed fixing first.** A 0.5% tolerance accepted a figure from the wrong line item; amounts now must match at the precision the answer states.

## Data

See [DATA.md](DATA.md) for every source, its license and how to rebuild it.

## What didn't work

See [docs/experiments.md](docs/experiments.md).

## Run it locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env             # add SEC_USER_AGENT and GROQ_API_KEY
pytest -q                        # offline tests
filingsqa-download --per-company 2
filingsqa-xbrl-questions
filingsqa-index                  # chunk + embed locally; resumable
filingsqa-eval --set smoke       # or --set dev / --set full
```
