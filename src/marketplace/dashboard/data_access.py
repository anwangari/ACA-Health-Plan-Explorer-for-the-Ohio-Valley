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
    counties, query_profiles, plans, plan_benefits, premium_quotes, issuers,
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


# Numeric columns that must never be treated as strings. Parquet/DB reads can
# occasionally hand back object dtype (e.g. when a column has mixed NULLs);
# coercing here guarantees medians, mins, and sorts are numeric everywhere.
_NUMERIC_COLS = {
    "monthly_premium", "premium_after_credit",
    "deductible_individual", "deductible_family",
    "moop_individual", "moop_family",
}


def _coerce_numeric(df):
    """Force known numeric columns to real numbers; bad values -> NaN."""
    for col in df.columns:
        if col in _NUMERIC_COLS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Profile grid: bounds for the input controls + snap-to-nearest lookup
# ---------------------------------------------------------------------------

def profile_grid():
    """The stored profiles as a DataFrame (age, fpl_percent, income, id)."""
    return _read_table("query_profiles", query_profiles)


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


def county_options(profile_id):
    """
    (value, label) pairs for the county dropdown, for a given profile.
    Label is disambiguated by state so same-named counties stay distinct.
    """
    df = premium_by_county(profile_id)
    if df.empty:
        return []
    df = df.sort_values("county_label")
    return [{"label": r["county_label"], "value": r["county_fips"]}
            for _, r in df.iterrows()]


# ---------------------------------------------------------------------------
# KPI summary metrics (react to selected profile + optional county)
# ---------------------------------------------------------------------------

def kpi_summary(profile_id, county_fips=None):
    """
    Headline numbers for the metric cards. Scoped to a profile, and to a single
    county when one is selected (else the whole region).

    Returns a dict of display-ready strings so the cards stay presentation-only.
    """
    blank = {"plans": "--", "median": "--", "cheapest_silver": "--",
             "cheapest_silver_credit": "--", "issuers": "--"}

    quotes = _coerce_numeric(_read_table("premium_quotes", premium_quotes))
    plan_df = _read_table("plans", plans)
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
    cheapest_silver_credit = (
        silver["premium_after_credit"].min() if not silver.empty else None
    )

    def money(v):
        return f"${v:,.0f}" if v is not None and pd.notnull(v) else "--"

    return {
        "plans": f"{n_plans:,}",
        "median": money(median_prem),
        "cheapest_silver": money(cheapest_silver),
        "cheapest_silver_credit": money(cheapest_silver_credit),
        "issuers": f"{n_issuers:,}",
    }


# ---------------------------------------------------------------------------
# View 1: median premium per county for a given profile
# ---------------------------------------------------------------------------

def premium_by_county(profile_id, metal_levels=None):
    """
    Median monthly premium per county for the given profile, optionally
    narrowed to a subset of metal levels.

    One row per county_fips. The display label appends the state so that
    same-named counties in different states (e.g. Hamilton County, OH vs TN)
    never collapse onto a single bar. The label is built to be non-null and
    unique even if a county_fips fails to match the geography table.
    """
    quotes = _coerce_numeric(_read_table("premium_quotes", premium_quotes))
    geo = _read_table("counties", counties)
    if quotes.empty:
        return quotes

    q = quotes[quotes["profile_id"] == profile_id]
    if metal_levels:
        plan_df = _read_table("plans", plans)
        keep_ids = plan_df[plan_df["metal_level"].isin(metal_levels)]["plan_id"]
        q = q[q["plan_id"].isin(keep_ids)]
    agg = (
        q.groupby("county_fips", as_index=False)["monthly_premium"]
        .median()
        .rename(columns={"monthly_premium": "median_premium"})
    )
    agg["median_premium"] = pd.to_numeric(agg["median_premium"], errors="coerce")

    keep = ["county_fips", "county_name", "state"]
    geo = geo[[c for c in keep if c in geo.columns]].drop_duplicates("county_fips")
    out = agg.merge(geo, on="county_fips", how="left")

    # Build a guaranteed non-null, unique label: "Name, ST". Fall back to the
    # FIPS when name/state are missing so two unmatched rows can't merge.
    name = out["county_name"].fillna("Unknown")
    state = out["state"].fillna("")
    out["county_label"] = [
        (f"{n}, {s}" if s else f"{n} ({f})")
        for n, s, f in zip(name, state, out["county_fips"])
    ]
    # If any labels still collide, disambiguate with the FIPS.
    dup = out["county_label"].duplicated(keep=False)
    out.loc[dup, "county_label"] = (
        out.loc[dup, "county_label"] + " (" + out.loc[dup, "county_fips"] + ")"
    )
    return out


