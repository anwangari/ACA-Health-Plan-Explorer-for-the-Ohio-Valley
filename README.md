# Marketplace Lens — ACA Health Plan Explorer for the Ohio Valley

An end-to-end data engineering pipeline that pulls individual health-insurance
plan data from the **CMS Marketplace API**, loads it into a normalized
**PostgreSQL** database, validates it, and (Week 4) serves it through an
interactive **Dash** dashboard. Built for MSBA 692 — Pipelines to Insights.

The project answers one question: **how does the cost of the same coverage vary
across counties in the Ohio Valley region?**

## Scope

Covers HealthCare.gov states **Indiana, Ohio, Tennessee, and West Virginia**.
Kentucky (kynect) and Virginia run their own state exchanges and are not served
by the federal API, so they are intentionally excluded.

## Tech stack

Python (requests, pandas, SQLAlchemy) · PostgreSQL · Parquet · Dash/Plotly · GitHub

## Pipeline

```
CMS Marketplace API
   └─ extract.py     pull plans per county × household profile → raw_cache/*.json
        └─ transform.py   flatten JSON → tidy/*.parquet (6 tables)
             └─ load.py        upsert Parquet → PostgreSQL (idempotent)
                  └─ validate.py    run data-quality checks → tidy/validation_results.parquet
```

| File | Role |
|------|------|
| `extract.py` | Calls the API with pagination; caches raw JSON. |
| `transform.py` | Flattens responses into 6 tidy Parquet tables. |
| `load.py` | Builds the schema, loads Parquet → Postgres, **and orchestrates the full run.** |
| `validate.py` | Data Quality & Validation Framework (19 checks, incl. API-vs-DB reconciliation). |

## Setup

```bash
# 1. Install dependencies
pip install requests pandas pyarrow sqlalchemy psycopg2-binary dotenv

# 2. Get a free API key: https://developer.cms.gov/marketplace-api/key-request.html
export MARKETPLACE_API_KEY="your_key_here"

# 3. Point at your PostgreSQL instance
export DATABASE_URL="postgresql+psycopg2://user:password@localhost:5432/marketplace"
```

## Run

```bash
python load.py               # full pipeline: extract → transform → load → validate
python load.py --no-extract  # reuse cached JSON (fast reruns, skips the API pull)
```

Each stage can also run on its own: `python extract.py`, `python transform.py`,
`python validate.py`. The run is **idempotent** — running it five times leaves
the database in the same state.

## Data model

Six tables, normalized to third normal form. `premium_quotes` is the fact table
at the center (grain: one row per plan × county × profile); `counties`,
`query_profiles`, `issuers`, `plans`, and `plan_benefits` describe it. Foreign
keys are enforced in PostgreSQL. 

## ER Diagram
![ER Diagram from postgres](docs/erd.png)

## Validation

`validate.py` checks completeness, value ranges, referential integrity, and
benefit-field coverage. Its headline check reconciles plans loaded in the DB
against the `total` each API response reported — this catches silent pagination
truncation. The run fails (exit code 1) on any ERROR-level check.

## Next steps

- [ ] Build Dash application (Week 4): premium maps, metal-level distributions, side-by-side plan comparison.
- [ ] Embed the exported ER and architecture diagrams in `docs/`.
- [ ] Expand `TARGET_ZIPS` for broader county coverage.
- [ ] (Stretch) Year-over-year premium comparison using the API's multi-year retention.

## Repository layout

```
.
├── extract.py
├── transform.py
├── load.py
├── validate.py
├── raw_cache/          # cached API responses (generated)
├── tidy/               # Parquet tables + validation results (generated)
└── docs/               # proposal, schema writeup, diagrams
```