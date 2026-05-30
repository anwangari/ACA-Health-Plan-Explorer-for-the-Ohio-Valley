"""
Smoke tests — fast, no API key or database required. These check that the
package imports cleanly, the config invariants hold, and the pure transform
helpers behave. (Replaces the old top-level simple-tests.py.)
"""

from marketplace import config
from marketplace.transform.helpers import first_amount, benefit_copay


def test_profiles_have_required_keys():
    for p in config.HOUSEHOLD_PROFILES:
        for key in config.PROFILE_TABLE_COLUMNS:
            assert key in p, f"profile {p.get('profile_id')} missing {key}"
        # keys the API payload needs
        assert "aptc_eligible" in p


def test_profile_ids_unique():
    ids = [p["profile_id"] for p in config.HOUSEHOLD_PROFILES]
    assert len(ids) == len(set(ids))


def test_profile_people_payload():
    people = config.profile_people(config.HOUSEHOLD_PROFILES[0])
    assert isinstance(people, list) and len(people) == 1
    assert {"age", "aptc_eligible", "gender", "uses_tobacco"} <= people[0].keys()


def test_first_amount_prefers_requested_type():
    items = [
        {"type": "Drug", "amount": 100},
        {"type": "Medical", "amount": 500},
    ]
    assert first_amount(items, "Medical") == 500
    # falls back to first available when type is missing
    assert first_amount([{"amount": 42}], "Medical") == 42
    assert first_amount(None) is None


def test_benefit_copay_reads_display_string():
    plan = {"benefits": [
        {"name": "Specialist Visit",
         "cost_sharings": [{"display_string": "$50"}]},
    ]}
    assert benefit_copay(plan, "Specialist Visit") == "$50"
    assert benefit_copay(plan, "Nonexistent") is None