# ---------------------------------------------------------------------------
# View 2: metal-level distribution (responds to profile, county, metal filter)
# ---------------------------------------------------------------------------

def metal_distribution(profile_id, county_fips=None, metal_levels=None):
    """
    Plans available and median premium per metal level. Scoped to a profile,
    optionally narrowed to a single county and to a subset of metal levels.
    """
    cols = ["metal_level", "plan_count", "median_premium"]
    quotes = _coerce_numeric(_read_table("premium_quotes", premium_quotes))
    plan_df = _read_table("plans", plans)
    if quotes.empty or plan_df.empty:
        return pd.DataFrame(columns=cols)

    q = quotes[quotes["profile_id"] == profile_id]
    if county_fips:
        q = q[q["county_fips"] == county_fips]
    if q.empty:
        return pd.DataFrame(columns=cols)

    merged = q.merge(plan_df[["plan_id", "metal_level"]], on="plan_id", how="left")
    if metal_levels:
        merged = merged[merged["metal_level"].isin(metal_levels)]

    return (
        merged.groupby("metal_level", as_index=False)
        .agg(plan_count=("plan_id", "nunique"),
             median_premium=("monthly_premium", "median"))
    )


# ---------------------------------------------------------------------------
# View 3: side-by-side plan comparison
# ---------------------------------------------------------------------------

def plan_comparison(profile_id, county_fips, metal_levels=None):
    quotes = _coerce_numeric(_read_table("premium_quotes", premium_quotes))
    plan_df = _read_table("plans", plans)
    benefits = _coerce_numeric(_read_table("plan_benefits", plan_benefits))
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


# ---------------------------------------------------------------------------
# View 4: full vs. after-credit premium, by metal level
# ---------------------------------------------------------------------------

def premium_vs_credit(profile_id, county_fips=None, metal_levels=None):
    """
    Median full premium vs. median premium-after-credit, grouped by metal level.
    Shows how much the advance premium tax credit buys down the sticker price.
    Scoped to a county and/or metal subset when given.

    Returns long-form rows (metal_level, kind, amount) ready for a grouped bar.
    """
    empty = pd.DataFrame(columns=["metal_level", "kind", "amount"])
    quotes = _coerce_numeric(_read_table("premium_quotes", premium_quotes))
    plan_df = _read_table("plans", plans)
    if quotes.empty or plan_df.empty:
        return empty

    q = quotes[quotes["profile_id"] == profile_id]
    if county_fips:
        q = q[q["county_fips"] == county_fips]
    if q.empty:
        return empty

    merged = q.merge(plan_df[["plan_id", "metal_level"]], on="plan_id", how="left")
    if metal_levels:
        merged = merged[merged["metal_level"].isin(metal_levels)]

    agg = (
        merged.groupby("metal_level", as_index=False)
        .agg(full=("monthly_premium", "median"),
             after_credit=("premium_after_credit", "median"))
    )
    long = agg.melt(
        id_vars="metal_level",
        value_vars=["full", "after_credit"],
        var_name="kind", value_name="amount",
    )
    long["kind"] = long["kind"].map(
        {"full": "Full premium", "after_credit": "After credit"}
    )
    return long


# ---------------------------------------------------------------------------
# View 5: plan offering and price by issuer
# ---------------------------------------------------------------------------

def issuer_comparison(profile_id, county_fips=None, metal_levels=None):
    """
    Per-issuer summary for the selected profile: how many distinct plans each
    insurer offers and their median monthly premium. Scoped to a county and/or
    metal subset when given. Sorted by plan count (widest offering first).
    """
    empty = pd.DataFrame(columns=["issuer_name", "plan_count", "median_premium"])
    quotes = _coerce_numeric(_read_table("premium_quotes", premium_quotes))
    plan_df = _read_table("plans", plans)
    issuer_df = _read_table("issuers", issuers)
    if quotes.empty or plan_df.empty:
        return empty

    q = quotes[quotes["profile_id"] == profile_id]
    if county_fips:
        q = q[q["county_fips"] == county_fips]
    if q.empty:
        return empty

    merged = q.merge(
        plan_df[["plan_id", "issuer_id", "metal_level"]], on="plan_id", how="left"
    )
    if metal_levels:
        merged = merged[merged["metal_level"].isin(metal_levels)]

    if not issuer_df.empty:
        merged = merged.merge(
            issuer_df[["issuer_id", "issuer_name"]], on="issuer_id", how="left"
        )
        merged["issuer_name"] = merged["issuer_name"].fillna(merged["issuer_id"])
    else:
        merged["issuer_name"] = merged["issuer_id"]

    agg = (
        merged.groupby("issuer_name", as_index=False)
        .agg(plan_count=("plan_id", "nunique"),
             median_premium=("monthly_premium", "median"))
    )
    agg["median_premium"] = pd.to_numeric(agg["median_premium"], errors="coerce")
    return agg.sort_values("plan_count", ascending=False)

