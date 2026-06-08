"""
data_access.py
==============
The ONLY module in the dashboard that touches data. Everything here returns a
pandas DataFrame (or a small dict/scalar for KPIs) ready for presentation;
layouts and callbacks stay presentation-only.

It reads from PostgreSQL when DATABASE_URL is set, and otherwise falls back to
the tidy Parquet files so the dashboard is demoable without a live database.
Table objects are imported from db.schema -- never redefined here.

The dashboard lets a user dial in an age and income band; rather than hitting
the API live, we snap that request to the NEAREST profile already stored in the
database (see nearest_profile_id). This keeps the dashboard strictly read-only
against the loaded data.
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
# Profile grid: bounds for the input controls + snap-to-nearest lookup
# ---------------------------------------------------------------------------

def profile_grid():
    """The stored profiles as a DataFrame (age, fpl_percent, income, id)."""
    df = _read_table("query_profiles", query_profiles)
    return df


def profile_bounds():
    """Min/max age and the available FPL bands, to configure the controls."""
    df = profile_grid()
    if df.empty:
        return {"age_min": 25, "age_max": 64, "fpl_bands": [150, 250, 400]}
    return {
        "age_min": int(df["age"].min()),
        "age_max": int(df["age"].max()),
        "fpl_bands": sorted(df["fpl_percent"].dropna().unique().astype(int).tolist()),
    }


def nearest_profile_id(age, fpl_percent):
    """
    Map a user-requested (age, fpl) to the closest stored profile_id.

    Age and FPL live on different scales, so we normalize each by its grid
    span before measuring distance -- otherwise income (hundreds of %) would
    swamp age (tens of years). Returns (profile_id, snapped_row_as_dict).
    """
    df = profile_grid()
    if df.empty:
        return None, {}

    age_span = max(df["age"].max() - df["age"].min(), 1)
    fpl_span = max(df["fpl_percent"].max() - df["fpl_percent"].min(), 1)

    d = (((df["age"] - age) / age_span) ** 2 +
         ((df["fpl_percent"] - fpl_percent) / fpl_span) ** 2)
    row = df.loc[d.idxmin()]
    return row["profile_id"], row.to_dict()


def profile_label(row):
    """Human label for a snapped profile row (dict)."""
    if not row:
        return ""
    return (f"Age {int(row['age'])}, "
            f"{int(row['fpl_percent'])}% FPL "
            f"(~${int(row['income']):,}/yr)")


# ---------------------------------------------------------------------------
# Lookups for filter controls
# ---------------------------------------------------------------------------

def list_metal_levels():
    df = _read_table("plans", plans)
    if df.empty:
        return []
    return sorted(df["metal_level"].dropna().unique().tolist())


# ---------------------------------------------------------------------------
# KPI summary metrics (react to selected profile + optional county)
# ---------------------------------------------------------------------------

def kpi_summary(profile_id, county_fips=None):
    """
    Headline numbers for the metric cards. Scoped to a profile, and to a single
    county when one is selected (else the whole region).

    Returns a dict of display-ready strings so the cards stay presentation-only.
    """
    quotes = _read_table("premium_quotes", premium_quotes)
    plan_df = _read_table("plans", plans)
    blank = {"plans": "--", "median": "--", "cheapest_silver": "--", "issuers": "--"}
    if quotes.empty or plan_df.empty:
        return blank

    q = quotes[quotes["profile_id"] == profile_id]
    if county_fips:
        q = q[q["county_fips"] == county_fips]
    if q.empty:
        return blank

    merged = q.merge(
        plan_df[["plan_id", "metal_level", "issuer_id"]], on="plan_id", how="left"
    )

    n_plans = merged["plan_id"].nunique()
    median_prem = merged["monthly_premium"].median()
    n_issuers = merged["issuer_id"].nunique()

    silver = merged[merged["metal_level"] == "Silver"]
    cheapest_silver = silver["monthly_premium"].min() if not silver.empty else None

    return {
        "plans": f"{n_plans:,}",
        "median": f"${median_prem:,.0f}" if pd.notnull(median_prem) else "--",
        "cheapest_silver": (f"${cheapest_silver:,.0f}"
                            if cheapest_silver is not None and pd.notnull(cheapest_silver)
                            else "--"),
        "issuers": f"{n_issuers:,}",
    }


# ---------------------------------------------------------------------------
# View 1: median premium per county for a given profile
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