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

## Deploy it for free

| Piece | Host (free tier) | Config |
|---|---|---|
| Vector store | Qdrant Cloud, 1 GB cluster | `filingsqa-index --cloud` with `QDRANT_URL`, `QDRANT_API_KEY` in `.env` |
| API (FastAPI) | Render web service, Docker | `render.yaml`, `Dockerfile`; secrets set in the Render dashboard |
| Demo page | Streamlit Community Cloud | `ui/app.py`, secret `API_URL` |
| Keep-alive | GitHub Actions | `.github/workflows/keepalive.yml`, repository variable `API_URL` |

The API limits each visitor to 10 questions an hour and the whole demo to 300 a day, so a public link can't use up the free LLM quota. Render's free service sleeps after 15 idle minutes, so the first question can take about a minute. Qdrant suspends free clusters unused for a week; the keep-alive workflow queries the store every three days without calling the LLM.
