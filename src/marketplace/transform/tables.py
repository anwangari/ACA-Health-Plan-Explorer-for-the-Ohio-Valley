"""
tables.py
=========
Reads the raw JSON responses cached by extract, flattens the nested plan data
into six tidy tables, and writes each to Parquet in data/tidy/.

Output tables:
  counties        - geography pulled from _counties.json
  query_profiles  - the standardized household profiles
  issuers         - distinct insurance companies
  plans           - one row per plan (fixed attributes)
  plan_benefits   - cost-sharing detail, one row per plan
  premium_quotes  - the fact table: plan x county x profile -> premium
"""

import json

import pandas as pd

from marketplace import config
from marketplace.logging_setup import get_logger
from marketplace.transform.helpers import first_amount, benefit_copay

log = get_logger("transform")


def load_counties():
    path = config.CACHE_DIR / "_counties.json"
    if not path.exists():
        log.warning("No _counties.json found; counties table will be empty.")
        return pd.DataFrame(columns=["county_fips", "county_name", "state", "zipcode"])
    rows = json.loads(path.read_text())
    df = pd.DataFrame(rows).drop_duplicates(subset=["county_fips"])
    return df[["county_fips", "county_name", "state", "zipcode"]]


def iter_plan_files():
    """Yield (meta, plans_list) for every cached plan search response."""
    for f in sorted(config.CACHE_DIR.glob("plans_*.json")):
        payload = json.loads(f.read_text())
        meta = payload.get("_meta", {})
        plans = payload.get("response", {}).get("plans", [])
        yield meta, plans


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
                    "deductible_individual": first_amount(
                        plan.get("deductibles"), "Medical"),
                    "deductible_family": first_amount(
                        plan.get("deductibles"), "Medical Family"),
                    "moop_individual": first_amount(
                        plan.get("moops"), "Medical"),
                    "moop_family": first_amount(
                        plan.get("moops"), "Medical Family"),
                    "primary_care_copay": benefit_copay(
                        plan, "Primary Care Visit to Treat an Injury or Illness"),
                    "specialist_copay": benefit_copay(
                        plan, "Specialist Visit"),
                    "generic_drug_copay": benefit_copay(
                        plan, "Generic Drugs"),
                    "emergency_room_cost": benefit_copay(
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

    quotes_df = pd.DataFrame(quotes).drop_duplicates(
        subset=["plan_id", "county_fips", "profile_id"])

    # query_profiles is built from the canonical config definition, keeping only
    # the columns the table persists.
    profiles_df = pd.DataFrame(config.HOUSEHOLD_PROFILES)[config.PROFILE_TABLE_COLUMNS]

    return {
        "issuers": pd.DataFrame(list(issuers.values())),
        "plans": pd.DataFrame(list(plans.values())),
        "plan_benefits": pd.DataFrame(list(benefits.values())),
        "premium_quotes": quotes_df,
        "query_profiles": profiles_df,
    }


def main():
    log.info("Starting transform.")

    tables = {"counties": load_counties()}
    tables.update(build_tables())

    for name, df in tables.items():
        out = config.TIDY_DIR / f"{name}.parquet"
        df.to_parquet(out, index=False, engine="pyarrow")
        log.info("Wrote %-15s %5d rows -> %s", name, len(df), out.name)

    log.info("Done. Tables written to %s/", config.TIDY_DIR)
    log.info("Unique plans: %d | unique issuers: %d | premium quotes: %d",
             len(tables["plans"]), len(tables["issuers"]),
             len(tables["premium_quotes"]))


if __name__ == "__main__":
    main()
