# FilingsQA: cited answers from SEC 10-K filings, measured on a public benchmark

> Status: **week 1 of 7** — data pipeline and eval set. Results land in week 2.

[Demo video — coming week 7] · [Live app — coming week 2] · [Blog post — coming week 7]

## Results

| Config | Retrieval recall@5 | Numeric accuracy | Wrong-answer rate | Abstention rate | p95 latency | Cost / 1k questions |
| --- | --- | --- | --- | --- | --- | --- |
| Baseline (week 2) | – | – | – | – | – | – |

Eval set: FinanceBench open set (150) + XBRL-derived numeric questions + hand-written questions.
Every number in this table is generated from `evals/results/`, never typed by hand.

## What I learned

*Filled in from `docs/experiments.md` as experiments run.*

## Data

See [DATA.md](DATA.md) for every source, its license and how to rebuild it.

## What didn't work

See [docs/experiments.md](docs/experiments.md).

## Run it locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env             # then put your name and email in SEC_USER_AGENT
pytest -q                        # offline tests
filingsqa-download --per-company 2
filingsqa-xbrl-questions
```
