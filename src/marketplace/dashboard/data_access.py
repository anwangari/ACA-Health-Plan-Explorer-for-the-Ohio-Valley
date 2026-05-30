"""
data_access.py
==============
The ONLY module in the dashboard that touches data. Everything here returns a
pandas DataFrame ready for plotting; layouts and callbacks stay presentation-only.

It reads from PostgreSQL when DATABASE_URL is set, and otherwise falls back to
the tidy Parquet files so the dashboard is demoable without a live database.
Table objects are imported from db.schema — never redefined here.
"""

import pandas as pd
from sqlalchemy import create_engine, select

from marketplace import config
from marketplace.logging_setup import get_logger
from marketplace.db.schema import (
    counties, query_profiles, plans, plan_benefits, premium_quotes,
)

log = get_logger("dashboard.data")


def _use_db():
    return bool(config.DATABASE_URL)


def _engine():
    return create_engine(config.DATABASE_URL)


def _parquet(name):
    return pd.read_parquet(config.TIDY_DIR / f"{name}.parquet")


def _read_table(name, table):
    """Read a whole table, from the DB if configured else from Parquet."""
    if _use_db():
        with _engine().connect() as conn:
            return pd.read_sql(select(table), conn)
    return _parquet(name)


# ---------------------------------------------------------------------------
# Lookups for filter controls
# ---------------------------------------------------------------------------

def list_profiles():
    """profile_id + a human label for the profile dropdown."""
    df = _read_table("query_profiles", query_profiles)
    if df.empty:
        return df
    df["label"] = df.apply(
        lambda r: f"Age {r['age']}, {int(r['fpl_percent'])}% FPL ({r['gender']})",
        axis=1,
    )
    return df[["profile_id", "label"]]


def list_metal_levels():
    df = _read_table("plans", plans)
    if df.empty:
        return []
    return sorted(df["metal_level"].dropna().unique().tolist())


# ---------------------------------------------------------------------------
# View 1: premium choropleth — median premium per county for a given profile
# ---------------------------------------------------------------------------

def premium_by_county(profile_id):
    quotes = _read_table("premium_quotes", premium_quotes)
    geo = _read_table("counties", counties)
    if quotes.empty:
        return quotes

    q = quotes[quotes["profile_id"] == profile_id]
    agg = (
        q.groupby("county_fips")["monthly_premium"]
        .median()
        .reset_index(name="median_premium")
    )
    return agg.merge(geo, on="county_fips", how="left")


# ---------------------------------------------------------------------------
# View 2: metal-level distribution for a given profile
# ---------------------------------------------------------------------------

def metal_distribution(profile_id):
    quotes = _read_table("premium_quotes", premium_quotes)
    plan_df = _read_table("plans", plans)
    if quotes.empty or plan_df.empty:
        return pd.DataFrame(columns=["metal_level", "plan_count", "median_premium"])

    q = quotes[quotes["profile_id"] == profile_id]
    merged = q.merge(plan_df[["plan_id", "metal_level"]], on="plan_id", how="left")
    return (
        merged.groupby("metal_level")
        .agg(plan_count=("plan_id", "nunique"),
             median_premium=("monthly_premium", "median"))
        .reset_index()
    )


# ---------------------------------------------------------------------------
# View 3: side-by-side plan comparison
# ---------------------------------------------------------------------------

def plan_comparison(profile_id, county_fips, metal_levels=None):
    quotes = _read_table("premium_quotes", premium_quotes)
    plan_df = _read_table("plans", plans)
    benefits = _read_table("plan_benefits", plan_benefits)
    if quotes.empty:
        return quotes

    q = quotes[(quotes["profile_id"] == profile_id) &
               (quotes["county_fips"] == county_fips)]
    out = (
        q.merge(plan_df, on="plan_id", how="left")
        .merge(benefits, on="plan_id", how="left")
    )
    if metal_levels:
        out = out[out["metal_level"].isin(metal_levels)]
    cols = [
        "plan_name", "metal_level", "plan_type", "monthly_premium",
        "premium_after_credit", "deductible_individual", "moop_individual",
        "primary_care_copay", "generic_drug_copay",
    ]
    cols = [c for c in cols if c in out.columns]
    return out[cols].sort_values("monthly_premium")
