"""
schema.py
=========
The single source of truth for the relational schema: six SQLAlchemy Table
definitions, the FK-respecting load order, and which key columns must be loaded
as strings. load.py, validate, and the dashboard all import from here.

Design notes:
  - county_fips, issuer_id, plan_id, profile_id are natural keys from the API.
  - plan_benefits uses plan_id as its PK (one benefit row per plan).
  - premium_quotes uses a COMPOSITE PK (plan_id, county_fips, profile_id):
    that triple uniquely identifies a quote and makes reruns idempotent.
  - ingested_at on every table supports the data-quality / reproducibility story.
"""

from sqlalchemy import (
    MetaData, Table, Column, String, Integer, Float, Boolean, DateTime,
    ForeignKey,
)

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
