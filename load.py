"""
load.py
=======
Load layer for the ACA Marketplace project.

Reads the tidy Parquet tables produced by transform.py and loads them into a
relational database (PostgreSQL in production) using SQLAlchemy. The schema
declares real primary keys and foreign keys, and loads are idempotent: rerun
it as many times as you like and row counts stay stable (upsert on conflict).

Load order respects foreign keys:
  counties, query_profiles, issuers   (no parents)
    -> plans                          (FK -> issuers)
      -> plan_benefits                (FK -> plans)
      -> premium_quotes               (FK -> plans, counties, query_profiles)

Requirements:
  pip install pandas pyarrow sqlalchemy psycopg2-binary

Configure the connection (PostgreSQL):
  export DATABASE_URL="postgresql+psycopg2://user:password@localhost:5432/marketplace"

Run:
  python load.py
"""

import os
import logging
import datetime as dt
from pathlib import Path
from dotenv import load_dotenv

import pandas as pd
from sqlalchemy import (
    create_engine, MetaData, Table, Column, String, Integer, Float, Boolean,
    DateTime, ForeignKey, event, func, select
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

load_dotenv() # Loading environment variables

TIDY_DIR = Path("tidy")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("load")

# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------
# Design notes:
#  - county_fips, issuer_id, plan_id, profile_id are natural keys from the API.
#  - plan_benefits uses plan_id as its PK (one benefit row per plan).
#  - premium_quotes uses a COMPOSITE PK (plan_id, county_fips, profile_id):
#    that triple uniquely identifies a quote and makes reruns idempotent
#    without juggling a surrogate key. (If your ER diagram prefers a surrogate
#    quote_id, add it as an extra column with a UNIQUE constraint on the triple.)
#  - ingested_at on every table supports the data-quality/reproducibility story.

metadata = MetaData()

counties = Table(
    "counties", metadata,
    Column("county_fips", String(5), primary_key=True),
    Column("county_name", String(100)),
    Column("state", String(2)),
    Column("zipcode", String(10)),
    Column("ingested_at", DateTime),
)

query_profiles = Table(
    "query_profiles", metadata,
    Column("profile_id", String(40), primary_key=True),
    Column("age", Integer),
    Column("income", Integer),
    Column("fpl_percent", Integer),
    Column("uses_tobacco", Boolean),
    Column("gender", String(10)),
    Column("household_size", Integer),
    Column("ingested_at", DateTime),
)

issuers = Table(
    "issuers", metadata,
    Column("issuer_id", String(20), primary_key=True),
    Column("issuer_name", String(200)),
    Column("toll_free_number", String(40)),
    Column("website_url", String(400)),
    Column("ingested_at", DateTime),
)

plans = Table(
    "plans", metadata,
    Column("plan_id", String(20), primary_key=True),
    Column("issuer_id", String(20), ForeignKey("issuers.issuer_id")),
    Column("plan_name", String(300)),
    Column("metal_level", String(20)),
    Column("plan_type", String(20)),
    Column("design_type", String(40)),
    Column("hsa_eligible", Boolean),
    Column("plan_year", Integer),
    Column("ingested_at", DateTime),
)

plan_benefits = Table(
    "plan_benefits", metadata,
    Column("plan_id", String(20), ForeignKey("plans.plan_id"), primary_key=True),
    Column("deductible_individual", Float),
    Column("deductible_family", Float),
    Column("moop_individual", Float),
    Column("moop_family", Float),
    Column("primary_care_copay", String(120)),
    Column("specialist_copay", String(120)),
    Column("generic_drug_copay", String(120)),
    Column("emergency_room_cost", String(120)),
    Column("ingested_at", DateTime),
)

premium_quotes = Table(
    "premium_quotes", metadata,
    Column("plan_id", String(20), ForeignKey("plans.plan_id"), primary_key=True),
    Column("county_fips", String(5), ForeignKey("counties.county_fips"), primary_key=True),
    Column("profile_id", String(40), ForeignKey("query_profiles.profile_id"), primary_key=True),
    Column("monthly_premium", Float),
    Column("premium_after_credit", Float),
    Column("plan_year", Integer),
    Column("ingested_at", DateTime),
)

# Load order: parents first so foreign keys resolve.
LOAD_PLAN = [
    ("counties", counties, ["county_fips"]),
    ("query_profiles", query_profiles, ["profile_id"]),
    ("issuers", issuers, ["issuer_id"]),
    ("plans", plans, ["plan_id"]),
    ("plan_benefits", plan_benefits, ["plan_id"]),
    ("premium_quotes", premium_quotes, ["plan_id", "county_fips", "profile_id"]),
]

# Columns that must be loaded as strings (FIPS/IDs can look numeric).
STRING_KEYS = {"county_fips", "issuer_id", "plan_id", "zipcode", "profile_id"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prepare(df, table):
    """Align a DataFrame to the table's columns, coerce key dtypes, NaN -> None."""
    df = df.copy()

    # Force ID/FIPS columns to clean strings (e.g. 18043, not 18043.0)
    for col in df.columns:
        if col in STRING_KEYS:
            df[col] = (
                df[col].astype("string")
                .str.replace(r"\.0$", "", regex=True)
            )

    df["ingested_at"] = dt.datetime.now()

    # Keep only columns that exist on the table
    valid = {c.name for c in table.columns}
    df = df[[c for c in df.columns if c in valid]]

    # NaN -> None so the DB stores real NULLs
    df = df.astype(object).where(pd.notnull(df), None)
    return df.to_dict("records")


def _upsert(conn, table, rows, pk_cols):
    """Dialect-aware bulk upsert (PostgreSQL or SQLite)."""
    if not rows:
        return
    dialect = conn.dialect.name
    if dialect == "postgresql":
        stmt = pg_insert(table).values(rows)
    elif dialect == "sqlite":
        stmt = sqlite_insert(table).values(rows)
    else:
        conn.execute(table.insert().values(rows))
        return

    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in table.columns
        if c.name not in pk_cols
    }
    stmt = stmt.on_conflict_do_update(index_elements=pk_cols, set_=update_cols)
    conn.execute(stmt)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(database_url=DATABASE_URL, tidy_dir=TIDY_DIR):
    log.info("Connecting to %s", database_url.split("@")[-1])
    engine = create_engine(database_url)

    # Enforce foreign keys on SQLite (PostgreSQL does this by default).
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)
    log.info("Schema ready (6 tables).")

    with engine.begin() as conn:
        for name, table, pk_cols in LOAD_PLAN:
            path = tidy_dir / f"{name}.parquet"
            if not path.exists():
                log.warning("Missing %s — skipping.", path.name)
                continue
            df = pd.read_parquet(path)
            rows = _prepare(df, table)
            _upsert(conn, table, rows, pk_cols)
            log.info("Loaded %-15s %5d rows", name, len(rows))

    # Post-load report (doubles as a lightweight validation signal).
    with engine.connect() as conn:
        log.info("---- post-load row counts ----")
        for name, table, _ in LOAD_PLAN:
            n = conn.execute(select(func.count()).select_from(table)).scalar()
            log.info("  %-15s %5d", name, n)

        # Surface benefit completeness right here so data gaps are visible.
        nulls = conn.execute(select(
            func.count().filter(plan_benefits.c.deductible_individual.is_(None)),
            func.count().filter(plan_benefits.c.moop_individual.is_(None)),
            func.count().filter(plan_benefits.c.primary_care_copay.is_(None)),
        )).one()
        log.info("---- benefit null check (plan_benefits) ----")
        log.info("  deductible_individual NULLs: %d", nulls[0])
        log.info("  moop_individual NULLs:       %d", nulls[1])
        log.info("  primary_care_copay NULLs:    %d", nulls[2])

    log.info("Load complete.")


def run_pipeline(skip_extract=False):
    """
    End-to-end orchestration: API -> Parquet -> DB -> validation.
    Imports the other stages and runs them in order. Because extract.py and
    transform.py guard their own main() behind __name__ == '__main__', importing
    them here has no side effects until we explicitly call their main().
    """
    import extract
    import transform
    import validate

    if not skip_extract:
        log.info("STEP 1/4  Extracting from API ...")
        extract.main()
    else:
        log.info("STEP 1/4  Skipping extract (using existing raw_cache).")

    log.info("STEP 2/4  Transforming raw JSON -> Parquet ...")
    transform.main()

    log.info("STEP 3/4  Loading Parquet -> database ...")
    main()

    log.info("STEP 4/4  Running data-quality validation ...")
    ok = validate.main()
    if not ok:
        log.error("Pipeline finished but validation FAILED. Review results above.")
        return False
    log.info("Pipeline complete and validated.")
    return True


if __name__ == "__main__":
    import sys
    # `python load.py`            -> full pipeline including a fresh API pull
    # `python load.py --no-extract`-> reuse cached JSON (faster reruns)
    skip = "--no-extract" in sys.argv
    success = run_pipeline(skip_extract=skip)
    sys.exit(0 if success else 1)