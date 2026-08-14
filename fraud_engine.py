"""
Deterministic fraud signal computation, mirroring rules_engine.py's
approach: the numbers/flags are computed in code from real historical
data in the store, and the LLM fraud agent is given that evidence to
explain rather than being asked to detect fraud from a single text blob
with no data behind it.
"""

from datetime import datetime, timedelta

from store import (
    claims_by_patient_since,
    diagnosis_amount_stats,
    find_possible_duplicates,
    hospital_claim_stats,
)

VELOCITY_WINDOW_DAYS = 30
VELOCITY_THRESHOLD = 3            # >= this many claims by the same patient in the window
AMOUNT_DEVIATION_THRESHOLD = 2.0  # claim amount > 2x the historical average for this diagnosis
EARLY_CLAIM_WINDOW_DAYS = 60      # claim filed this soon after policy inception
EARLY_CLAIM_COVERAGE_RATIO = 0.5  # ...and for more than 50% of the coverage limit
HIGH_HOSPITAL_REJECTION_RATE = 0.5


def compute_fraud_signals(claim_data: dict, rules_result: dict) -> dict:
    patient_name = claim_data["patient_name"]
    hospital_name = claim_data["hospital_name"]
    diagnosis = claim_data["diagnosis"]
    claim_amount = float(claim_data["claim_amount"])

    flags = []

    # 1. Exact duplicate (same patient, hospital, amount already on file)
    duplicates = find_possible_duplicates(patient_name, hospital_name, claim_amount)
    if duplicates:
        flags.append(f"Duplicate claim: {len(duplicates)} prior claim(s) match patient/hospital/amount exactly.")

    # 2. Claim velocity -- many claims from the same patient in a short window
    since = str(datetime.now() - timedelta(days=VELOCITY_WINDOW_DAYS))
    recent = claims_by_patient_since(patient_name, since)
    if len(recent) >= VELOCITY_THRESHOLD:
        flags.append(
            f"High claim velocity: {len(recent)} claims filed by this patient in the last "
            f"{VELOCITY_WINDOW_DAYS} days (threshold: {VELOCITY_THRESHOLD})."
        )

    # 3. Amount is a statistical outlier for this diagnosis
    stats = diagnosis_amount_stats(diagnosis)
    amount_deviation_ratio = None
    if stats["avg"]:
        amount_deviation_ratio = claim_amount / stats["avg"]
        if amount_deviation_ratio >= AMOUNT_DEVIATION_THRESHOLD:
            flags.append(
                f"Amount outlier: claim (Rs.{claim_amount:,.0f}) is {amount_deviation_ratio:.1f}x the "
                f"historical average (Rs.{stats['avg']:,.0f}) for '{diagnosis}' (n={stats['count']})."
            )

    # 4. Large claim filed suspiciously soon after policy inception
    try:
        start = datetime.strptime(str(claim_data.get("policy_start_date")), "%Y-%m-%d")
        claim_dt = datetime.strptime(str(claim_data.get("claim_date")), "%Y-%m-%d")
        days_since_start = (claim_dt - start).days
        coverage_limit = rules_result["policy_catalog_entry"]["coverage_limit"]
        if 0 <= days_since_start <= EARLY_CLAIM_WINDOW_DAYS and claim_amount >= EARLY_CLAIM_COVERAGE_RATIO * coverage_limit:
            flags.append(
                f"Early large claim: filed {days_since_start} day(s) after policy inception for "
                f"{claim_amount / coverage_limit:.0%} of the coverage limit."
            )
    except (ValueError, TypeError, KeyError):
        days_since_start = None

    # 5. Hospital's historical rejection rate
    hosp_stats = hospital_claim_stats(hospital_name)
    if hosp_stats["total_claims"] >= 3 and hosp_stats["rejection_rate"] >= HIGH_HOSPITAL_REJECTION_RATE:
        flags.append(
            f"Hospital risk: {hospital_name} has a {hosp_stats['rejection_rate']:.0%} claim rejection "
            f"rate across {hosp_stats['total_claims']} prior claims."
        )

    # 6. High count of previous claims self-reported by the claimant
    try:
        previous_claims = int(claim_data.get("previous_claims", 0))
        if previous_claims >= 5:
            flags.append(f"Claimant self-reports {previous_claims} previous claims (elevated history).")
    except (ValueError, TypeError):
        pass

    # Simple weighted risk score
    if len(flags) >= 2:
        risk_score = "HIGH"
    elif len(flags) == 1:
        risk_score = "MEDIUM"
    else:
        risk_score = "LOW"

    return {
        "risk_score": risk_score,
        "risk_flags": flags,
        "duplicate_count": len(duplicates),
        "claims_last_30_days": len(recent),
        "diagnosis_avg_amount": stats["avg"],
        "amount_deviation_ratio": amount_deviation_ratio,
        "hospital_rejection_rate": hosp_stats["rejection_rate"],
    }
