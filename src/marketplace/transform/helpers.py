"""
helpers.py
==========
Small helpers for digging into the nested / inconsistent structures the API
returns for deductibles, MOOPs, and per-benefit cost sharing.
"""


def first_amount(items, want_type=None):
    """
    Deductibles and MOOPs come back as a list of objects, often split by
    'Medical', 'Drug', 'Medical and Drug', and by individual vs family.
    Pull the first matching amount; fall back to the first amount present.
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
    for it in items:
        if isinstance(it, dict) and it.get("amount") is not None:
            return it.get("amount")
    return None


def benefit_copay(plan, benefit_name):
    """
    Plan benefits live in a list; each has a name and cost-sharing detail.
    Returns a readable copay/coinsurance string for the named benefit.
    """
    for b in plan.get("benefits", []) or []:
        if not isinstance(b, dict):
            continue
        if b.get("name") == benefit_name:
            shares = b.get("cost_sharings") or []
            if shares and isinstance(shares[0], dict):
                return shares[0].get("display_string")
    return None
