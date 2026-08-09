"""
config.py
=========
Single source of truth for the whole project: filesystem paths, environment
variables, the standardized household profiles, API settings, and the domain
constants the validation layer checks against.

Nothing else in the package should re-declare these. Stages import from here so
that, for example, the household profiles cannot drift between extract and
transform (they used to be defined twice and synced by hand).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# BASE_DIR is the repo root: this file is src/marketplace/config.py, so go up
# three levels (config.py -> marketplace -> src -> repo root).
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "raw_cache"
TIDY_DIR = DATA_DIR / "tidy"

# Created lazily by the stages that write to them, but ensure they exist here
# so a fresh checkout works without manual mkdir.
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TIDY_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Environment / secrets
# ---------------------------------------------------------------------------
load_dotenv(BASE_DIR / ".env")

# NOTE: the key is read as MARKETPLACE_API (not MARKETPLACE_API_KEY).
API_KEY = os.getenv("MARKETPLACE_API")
DATABASE_URL = os.getenv("DATABASE_URL")

# ---------------------------------------------------------------------------
# CMS Marketplace API settings
# ---------------------------------------------------------------------------
BASE_URL = "https://marketplace.api.healthcare.gov/api/v1"
PLAN_YEAR = 2026
MARKET = "Individual"

REQUEST_DELAY = 0.5   # polite pacing between requests (seconds)
MAX_RETRIES = 3
PAGE_SIZE = 100       # plans per page; API default is 10

# Target zip codes — a few representative ones per state. extract resolves these
# to county FIPS automatically. Expand for broader county coverage.
TARGET_ZIPS = {
    "IN": ["47150", "46204", "47715"],   # New Albany, Indianapolis, Evansville
    "OH": ["45202", "43215", "44114"],   # Cincinnati, Columbus, Cleveland
    "TN": ["37201", "37402", "37902"],   # Nashville, Chattanooga, Knoxville
    "WV": ["25301", "26501", "25701"],   # Charleston, Morgantown, Huntington
}

# ---------------------------------------------------------------------------
# Standardized household profiles (canonical definition)
# ---------------------------------------------------------------------------
# A fixed set of shoppers means a premium difference between two counties
# reflects the market, not the household. This is the ONE place profiles live;
# extract derives the API "people" payload from it, transform writes the flat
# columns to the query_profiles table.
#
# Profiles are GENERATED as a grid (ages x FPL bands) rather than hand-listed,
# so the dashboard can let a user dial in an age/income and snap to the nearest
# stored profile. To widen coverage, add values to PROFILE_AGES or
# PROFILE_FPL_BANDS and re-run the pipeline once -- nothing else changes.
#
# Current grid: 5 ages x 3 FPL bands = 15 profiles. household size fixed at 1,
# tobacco off, to keep the one-time extract tractable.

PROFILE_AGES = [25, 35, 45, 55, 64]
PROFILE_FPL_BANDS = [150, 250, 400]

# 2025 federal poverty level for a household of 1 (used to derive income from
# an FPL band). Roughly $15,060; income = FPL% x that.
FPL_BASE_HH1 = 15060


def _build_profiles():
    profiles = []
    for age in PROFILE_AGES:
        for fpl in PROFILE_FPL_BANDS:
            profiles.append({
                "profile_id": f"single_{age}_{fpl}fpl",
                "age": age,
                "income": round(FPL_BASE_HH1 * fpl / 100),
                "fpl_percent": fpl,
                "gender": "Male",
                "uses_tobacco": False,
                "household_size": 1,
                "aptc_eligible": True,
            })
    return profiles


HOUSEHOLD_PROFILES = _build_profiles()

# Columns persisted to the query_profiles table (drops API-only keys).
PROFILE_TABLE_COLUMNS = [
    "profile_id", "age", "income", "fpl_percent",
    "uses_tobacco", "gender", "household_size",
]


def profile_people(profile):
    """Build the API 'people' list for a household profile."""
    return [{
        "age": profile["age"],
        "aptc_eligible": profile["aptc_eligible"],
        "gender": profile["gender"],
        "uses_tobacco": profile["uses_tobacco"],
    }]


# ---------------------------------------------------------------------------
# Validation domain constants
# ---------------------------------------------------------------------------
VALID_METAL_LEVELS = {
    "Bronze", "Expanded Bronze", "Silver", "Gold", "Platinum", "Catastrophic",
}
PREMIUM_FLOOR = 50.0        # below this, almost certainly a data error
PREMIUM_CEILING = 5000.0    # above this, flag for review
BENEFIT_NULL_WARN_PCT = 10.0  # warn if >10% of plans miss a core benefit field
