"""
seed.py
=======
Railway release-phase entry point. Populates the database ONCE, then no-ops on
later deploys so every redeploy isn't a fresh (slow, rate-limit-prone) API pull.

Logic:
  1. If DATABASE_URL is set and premium_quotes already has rows -> done, exit 0.
  2. Otherwise run the pipeline. If a raw cache exists, reuse it (--no-extract);
     only hit the CMS API when there's nothing cached yet.
  3. Never hard-fail the deploy: the web service can still boot and fall back
     to Parquet (or show empty-state) rather than crash-loop.

Run from the repo root as:  python seed.py
"""

import sys
import traceback


def _db_already_seeded():
    """True if the DB is reachable and premium_quotes has at least one row."""
    try:
        from sqlalchemy import create_engine, select, func
        from marketplace import config
        from marketplace.db.schema import premium_quotes

        if not config.DATABASE_URL:
            return False
        engine = create_engine(config.DATABASE_URL)
        with engine.connect() as conn:
            n = conn.execute(select(func.count()).select_from(premium_quotes)).scalar()
        return bool(n and n > 0)
    except Exception:
        # Table may not exist yet, or DB not ready -> treat as not seeded.
        return False


def _raw_cache_exists():
    try:
        from marketplace import config
        return any(config.CACHE_DIR.glob("plans_*.json"))
    except Exception:
        return False


def main():
    if _db_already_seeded():
        print("[seed] Database already populated; skipping pipeline.")
        return 0

    try:
        from marketplace.pipeline import run_pipeline
        skip_extract = _raw_cache_exists()
        print(f"[seed] Seeding database (skip_extract={skip_extract}) ...")
        ok = run_pipeline(skip_extract=skip_extract)
        if not ok:
            print("[seed] Pipeline ran but validation reported issues. "
                  "Continuing so the web service can still start.")
        else:
            print("[seed] Pipeline complete and validated.")
        return 0
    except Exception:
        print("[seed] Pipeline raised an exception. The web service will still "
              "start and fall back to available data.\n")
        traceback.print_exc()
        return 0  # deliberately non-fatal


if __name__ == "__main__":
    sys.exit(main())
