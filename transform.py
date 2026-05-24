"""
transform.py
============
Transformation layer for the ACA Marketplace project.

Reads the raw JSON responses saved by extract.py, flattens the nested plan
data into tidy tables, and writes each table to Parquet.

Output tables (one .parquet each, in ./tidy/):
  counties        - geography pulled from _counties.json
  query_profiles  - the standardized household profiles
  issuers         - distinct insurance companies
  plans           - one row per plan (fixed attributes)
  plan_benefits   - cost-sharing detail, one row per plan
  premium_quotes  - the bridge table: plan x county x profile -> premium

Why Parquet: it's columnar, compressed, and preserves dtypes, so the load
step into PostgreSQL is cleaner than re-parsing CSV strings. It also handles
nulls without the empty-string ambiguity CSV has.

Requirements:
  pip install pandas pyarrow

Run:
  python transform.py
"""

import json
import logging
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CACHE_DIR = Path("raw_cache")
OUT_DIR = Path("tidy")
OUT_DIR.mkdir(exist_ok=True)

# Mirror the profiles defined in extract.py so query_profiles is self-contained.
# (Kept here rather than imported so this script can run standalone.)
HOUSEHOLD_PROFILES = [
    {"profile_id": "single_40_250fpl", "age": 40, "income": 37650,
     "fpl_percent": 250, "uses_tobacco": False, "gender": "Male", "household_size": 1},
    {"profile_id": "single_27_400fpl", "age": 27, "income": 60240,
     "fpl_percent": 400, "uses_tobacco": False, "gender": "Female", "household_size": 1},
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("transform")


# ---------------------------------------------------------------------------
# Small helpers for digging into nested / inconsistent structures
# ---------------------------------------------------------------------------

def _first_amount(items, want_type=None):
    """
    Deductibles and MOOPs come back as a list of objects, often split by
    'Medical', 'Drug', 'Medical and Drug', and by individual vs family.
    This pulls the first matching amount. Adjust the matching once you've
    eyeballed a real response.
    """
    if not isinstance(items, list):
        return None
    for it in items:
        if not isinstance(it, dict):
            continue
        if want_type is None or it.get("type") == want_type:
            amt = it.get("amount")
            if amt is not None:
                return amt
    # fall back to the first amount we can find
    for it in items:
        if isinstance(it, dict) and it.get("amount") is not None:
            return it.get("amount")
    return None


def _benefit_copay(plan, benefit_name):
    """
    Plan benefits live in a list; each has a name and cost-sharing detail.
    Returns a readable copay/coinsurance string for the named benefit.
    VERIFY the key names ('benefits', 'name', 'cost_sharings', 'display_string')
    against a real cached file.
    """
    for b in plan.get("benefits", []) or []:
        if not isinstance(b, dict):
            continue
        if b.get("name") == benefit_name:
            shares = b.get("cost_sharings") or []
            if shares and isinstance(shares[0], dict):
                return shares[0].get("display_string")
    return None


# ---------------------------------------------------------------------------
# Load raw responses
# ---------------------------------------------------------------------------

def load_counties():
    path = CACHE_DIR / "_counties.json"
    if not path.exists():
        log.warning("No _counties.json found; counties table will be empty.")
        return pd.DataFrame(columns=["county_fips", "county_name", "state", "zipcode"])
    rows = json.loads(path.read_text())
    df = pd.DataFrame(rows).drop_duplicates(subset=["county_fips"])
    return df[["county_fips", "county_name", "state", "zipcode"]]


def iter_plan_files():
    """Yield (meta, plans_list) for every cached plan search response."""
    for f in sorted(CACHE_DIR.glob("plans_*.json")):
        payload = json.loads(f.read_text())
        meta = payload.get("_meta", {})
        plans = payload.get("response", {}).get("plans", [])
        yield meta, plans


# ---------------------------------------------------------------------------
# Build each tidy table
# ---------------------------------------------------------------------------

def build_tables():
    issuers = {}          # issuer_id -> row
    plans = {}            # plan_id   -> row
    benefits = {}         # plan_id   -> row
    quotes = []           # one row per plan x county x profile

    n_plan_rows = 0

    for meta, plan_list in iter_plan_files():
        county_fips = meta.get("county_fips")
        profile_id = meta.get("profile_id")
        plan_year = meta.get("plan_year")

        for plan in plan_list:
            n_plan_rows += 1
            plan_id = plan.get("id")
            if not plan_id:
                continue

            # --- issuer (dedupe by id) ---
            issuer = plan.get("issuer", {}) or {}
            issuer_id = issuer.get("id")
            if issuer_id and issuer_id not in issuers:
                issuers[issuer_id] = {
                    "issuer_id": issuer_id,
                    "issuer_name": issuer.get("name"),
                    "toll_free_number": issuer.get("toll_free_number"),
                    "website_url": issuer.get("individual_url") or issuer.get("url"),
                }

            # --- plan (fixed attributes, dedupe by id) ---
            if plan_id not in plans:
                plans[plan_id] = {
                    "plan_id": plan_id,
                    "issuer_id": issuer_id,
                    "plan_name": plan.get("name"),
                    "metal_level": plan.get("metal_level"),
                    "plan_type": plan.get("type"),
                    "design_type": plan.get("design_type"),
                    "hsa_eligible": plan.get("hsa_eligible"),
                    "plan_year": plan_year,
                }

            # --- plan_benefits (cost sharing, dedupe by id) ---
            if plan_id not in benefits:
                benefits[plan_id] = {
                    "plan_id": plan_id,
                    "deductible_individual": _first_amount(
                        plan.get("deductibles"), "Medical"),
                    "deductible_family": _first_amount(
                        plan.get("deductibles"), "Medical Family"),
                    "moop_individual": _first_amount(
                        plan.get("moops"), "Medical"),
                    "moop_family": _first_amount(
                        plan.get("moops"), "Medical Family"),
                    "primary_care_copay": _benefit_copay(
                        plan, "Primary Care Visit to Treat an Injury or Illness"),
                    "specialist_copay": _benefit_copay(
                        plan, "Specialist Visit"),
                    "generic_drug_copay": _benefit_copay(
                        plan, "Generic Drugs"),
                    "emergency_room_cost": _benefit_copay(
                        plan, "Emergency Room Services"),
                }

            # --- premium_quote (varies by county AND profile) ---
            quotes.append({
                "plan_id": plan_id,
                "county_fips": county_fips,
                "profile_id": profile_id,
                "monthly_premium": plan.get("premium"),
                "premium_after_credit": plan.get("premium_w_credit"),
                "plan_year": plan_year,
            })

    log.info("Processed %d raw plan rows across all files.", n_plan_rows)

    issuers_df = pd.DataFrame(list(issuers.values()))
    plans_df = pd.DataFrame(list(plans.values()))
    benefits_df = pd.DataFrame(list(benefits.values()))
    quotes_df = pd.DataFrame(quotes).drop_duplicates(
        subset=["plan_id", "county_fips", "profile_id"])
    profiles_df = pd.DataFrame(HOUSEHOLD_PROFILES)

    return {
        "issuers": issuers_df,
        "plans": plans_df,
        "plan_benefits": benefits_df,
        "premium_quotes": quotes_df,
        "query_profiles": profiles_df,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info("Starting transform.")

    tables = {"counties": load_counties()}
    tables.update(build_tables())

    for name, df in tables.items():
        out = OUT_DIR / f"{name}.parquet"
        df.to_parquet(out, index=False, engine="pyarrow")
        log.info("Wrote %-15s %5d rows -> %s", name, len(df), out.name)

    # Quick sanity summary
    log.info("Done. Tables written to ./%s/", OUT_DIR)
    log.info("Unique plans: %d | unique issuers: %d | premium quotes: %d",
             len(tables["plans"]), len(tables["issuers"]),
             len(tables["premium_quotes"]))


if __name__ == "__main__":
    main()