# ---------------------------------------------------------------------------
# View 6: premium vs. deductible scatter (one dot per plan)
# ---------------------------------------------------------------------------

def plan_value_scatter(profile_id, county_fips, metal_levels=None):
    """
    One row per plan for the selected profile + county: after-credit premium
    against individual deductible, plus metal level for color and the plan name
    for hover. Both axes are clean stored numbers -- no modeling. Value plans
    sit toward the low-premium, low-deductible corner.
    """
    cols = ["plan_name", "metal_level", "premium_after_credit",
            "monthly_premium", "deductible_individual", "moop_individual"]
    quotes = _coerce_numeric(_read_table("premium_quotes", premium_quotes))
    plan_df = _read_table("plans", plans)
    benefits = _coerce_numeric(_read_table("plan_benefits", plan_benefits))
    if quotes.empty or plan_df.empty or not county_fips:
        return pd.DataFrame(columns=cols)

    q = quotes[(quotes["profile_id"] == profile_id) &
               (quotes["county_fips"] == county_fips)]
    out = (
        q.merge(plan_df[["plan_id", "plan_name", "metal_level"]], on="plan_id", how="left")
        .merge(benefits[["plan_id", "deductible_individual", "moop_individual"]],
               on="plan_id", how="left")
    )
    if metal_levels:
        out = out[out["metal_level"].isin(metal_levels)]
    # Prefer after-credit premium on the axis; fall back to full if missing.
    out["premium_after_credit"] = out["premium_after_credit"].fillna(out["monthly_premium"])
    out = out.dropna(subset=["premium_after_credit", "deductible_individual"])
    return out[[c for c in cols if c in out.columns]]


# ---------------------------------------------------------------------------
# View 7: estimated annual cost per plan (illustrative, assumption-based)
# ---------------------------------------------------------------------------

# Usage levels map to how much of the plan's OWN deductible/MOOP a shopper is
# assumed to pay over a year. No actuarial model, no copay parsing -- just a
# transparent assumption the user picks. "Moderate" = you meet the deductible;
# "High" = you hit the out-of-pocket maximum.
USAGE_LEVELS = {
    "moderate": "Moderate use (meet the deductible)",
    "high": "High use (reach the out-of-pocket max)",
}


def annual_cost_estimate(profile_id, county_fips, usage="moderate", metal_levels=None):
    """
    Estimated total annual cost per plan:
        (premium_after_credit x 12) + assumed out-of-pocket
    where assumed OOP is the plan's deductible (moderate) or MOOP (high).
    Illustrative only -- actual cost depends on care used. Sorted cheapest first.
    """
    cols = ["plan_name", "metal_level", "annual_premium",
            "assumed_oop", "annual_cost"]
    base = plan_value_scatter(profile_id, county_fips, metal_levels)
    if base.empty:
        return pd.DataFrame(columns=cols)

    df = base.copy()
    df["annual_premium"] = df["premium_after_credit"] * 12
    if usage == "high":
        df["assumed_oop"] = df["moop_individual"]
    else:  # moderate
        df["assumed_oop"] = df["deductible_individual"]
    df["assumed_oop"] = df["assumed_oop"].fillna(0)
    df["annual_cost"] = df["annual_premium"] + df["assumed_oop"]
    return df[cols].sort_values("annual_cost")


def best_value_plan(profile_id, county_fips, usage="moderate", metal_levels=None):
    """The single lowest estimated-annual-cost plan, as a dict (or {})."""
    df = annual_cost_estimate(profile_id, county_fips, usage, metal_levels)
    if df.empty:
        return {}
    return df.iloc[0].to_dict()