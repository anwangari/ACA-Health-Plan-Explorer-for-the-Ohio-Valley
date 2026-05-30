# CLAUDE.md

Guidance for working in this repository.

## What this is

**Marketplace Lens** — an end-to-end ETL pipeline + dashboard that pulls
individual ACA health-plan data from the **CMS Marketplace API**, normalizes it
into **PostgreSQL**, validates it, and serves it through an interactive **Dash**
app. Built for MSBA 692 ("Pipelines to Insights").

It answers one question: **how does the cost of the same coverage vary across
counties in the Ohio Valley region?**

Scope: HealthCare.gov states **Indiana, Ohio, Tennessee, West Virginia**.
Kentucky (kynect) and Virginia run their own exchanges and are excluded — the
federal API does not serve them.

## Pipeline

```
CMS Marketplace API
  └─ extract     pull plans per county × household profile → data/raw_cache/*.json
       └─ transform   flatten JSON → data/tidy/*.parquet (6 tables)
            └─ load    upsert Parquet → PostgreSQL (idempotent)
                 └─ validate   data-quality checks → data/tidy/validation_results.parquet
                      └─ dashboard   serve the loaded data via Dash/Plotly
```

The pipeline is **idempotent** — running it repeatedly leaves the database in
the same state (upsert on conflict against natural/composite keys).

## Target module structure

The codebase is being restructured from flat top-level scripts into a package.
This is the target layout:

```
marketplace-lens/
├── requirements.txt              # pinned dependencies
├── .env                          # secrets (gitignored): MARKETPLACE_API, DATABASE_URL
├── .env.example                  # checked-in template
├── README.md
├── CLAUDE.md
├── docs/
│   └── erd.png
│
├── src/marketplace/
│   ├── __init__.py
│   ├── config.py                 # SINGLE source of truth: paths, env vars, profiles, constants
│   ├── logging_setup.py          # shared logging.basicConfig boilerplate
│   │
│   ├── extract/
│   │   ├── api_client.py         # _request(): retry/backoff, rate limiting
│   │   └── plans.py              # get_counties_for_zip(), search_plans(), extract main()
│   │
│   ├── transform/
│   │   ├── helpers.py            # _first_amount(), _benefit_copay()
│   │   └── tables.py             # load_counties(), build_tables(), transform main()
│   │
│   ├── db/
│   │   ├── schema.py             # 6 SQLAlchemy Table defs + LOAD_PLAN (single source of truth)
│   │   └── load.py               # _prepare(), _upsert(), load main()
│   │
│   ├── validate/
│   │   ├── checks.py             # 8 check_* functions + Results class
│   │   └── runner.py             # validate main()
│   │
│   ├── dashboard/                # APPLICATION LAYER (Dash/Plotly)
│   │   ├── app.py                # Dash app instance, server, layout assembly, entry point
│   │   ├── data_access.py        # read-only queries against Postgres (or tidy/ Parquet fallback)
│   │   ├── layouts.py            # page layout + reusable components
│   │   └── callbacks.py          # interactivity (filters, dropdowns, cross-filtering)
│   │
│   └── pipeline.py               # run_pipeline() orchestration (extract→transform→load→validate)
│
├── cli.py / __main__.py          # `python -m marketplace ...` entry point
│
├── data/                         # generated artifacts (gitignore the bulky bits)
│   ├── raw_cache/                # cached API responses
│   └── tidy/                     # Parquet tables + validation_results.parquet
│
└── tests/
    └── test_smoke.py             # was simple-tests.py
```

### Dashboard layer notes

- `data_access.py` is the **only** module in `dashboard/` that talks to the
  database. It imports table objects from `db/schema.py` — never redefines them.
  Keep all SQL here so layouts/callbacks stay presentation-only.
- Planned views (per the project goal): county-level **premium choropleth map**,
  **metal-level distribution**, and **side-by-side plan comparison**.
- The app should degrade to reading `data/tidy/*.parquet` if `DATABASE_URL` is
  unset, so the dashboard is demoable without a live Postgres.

## requirements.txt

Pin these (pipeline + dashboard). Versions are illustrative — pin to whatever
is installed and tested:

```
requests
pandas
pyarrow
sqlalchemy
psycopg2-binary
python-dotenv
dash
plotly
```

## Commands

```bash
# install
pip install -r requirements.txt

# full pipeline (fresh API pull → transform → load → validate)
python -m marketplace

# reuse cached JSON, skip the API pull (fast reruns)
python -m marketplace --no-extract

# single stages
python -m marketplace extract
python -m marketplace transform
python -m marketplace load
python -m marketplace validate

# launch the dashboard
python -m marketplace dashboard      # or: python src/marketplace/dashboard/app.py

# tests
python -m pytest tests/
```

## Conventions & gotchas

- **`config.py` is the single source of truth.** `HOUSEHOLD_PROFILES`, cache/tidy
  paths, `BASE_URL`/`PLAN_YEAR`/`MARKET`/`TARGET_ZIPS`, and validation thresholds
  all live there. Do **not** redefine them per-module (the pre-restructure code
  duplicated `HOUSEHOLD_PROFILES` in two files and kept them in sync by hand —
  don't reintroduce that).
- **`db/schema.py` is the single source of truth for the schema.** `load.py`,
  `validate/checks.py`, and `dashboard/data_access.py` all import the Table
  objects from it.
- **Env var name:** the API key is read as `MARKETPLACE_API` (note: not
  `MARKETPLACE_API_KEY`). The DB URL is `DATABASE_URL`
  (`postgresql+psycopg2://user:pass@host:5432/marketplace`). Both load from
  `.env` via `python-dotenv`, centralized in `config.py`.
- **Data model:** 6 tables in 3NF. `premium_quotes` is the fact table with a
  **composite PK** `(plan_id, county_fips, profile_id)` — this is what makes
  reruns idempotent. `counties`, `query_profiles`, `issuers`, `plans`,
  `plan_benefits` describe it. FKs are enforced (and PRAGMA-enabled on SQLite).
- **Validation severity:** `ERROR`-level check failure fails the run (exit 1);
  `WARN` does not. The headline check is **reconciliation** — DB plan counts vs.
  the `total` each API response reported, which catches silent pagination
  truncation.
- **Generated data** (`data/raw_cache/`, `data/tidy/`) is reproducible from the
  pipeline; treat it as disposable.
