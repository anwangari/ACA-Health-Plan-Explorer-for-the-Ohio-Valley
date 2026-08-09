"""
plans.py
========
Endpoint wrappers and the extraction loop. Resolves zip codes to counties, then
for each (county, household profile) pair pulls every plan (paging to the full
reported total) and caches the raw JSON to data/raw_cache/.
"""

import json

from marketplace import config
from marketplace.extract.api_client import request
from marketplace.logging_setup import get_logger

log = get_logger("extract")


def get_counties_for_zip(zipcode):
    """
    Resolve a zip code to its county/counties.
    Endpoint: GET /counties/by/zip/{zipcode}

    A zip can span multiple counties, so this returns a list.
    """
    data = request("GET", f"counties/by/zip/{zipcode}")
    if not data:
        return []

    results = []
    for c in data.get("counties", []):
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
    cache_file = config.CACHE_DIR / f"plans_{county['county_fips']}_{profile['profile_id']}.json"

    # Smart cache check: only skip if the cached file holds the full set.
    if cache_file.exists():
        cached = json.loads(cache_file.read_text())
        got = len(cached.get("response", {}).get("plans", []))
        total = cached.get("response", {}).get("total", got)
        if got >= total:
            log.info("Cache hit (complete): %s", cache_file.name)
            return cached
        log.info("Cache incomplete (%d/%d), refetching: %s", got, total, cache_file.name)

    base_body = {
        "household": {
            "income": profile["income"],
            "people": config.profile_people(profile),
        },
        "market": config.MARKET,
        "place": {
            "countyfips": county["county_fips"],
            "state": county["state"],
            "zipcode": county["zipcode"],
        },
        "year": config.PLAN_YEAR,
    }

    all_plans = []
    total = None
    offset = 0
    last_meta = {}

    while True:
        body = dict(base_body, limit=config.PAGE_SIZE, offset=offset)
        data = request("POST", "plans/search", json_body=body)
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
            "plan_year": config.PLAN_YEAR,
        },
        "response": {**last_meta, "total": total, "plans": all_plans},
    }
    cache_file.write_text(json.dumps(enriched, indent=2))
    log.info("Saved %d/%s plans -> %s", len(all_plans), total, cache_file.name)
    return enriched


def main():
    """Resolve all target zips to counties, then pull plans for every
    county x profile combination."""
    log.info("Starting extraction for plan year %d", config.PLAN_YEAR)

    # Step 1: resolve zips to counties (dedupe — many zips share a county).
    seen_fips = set()
    counties = []
    for zips in config.TARGET_ZIPS.values():
        for z in zips:
            for county in get_counties_for_zip(z):
                fips = county["county_fips"]
                if fips and fips not in seen_fips:
                    seen_fips.add(fips)
                    counties.append(county)

    log.info("Resolved %d unique counties.", len(counties))

    # Save the county list — this feeds the 'counties' table directly.
    (config.CACHE_DIR / "_counties.json").write_text(json.dumps(counties, indent=2))

    # Step 2: search plans for every county x profile combination.
    total_calls = len(counties) * len(config.HOUSEHOLD_PROFILES)
    log.info("Will make up to %d plan searches.", total_calls)

    for county in counties:
        for profile in config.HOUSEHOLD_PROFILES:
            search_plans(county, profile)

    log.info("Extraction complete. Raw responses are in %s/", config.CACHE_DIR)


if __name__ == "__main__":
    main()
