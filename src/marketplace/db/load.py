"""
load.py
=======
Reads the tidy Parquet tables and loads them into a relational database
(PostgreSQL in production) using SQLAlchemy. Loads are idempotent: rerun as
many times as you like and row counts stay stable (upsert on conflict).
"""

import datetime as dt

import pandas as pd
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from marketplace import config
from marketplace.logging_setup import get_logger
from marketplace.db.schema import (
    metadata, LOAD_PLAN, STRING_KEYS, plan_benefits,
)

log = get_logger("load")


def _prepare(df, table):
    """Align a DataFrame to the table's columns, coerce key dtypes, NaN -> None."""
    df = df.copy()

    # Force ID/FIPS columns to clean strings (e.g. 18043, not 18043.0)
    for col in df.columns:
        if col in STRING_KEYS:
            df[col] = (
                df[col].astype("string").str.replace(r"\.0$", "", regex=True)
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


def main(database_url=None, tidy_dir=None):
    database_url = database_url or config.DATABASE_URL
    tidy_dir = tidy_dir or config.TIDY_DIR
    if not database_url:
        raise RuntimeError("No DATABASE_URL set. Add it to your .env file.")

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


if __name__ == "__main__":
    main()
