"""
extract.py
==========
Extraction layer for the ACA Marketplace project.

Pulls plan data from the CMS Marketplace API for a set of zip codes across
the Ohio Valley region, using a small set of standardized household profiles
so premium quotes stay comparable across counties.

What it does:
  1. Resolves each zip code to its county FIPS code(s).
  2. For each (county, household profile) pair, calls the plan search endpoint.
  3. Saves every raw JSON response to ./raw_cache/ so reruns are cheap and you
     can inspect the real response shape before building the transform step.

Requirements:
  - A free API key from https://developer.cms.gov/marketplace-api/key-request.html
  - pip install requests

Run:
  export MARKETPLACE_API_KEY="your_key_here"
  python extract.py
"""

import os
import json
import time
import logging
from dotenv import load_dotenv
from pathlib import Path

import requests

# -------------------------------------------------------------------------
# read environment varibles from memory
load_dotenv()
# --------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY = os.getenv("MARKETPLACE_API")  # never hard-code your key
BASE_URL = "https://marketplace.api.healthcare.gov/api/v1"
PLAN_YEAR = 2026
MARKET = "Individual"

CACHE_DIR = Path("raw_cache")
CACHE_DIR.mkdir(exist_ok=True)

# Polite pacing between requests (seconds). The API is rate-limited and returns
# the limit in response headers; this keeps us well under it.
REQUEST_DELAY = 0.5
MAX_RETRIES = 3
PAGE_SIZE = 100   # plans per page; API default is 10

# Target zip codes — a few representative ones per state to start.
# The script resolves these to county FIPS automatically; expand this list
# once the pipeline works end to end.
TARGET_ZIPS = {
    "IN": ["47150", "46204", "47715"],   # New Albany, Indianapolis, Evansville
    "OH": ["45202", "43215", "44114"],   # Cincinnati, Columbus, Cleveland
    "TN": ["37201", "37402", "37902"],   # Nashville, Chattanooga, Knoxville
    "WV": ["25301", "26501", "25701"],   # Charleston, Morgantown, Huntington
}

