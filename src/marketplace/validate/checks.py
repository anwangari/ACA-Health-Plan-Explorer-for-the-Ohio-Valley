"""
checks.py
=========
The individual data-quality checks and the Results accumulator.

Each check has a SEVERITY:
  ERROR - a real data-integrity problem; the run is considered FAILED.
  WARN  - worth a human's attention but not disqualifying.

The headline check is RECONCILIATION: for every (county, profile) we pulled,
compare the number of plans actually in the database against the 'total' the
API reported in the cached response. This catches silent pagination truncation.
"""

import json
import datetime as dt

import pandas as pd
from sqlalchemy import select, func

from marketplace import config
from marketplace.logging_setup import get_logger
from marketplace.db.schema import (
    counties, issuers, plans, plan_benefits, premium_quotes,
)

log = get_logger("validate")


class Results:
    def __init__(self):
        self.rows = []

    def add(self, check, table, severity, passed, n_failed, detail):
        self.rows.append({
            "check": check,
            "table": table,
            "severity": severity,
            "status": "PASS" if passed else "FAIL",
            "n_failed": int(n_failed),
            "detail": detail,
            "checked_at": dt.datetime.now(),
        })
        level = log.info if passed else (log.error if severity == "ERROR" else log.warning)
        level("[%s] %-28s %-14s n_failed=%-5d %s",
              "PASS" if passed else "FAIL", check, f"({table})", n_failed, detail)

    def failed_errors(self):
        return [r for r in self.rows if r["status"] == "FAIL" and r["severity"] == "ERROR"]

    def to_frame(self):
        return pd.DataFrame(self.rows)


def _count(conn, table, whereclause=None):
    stmt = select(func.count()).select_from(table)
    if whereclause is not None:
        stmt = stmt.where(whereclause)
    return conn.execute(stmt).scalar() or 0


def check_required_not_null(conn, res):
    """Required columns must never be null."""
    required = [
        (plans, "plan_id"), (plans, "metal_level"), (plans, "issuer_id"),
        (premium_quotes, "monthly_premium"), (premium_quotes, "plan_id"),
        (premium_quotes, "county_fips"), (premium_quotes, "profile_id"),
        (counties, "county_fips"), (issuers, "issuer_id"),
    ]
    for table, col in required:
        n = _count(conn, table, getattr(table.c, col).is_(None))
        res.add(f"not_null:{col}", table.name, "ERROR", n == 0, n,
                "no nulls" if n == 0 else f"{n} null values in required column")


def check_metal_level_valid(conn, res):
    """metal_level must be a recognized ACA tier."""
    n = _count(conn, plans, plans.c.metal_level.notin_(config.VALID_METAL_LEVELS))
    res.add("valid_metal_level", "plans", "ERROR", n == 0, n,
            "all recognized" if n == 0 else f"{n} plans with unexpected metal level")


def check_premium_positive(conn, res):
    """Premiums must be present and positive."""
    n = _count(conn, premium_quotes,
               (premium_quotes.c.monthly_premium.is_(None)) |
               (premium_quotes.c.monthly_premium <= 0))
    res.add("premium_positive", "premium_quotes", "ERROR", n == 0, n,
            "all positive" if n == 0 else f"{n} non-positive/null premiums")


def check_premium_range(conn, res):
    """Premiums outside a plausible monthly band get flagged (not failed)."""
    n = _count(conn, premium_quotes,
               (premium_quotes.c.monthly_premium < config.PREMIUM_FLOOR) |
               (premium_quotes.c.monthly_premium > config.PREMIUM_CEILING))
    res.add("premium_plausible_range", "premium_quotes", "WARN", n == 0, n,
            f"all within ${config.PREMIUM_FLOOR:.0f}-${config.PREMIUM_CEILING:.0f}"
            if n == 0 else f"{n} premiums outside plausible band")


def check_credit_le_premium(conn, res):
    """premium_after_credit should not exceed the full premium."""
    n = _count(conn, premium_quotes,
               (premium_quotes.c.premium_after_credit.isnot(None)) &
               (premium_quotes.c.premium_after_credit > premium_quotes.c.monthly_premium))
    res.add("credit_le_premium", "premium_quotes", "WARN", n == 0, n,
            "subsidized <= full" if n == 0 else f"{n} rows where credited premium exceeds full")


def check_orphans(conn, res):
    """Referential integrity — should hold given FK constraints, but verify."""
    plan_ids = select(plans.c.plan_id)
    n_q = _count(conn, premium_quotes, premium_quotes.c.plan_id.notin_(plan_ids))
    res.add("fk:quotes->plans", "premium_quotes", "ERROR", n_q == 0, n_q,
            "all quotes map to a plan" if n_q == 0 else f"{n_q} orphan quotes")

    issuer_ids = select(issuers.c.issuer_id)
    n_p = _count(conn, plans, plans.c.issuer_id.notin_(issuer_ids))
    res.add("fk:plans->issuers", "plans", "ERROR", n_p == 0, n_p,
            "all plans map to an issuer" if n_p == 0 else f"{n_p} plans with unknown issuer")


def check_benefit_completeness(conn, res):
    """Core benefit fields should be mostly populated; warn past a threshold."""
    total = _count(conn, plan_benefits)
    if total == 0:
        res.add("benefit_completeness", "plan_benefits", "WARN", False, 0, "no rows to check")
        return
    for col in ("deductible_individual", "moop_individual", "primary_care_copay"):
        n_null = _count(conn, plan_benefits, getattr(plan_benefits.c, col).is_(None))
        pct = 100.0 * n_null / total
        passed = pct <= config.BENEFIT_NULL_WARN_PCT
        res.add(f"complete:{col}", "plan_benefits", "WARN", passed, n_null,
                f"{pct:.1f}% null (threshold {config.BENEFIT_NULL_WARN_PCT:.0f}%)")


def check_reconciliation(conn, res):
    """
    HEADLINE CHECK. For each cached (county, profile) response, compare the
    number of plans the API reported (response 'total') against the number of
    premium_quotes actually loaded for that pair. A shortfall means plans were
    dropped between extraction and load (e.g. pagination truncation).
    """
    shortfalls = 0
    pairs_checked = 0
    worst = None

    for f in sorted(config.CACHE_DIR.glob("plans_*.json")):
        payload = json.loads(f.read_text())
        meta = payload.get("_meta", {})
        county = meta.get("county_fips")
        profile = meta.get("profile_id")
        reported_total = payload.get("response", {}).get("total")
        if county is None or profile is None or reported_total is None:
            continue

        pairs_checked += 1
        loaded = _count(conn, premium_quotes,
                        (premium_quotes.c.county_fips == county) &
                        (premium_quotes.c.profile_id == profile))
        if loaded < reported_total:
            shortfalls += 1
            gap = reported_total - loaded
            if worst is None or gap > worst[1]:
                worst = (f"{county}/{profile}", gap, reported_total, loaded)

    if shortfalls == 0:
        detail = f"{pairs_checked} county/profile pairs reconcile exactly"
    else:
        w = worst
        detail = (f"{shortfalls}/{pairs_checked} pairs short; worst {w[0]} "
                  f"loaded {w[3]} of {w[2]} (gap {w[1]})")
    res.add("reconciliation:db_vs_api_total", "premium_quotes", "ERROR",
            shortfalls == 0, shortfalls, detail)


CHECKS = [
    check_required_not_null,
    check_metal_level_valid,
    check_premium_positive,
    check_premium_range,
    check_credit_le_premium,
    check_orphans,
    check_benefit_completeness,
    check_reconciliation,
]
