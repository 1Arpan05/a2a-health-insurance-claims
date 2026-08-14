"""
Deterministic business rules for policy status, waiting periods,
premium lapse, and settlement math.

These decisions are computed in code (not by the LLM) so the
approval/rejection math is auditable and reproducible. LLM agents
consume this output as ground-truth evidence rather than inventing
their own numbers.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


POLICIES = {
    "Star Silver":   {"coverage_limit": 100000,  "premium": 5000,   "frequency": "yearly", "waiting_period_days": 30},
    "Star Gold":     {"coverage_limit": 200000,  "premium": 9000,   "frequency": "yearly", "waiting_period_days": 30},
    "Star Platinum": {"coverage_limit": 500000,  "premium": 18000,  "frequency": "yearly", "waiting_period_days": 15},
    "Star Diamond":  {"coverage_limit": 1000000, "premium": 32000,  "frequency": "yearly", "waiting_period_days": 15},
    "Star Elite":    {"coverage_limit": 2500000, "premium": 65000,  "frequency": "yearly", "waiting_period_days": 0},
}

GRACE_PERIOD_DAYS = 15  # standard grace period after a missed premium due date


def _parse_date(value):
    """Accept date/datetime objects or 'YYYY-MM-DD' strings."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()


def get_policy_catalog():
    """Return the policy catalog for UI display."""
    return POLICIES


def get_policy_status(policy_name, last_premium_paid_date, as_of_date=None):
    """
    Determine ACTIVE / GRACE / LAPSED status from the premium payment
    schedule instead of assuming the policy is always active.
    """
    policy = POLICIES[policy_name]
    as_of = as_of_date or date.today()
    last_paid = _parse_date(last_premium_paid_date)

    if last_paid is None:
        return {"status": "UNKNOWN", "reason": "No premium payment date provided."}

    if policy["frequency"] == "monthly":
        next_due = last_paid + timedelta(days=30)
    else:  # yearly
        next_due = last_paid + timedelta(days=365)

    grace_end = next_due + timedelta(days=GRACE_PERIOD_DAYS)

    if as_of <= next_due:
        return {"status": "ACTIVE", "next_due": str(next_due), "reason": "Premium up to date."}
    elif as_of <= grace_end:
        return {"status": "GRACE", "next_due": str(next_due), "grace_end": str(grace_end),
                "reason": f"Premium overdue since {next_due}, within {GRACE_PERIOD_DAYS}-day grace period."}
    else:
        return {"status": "LAPSED", "next_due": str(next_due), "grace_end": str(grace_end),
                "reason": f"Premium overdue since {next_due}; grace period ended {grace_end}."}


def check_claim_timing(policy_name, policy_start_date, claim_date):
    """
    Reject claims dated before the policy existed, and enforce the
    policy's waiting period after inception.
    """
    policy = POLICIES[policy_name]
    start = _parse_date(policy_start_date)
    claim = _parse_date(claim_date)

    if start is None or claim is None:
        return {"valid": False, "reason": "Missing policy start date or claim/treatment date."}

    if claim < start:
        return {
            "valid": False,
            "reason": f"Claim/treatment date ({claim}) is before the policy start date ({start}). "
                      f"A claim cannot predate the insurance policy it is filed against."
        }

    waiting_period = policy["waiting_period_days"]
    eligible_from = start + timedelta(days=waiting_period)
    if claim < eligible_from:
        return {
            "valid": False,
            "reason": f"Claim date ({claim}) falls within the {waiting_period}-day waiting period "
                      f"after policy inception ({start}). Claims are eligible from {eligible_from}."
        }

    return {"valid": True, "reason": "Claim date is within the valid policy period."}


def compute_settlement(claim_amount, coverage_limit):
    claim_amount = float(claim_amount)
    coverage_limit = float(coverage_limit)

    insurance_payable = min(claim_amount, coverage_limit)
    patient_payable = max(claim_amount - coverage_limit, 0)
    settlement_type = "FULL SETTLEMENT" if claim_amount <= coverage_limit else "PARTIAL SETTLEMENT"

    return {
        "claim_amount": claim_amount,
        "coverage_limit": coverage_limit,
        "insurance_payable": insurance_payable,
        "patient_payable": patient_payable,
        "settlement_type": settlement_type,
    }


def evaluate_claim(claim_data: dict) -> dict:
    """
    Single entry point: runs all deterministic checks and returns a
    structured verdict the LLM reviewer/agents can use as evidence.

    Expected keys in claim_data:
        policy_name, policy_start_date, last_premium_paid_date,
        claim_date, claim_amount
    """
    policy_name = claim_data["policy_name"]
    policy = POLICIES[policy_name]

    policy_status = get_policy_status(
        policy_name,
        claim_data.get("last_premium_paid_date"),
        _parse_date(claim_data.get("claim_date")) or date.today(),
    )

    timing = check_claim_timing(
        policy_name,
        claim_data.get("policy_start_date"),
        claim_data.get("claim_date"),
    )

    settlement = compute_settlement(claim_data["claim_amount"], policy["coverage_limit"])

    hard_reject_reasons = []
    if policy_status["status"] == "LAPSED":
        hard_reject_reasons.append(f"Policy lapsed: {policy_status['reason']}")
    if not timing["valid"]:
        hard_reject_reasons.append(timing["reason"])

    return {
        "policy_name": policy_name,
        "policy_catalog_entry": policy,
        "policy_status": policy_status,
        "claim_timing": timing,
        "settlement": settlement,
        "hard_reject": len(hard_reject_reasons) > 0,
        "hard_reject_reasons": hard_reject_reasons,
        "recommended_decision": "REJECT" if hard_reject_reasons else settlement["settlement_type"],
    }
