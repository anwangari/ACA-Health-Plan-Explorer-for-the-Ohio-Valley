# ACA Health Plan Explorer for the Ohio Valley

**An ACA health-plan price explorer for the Ohio Valley — built as a complete, reproducible data engineering pipeline.**

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-relational-336791)
![Dash](https://img.shields.io/badge/Dash-Plotly-1f77b4)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red)

Marketplace Lens pulls individual health-insurance plan data from the federal
**CMS Marketplace API**, normalizes it into a **PostgreSQL** database, validates
it against a documented set of data-quality checks, and serves it through an
interactive **Dash** dashboard.

It exists to answer one concrete question:

> **How does the cost of the same coverage vary from county to county across the Ohio Valley?**

The identical plan is priced differently depending on where you live and who is
shopping. Marketplace Lens makes that variation visible — and, just as
importantly, makes the data behind it trustworthy and reproducible.

---

## Key Technical Challenges

A few problems had to be solved for the numbers to be correct rather than just
present:

- **Silent pagination truncation.** The CMS API returns only 10 plans per
  county by default, sorted cheapest-first. Taken at face value, this skewed the
  data toward Bronze plans (~88% in early runs) and produced a completely
  unrepresentative market. The extractor pages through the full reported `total`
  for every query, and a headline validation check reconciles loaded plan counts
  against that `total` to guarantee nothing was dropped between the API and the
  database.

- **Scoping to what the federal API actually serves.** Kentucky (kynect) and
  Virginia run their own state exchanges and aren't available through the federal
  API. They're deliberately excluded; the project covers the four HealthCare.gov
  states in the region — **Indiana, Ohio, Tennessee, and West Virginia**.

- **Keeping prices honest across geography.** Premiums genuinely differ by
  county *and* by shopper, so they can't live on the plan record. They sit in a
  fact table keyed by (plan × county × household profile), which is what lets the
  dashboard compare like-for-like coverage across the region.

- **Duplicate county names across states.** "Hamilton County" exists in both
  Ohio and Tennessee with different FIPS codes and different plan markets. The
  dashboard disambiguates every county by appending its state, so distinct
  markets never collapse onto one label.

- **Reproducibility.** The entire pipeline is idempotent — running it once or
  five times leaves the database in exactly the same state, via upserts on
  natural and composite keys.

---

## Architecture

```
CMS Marketplace API
   └─ extract     pull plans per county × household profile → data/raw_cache/*.json
        └─ transform   flatten nested JSON → data/tidy/*.parquet (6 tables)
             └─ load        upsert Parquet → PostgreSQL (idempotent)
                  └─ validate    8 data-quality checks → validation_results.parquet
                       └─ dashboard   interactive Dash/Plotly app over the loaded data
```

Each stage is an importable module with a single responsibility;
`pipeline.py` orchestrates them end to end, and the whole run is driven from one
command.

| Stage | Module | What it does |
|-------|--------|--------------|
| Extract | `extract/` | Calls the API with retry/backoff, rate limiting, and full pagination; caches raw JSON. |
| Transform | `transform/` | Flattens deeply nested responses into 6 tidy Parquet tables. |
| Load | `db/` | Defines the schema and upserts Parquet → Postgres (idempotent). |
| Validate | `validate/` | 8 data-quality checks, including API-vs-DB reconciliation. |
| Dashboard | `dashboard/` | Dash app: profile builder, KPI cards, four charts, plan comparison. |

---

## Data model

Six tables in third normal form, with foreign keys enforced in PostgreSQL.
`premium_quotes` is the fact table at the center (grain: one row per plan ×
county × household profile); `counties`, `query_profiles`, `issuers`, `plans`,
and `plan_benefits` describe it.

![ER diagram](docs/erd.png)

Splitting fixed plan attributes from county/shopper-dependent prices keeps every
fact in exactly one place and is what makes the reconciliation and referential-
integrity checks meaningful.

---

## Dashboard

The Dash app is a single-page, interactive explorer for ACA plan costs across
the Ohio Valley, built on `dash-bootstrap-components`. It reads from PostgreSQL,
falling back to the tidy Parquet files when no database is configured — so it is
fully demoable without a live database.

### What you can do

- **Build a shopper profile.** Set an age (slider) and income as a percentage of
  the federal poverty level (dropdown). The app maps your input to the closest
  pre-computed profile in the database and shows which one it used, so every
  number on screen is a real stored quote rather than a live estimate.
- **Pick a county** to focus every view on one market, or leave it to compare
  across the region.
- **Filter by metal level** (Bronze, Silver, Gold, Platinum) to narrow the plan
  table.

### What it shows

- **Four summary cards** — plans available, median monthly premium, cheapest
  Silver premium, and number of issuers — all reacting to the selected profile
  and county.
- **Median premium by county** — a ranked bar chart making geographic price
  variation immediately visible, with each county disambiguated by state.
- **Plans available by metal level** — the metal-tier mix for the selected
  profile.
- **Full vs. after-credit premium** — a grouped bar showing how much the advance
  premium tax credit buys down the sticker price at each metal level.
- **Comparison by issuer** — how many plans each insurer offers and their median
  premium, so you can see which carriers compete in a given market.
- **Plan comparison table** — every plan for the chosen profile and county side
  by side (premium, after-credit premium, deductible, max out-of-pocket, key
  copays), sortable in-browser.

### Business insights this surfaces

- **The same coverage is not the same price.** Median premiums for an identical
  shopper swing substantially across the region — Indiana and Ohio counties
  cluster cheapest, Tennessee in the middle, and West Virginia counties most
  expensive — the core finding the project was built to expose.
- **Subsidies reshape affordability.** Comparing full vs. after-credit premiums
  shows that sticker prices overstate what most shoppers actually pay; the gap
  widens sharply at lower incomes.
- **Age dominates the sticker price.** Because ACA rates are age-banded, the
  oldest profiles see full premiums several times higher than the youngest —
  visible by sliding age and watching the cards and county chart move.
- **Market competition varies by issuer.** Some counties are served by only a
  couple of carriers, which the issuer view makes plain.

### Running it

```bash
python -m marketplace dashboard
```

Then open **http://127.0.0.1:8050**. See **[docs/dashboard.md](docs/dashboard.md)**
for a full usage walkthrough and instructions on stopping the server.

### Screenshots

<!-- Replace these placeholders with real captures before submitting. -->

![Dashboard overview](docs/img/dashboard_overview.png)
*Single-page layout: profile controls, summary cards, and the four charts.*

![Full vs after-credit](docs/img/dashboard_credit.png)
*The premium tax credit's effect on monthly cost, by metal level.*

---

## Engineering decisions worth calling out

- **Single source of truth.** Paths, secrets, household profiles, API settings,
  and validation thresholds all live in `config.py`. The household profiles are
  generated as a grid (ages × income bands), so widening coverage is a one-line
  change. The schema lives once in `db/schema.py` and is imported everywhere
  (load, validation, dashboard) rather than redefined.
- **The dashboard never calls the API.** It reads pre-computed quotes for the
  loaded profile grid and snaps user input to the nearest one, so it stays
  strictly read-only against the database and can't fail on a live API call
  during a demo.
- **Validation as a gate, not a report.** ERROR-level failures exit non-zero and
  fail the run; WARN-level issues are surfaced without blocking. Results are
  written to Parquet for an auditable history.
- **Graceful degradation.** The dashboard reads from PostgreSQL when configured
  and falls back to the tidy Parquet files when it isn't — so it's demoable
  without a live database.

---

## Quick start

```bash
# 1. Install the package and dependencies
pip install -e .

# 2. Configure secrets
cp .env.example .env
#    Then edit .env:
#    MARKETPLACE_API=your_key_here          (free key: https://developer.cms.gov/marketplace-api/key-request.html)
#    DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/marketplace

# 3. Run the full pipeline (extract → transform → load → validate)
python -m marketplace

# Reuse cached API responses for fast reruns
python -m marketplace --no-extract

# Launch the dashboard
python -m marketplace dashboard
```

Individual stages run on their own too:
`python -m marketplace {extract|transform|load|validate}`.

See **[docs/dashboard.md](docs/dashboard.md)** for running and stopping the
dashboard server.

---

## Project status

| Component | Status |
|-----------|--------|
| Extract / transform / load pipeline | ✅ Complete, verified against live API |
| PostgreSQL schema + ER diagram | ✅ Complete |
| Data-quality validation framework | ✅ Complete (8 checks) |
| Dash dashboard | ✅ Complete (MVP) — profile builder, 4 KPI cards, 4 charts, sortable plan table |
| County choropleth (FIPS + GeoJSON) | 💭 Planned — ranked bar conveys the same geographic comparison for now |
| Year-over-year premium comparison | 💭 Planned (stretch) |

---

## Tech stack

Python (requests · pandas · SQLAlchemy) · PostgreSQL · Parquet · Dash / Plotly · dash-bootstrap-components · GitHub

## Repository layout

```
marketplace-lens/
├── pyproject.toml · requirements.txt · .env.example · README.md
├── docs/                      # dashboard.md, erd.png, architecture diagram, img/
├── src/marketplace/
│   ├── config.py              # single source of truth (incl. generated profile grid)
│   ├── pipeline.py            # end-to-end orchestration
│   ├── __main__.py            # `python -m marketplace`
│   ├── extract/               # api_client.py, plans.py
│   ├── transform/             # helpers.py, tables.py
│   ├── db/                    # schema.py, load.py
│   ├── validate/              # checks.py, runner.py
│   └── dashboard/             # app.py, data_access.py, layouts.py, callbacks.py
├── data/                      # generated artifacts (gitignored)
│   ├── raw_cache/             # cached API responses
│   └── tidy/                  # Parquet tables + validation results
└── tests/test_smoke.py
```

---