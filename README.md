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
   └─ extract     pull plans per county × household profile → data/raw_cache/*.json
        └─ transform   flatten JSON → data/tidy/*.parquet (6 tables)
             └─ load        upsert Parquet → PostgreSQL (idempotent)
                  └─ validate    run data-quality checks → data/tidy/validation_results.parquet
                       └─ dashboard   serve the loaded data via Dash/Plotly
```

| Stage | Module | Role |
|-------|--------|------|
| extract | `src/marketplace/extract/` | Calls the API with pagination; caches raw JSON. |
| transform | `src/marketplace/transform/` | Flattens responses into 6 tidy Parquet tables. |
| load | `src/marketplace/db/` | Builds the schema and loads Parquet → Postgres (idempotent upserts). |
| validate | `src/marketplace/validate/` | Data Quality & Validation Framework (8 checks, incl. API-vs-DB reconciliation). |
| dashboard | `src/marketplace/dashboard/` | Interactive Dash/Plotly app over the loaded data. |

Orchestration lives in `src/marketplace/pipeline.py`, which runs
extract → transform → load → validate in order.

## Setup

```bash
# 1. Install the package and its dependencies (editable install)
pip install -e .

# 2. Get a free API key: https://developer.cms.gov/marketplace-api/key-request.html
#    Copy .env.example to .env and fill in your values.
cp .env.example .env
```

Your `.env` needs two values:

```
# API key — note the env var is MARKETPLACE_API (not MARKETPLACE_API_KEY)
MARKETPLACE_API=your_key_here

# PostgreSQL connection. Leave unset to run the dashboard off the tidy Parquet
# files instead of a live database.
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/marketplace
```

Both are loaded from `.env` automatically via `python-dotenv` (centralized in
`config.py`).

## Run

```bash
# full pipeline: extract → transform → load → validate
python -m marketplace

# reuse cached JSON (fast reruns, skips the API pull)
python -m marketplace --no-extract
```

Each stage can also run on its own:

```bash
python -m marketplace extract
python -m marketplace transform
python -m marketplace load
python -m marketplace validate
```

The run is **idempotent** — running it five times leaves the database in the
same state (upsert on conflict against natural/composite keys).

To launch the Dash dashboard:

```bash
python -m marketplace dashboard      # or: python src/marketplace/dashboard/app.py
```

See **[Running the Dashboard Server](docs/dashboard.md)** for start/stop details.

## Data model

Six tables, normalized to third normal form. `premium_quotes` is the fact table
at the center (grain: one row per plan × county × profile); `counties`,
`query_profiles`, `issuers`, `plans`, and `plan_benefits` describe it. Foreign
keys are enforced in PostgreSQL.

## ER Diagram
![ER Diagram from postgres](docs/erd.png)

## Validation

The validation framework checks completeness, value ranges, referential
integrity, and benefit-field coverage. Its headline check reconciles plans
loaded in the DB against the `total` each API response reported — this catches
silent pagination truncation. The run fails (exit code 1) on any ERROR-level
check; WARN-level checks flag issues without failing the run.

## Next steps

- [ ] Build Dash application (Week 4): premium maps, metal-level distributions, side-by-side plan comparison.
- [ ] Embed the exported ER and architecture diagrams in `docs/`.
- [ ] Expand `TARGET_ZIPS` for broader county coverage.
- [ ] (Stretch) Year-over-year premium comparison using the API's multi-year retention.

## Repository layout

```
marketplace-lens/
├── pyproject.toml
├── requirements.txt
├── .env.example
├── README.md
├── docs/
│   ├── dashboard.md
│   └── erd.png
├── src/marketplace/
│   ├── config.py              # single source of truth: paths, env vars, profiles, constants
│   ├── logging_setup.py
│   ├── pipeline.py            # end-to-end orchestration
│   ├── __main__.py            # python -m marketplace entry point
│   ├── extract/               # api_client.py, plans.py
│   ├── transform/             # helpers.py, tables.py
│   ├── db/                    # schema.py, load.py
│   ├── validate/              # checks.py, runner.py
│   └── dashboard/             # app.py, data_access.py, layouts.py, callbacks.py
├── data/                      # generated artifacts (gitignored)
│   ├── raw_cache/             # cached API responses
│   └── tidy/                  # Parquet tables + validation_results.parquet
└── tests/
    └── test_smoke.py
```