# Standardized household profiles. Keeping a fixed set means a premium
# difference between two counties reflects the market, not the shopper.
HOUSEHOLD_PROFILES = [
    {
        "profile_id": "single_40_250fpl",
        "income": 37650,          # ~250% of FPL for a household of 1 (2025 guideline)
        "people": [
            {"age": 40, "aptc_eligible": True, "gender": "Male", "uses_tobacco": False}
        ],
    },
    {
        "profile_id": "single_27_400fpl",
        "income": 60240,          # ~400% of FPL for a household of 1
        "people": [
            {"age": 27, "aptc_eligible": True, "gender": "Female", "uses_tobacco": False}
        ],
    },
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("extract")


# ---------------------------------------------------------------------------
# Low-level request helper
# ---------------------------------------------------------------------------

def _request(method, path, *, params=None, json_body=None):
    """Make one API call with retry/backoff. Returns parsed JSON or None."""
    if not API_KEY:
        raise RuntimeError(
            "No API key found. Set the MARKETPLACE_API_KEY environment variable."
        )

    url = f"{BASE_URL}/{path}"
    params = dict(params or {})
    params["apikey"] = API_KEY

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(
                method, url, params=params, json=json_body, timeout=30
            )

            # Rate limited — back off and retry.
            if resp.status_code == 429:
                wait = 2 ** attempt
                log.warning("Rate limited. Waiting %ss before retry.", wait)
                time.sleep(wait)
                continue

            # Client error — log what the API actually said, and DON'T retry
            # a 400 (a malformed request won't fix itself by repeating).
            if 400 <= resp.status_code < 500:
                log.error("HTTP %d on %s — API response: %s",
                          resp.status_code, path, resp.text[:600])
                if resp.status_code == 400:
                    return None

            resp.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return resp.json()
        except requests.RequestException as exc:
            log.warning("Request failed (attempt %d/%d): %s",
                        attempt, MAX_RETRIES, exc)
            time.sleep(2 ** attempt)

    log.error("Giving up on %s after %d attempts.", path, MAX_RETRIES)
    return None


# ---------------------------------------------------------------------------
# Endpoint wrappers
# ---------------------------------------------------------------------------

def get_counties_for_zip(zipcode):
    """
    Resolve a zip code to its county/counties.
    Endpoint: GET /counties/by/zip/{zipcode}

    A zip can span multiple counties, so this returns a list.
    NOTE: verify the exact key names ('counties', 'fips', 'name') against a
    real response — they are based on the published API spec but confirm once
    you have your key.
    """
    data = _request("GET", f"counties/by/zip/{zipcode}")
    if not data:
        return []

    counties = data.get("counties", [])
    results = []
    for c in counties:
        results.append({
            "county_fips": c.get("fips"),
            "county_name": c.get("name"),
            "state": c.get("state"),
            "zipcode": zipcode,
        })
    return results


def search_plans(county, profile):
    """
    Search ALL plans for one county + one household profile, paging through
    results until we've collected the full 'total' the API reports.
    Endpoint: POST /plans/search
    """
    cache_file = CACHE_DIR / f"plans_{county['county_fips']}_{profile['profile_id']}.json"

    # Smart cache check: only skip if the cached file already holds the full set.
    if cache_file.exists():
        cached = json.loads(cache_file.read_text())
        got = len(cached.get("response", {}).get("plans", []))
        total = cached.get("response", {}).get("total", got)
        if got >= total:
            log.info("Cache hit (complete): %s", cache_file.name)
            return cached
        log.info("Cache incomplete (%d/%d), refetching: %s", got, total, cache_file.name)

    base_body = {
        "household": {"income": profile["income"], "people": profile["people"]},
        "market": MARKET,
        "place": {
            "countyfips": county["county_fips"],
            "state": county["state"],
            "zipcode": county["zipcode"],
        },
        "year": PLAN_YEAR,
    }

    all_plans = []
    total = None
    offset = 0
    last_meta = {}

    while True:
        body = dict(base_body, limit=PAGE_SIZE, offset=offset)
        data = _request("POST", "plans/search", json_body=body)
        if data is None:
            break

        page_plans = data.get("plans", [])
        all_plans.extend(page_plans)

        if total is None:
            total = data.get("total", len(page_plans))
        # keep the non-plan metadata (facets, ranges, rate_area) from page 1
        if offset == 0:
            last_meta = {k: v for k, v in data.items() if k != "plans"}

        offset += len(page_plans)
        # stop when we've collected everything or a page came back empty
        if not page_plans or offset >= total:
            break

    enriched = {
        "_meta": {
            "county_fips": county["county_fips"],
            "state": county["state"],
            "zipcode": county["zipcode"],
            "profile_id": profile["profile_id"],
            "plan_year": PLAN_YEAR,
        },
        "response": {**last_meta, "total": total, "plans": all_plans},
    }
    cache_file.write_text(json.dumps(enriched, indent=2))
    log.info("Saved %d/%s plans -> %s", len(all_plans), total, cache_file.name)
    return enriched


# ---------------------------------------------------------------------------
# Main extraction loop
# ---------------------------------------------------------------------------

def main():
    log.info("Starting extraction for plan year %d", PLAN_YEAR)

    # Step 1: resolve all zips to counties (dedupe — multiple zips often
    # map to the same county).
    seen_fips = set()
    counties = []
    for state, zips in TARGET_ZIPS.items():
        for z in zips:
            for county in get_counties_for_zip(z):
                if county["county_fips"] and county["county_fips"] not in seen_fips:
                    seen_fips.add(county["county_fips"])
                    counties.append(county)

    log.info("Resolved %d unique counties.", len(counties))

    # Save the county list — this feeds your 'counties' table directly.
    (CACHE_DIR / "_counties.json").write_text(json.dumps(counties, indent=2))

    # Step 2: search plans for every county x profile combination.
    total_calls = len(counties) * len(HOUSEHOLD_PROFILES)
    log.info("Will make up to %d plan searches.", total_calls)

    for county in counties:
        for profile in HOUSEHOLD_PROFILES:
            search_plans(county, profile)

    log.info("Extraction complete. Raw responses are in ./%s/", CACHE_DIR)


if __name__ == "__main__":
    main()