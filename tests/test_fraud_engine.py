"""
Tests for the deterministic fraud signal engine. Each signal is seeded
via real store.save_claim() calls against an isolated temp DB (see
conftest.isolated_db) so these test real query behavior, not mocks.
"""

from datetime import datetime, timedelta

import pytest

from fraud_engine import compute_fraud_signals

RULES_RESULT = {"policy_catalog_entry": {"coverage_limit": 200000}}


def _claim_data(**overrides):
    claim = {
        "patient_name": "Test Patient",
        "hospital_name": "Test Hospital",
        "diagnosis": "Test Diagnosis",
        "claim_amount": 50000,
        "policy_start_date": "2020-01-01",
        "claim_date": "2020-06-01",
        "previous_claims": 0,
    }
    claim.update(overrides)
    return claim


def _seed(isolated_db, **overrides):
    record = {
        "patient_name": "Test Patient",
        "hospital_name": "Test Hospital",
        "diagnosis": "Test Diagnosis",
        "claim_amount": 50000,
        "status": "approved",
        "created_at": str(datetime.now()),
    }
    record.update(overrides)
    return isolated_db.save_claim(record)


# --------------------------------------------------------------------- baseline
def test_no_history_yields_low_risk_no_flags(isolated_db):
    signals = compute_fraud_signals(_claim_data(), RULES_RESULT)
    assert signals["risk_score"] == "LOW"
    assert signals["risk_flags"] == []
    assert signals["duplicate_count"] == 0


# --------------------------------------------------------------------- duplicate detection
def test_exact_duplicate_is_flagged(isolated_db):
    _seed(isolated_db, patient_name="Anita", hospital_name="Fortis", claim_amount=250000)

    signals = compute_fraud_signals(
        _claim_data(patient_name="Anita", hospital_name="Fortis", claim_amount=250000),
        RULES_RESULT,
    )
    assert signals["duplicate_count"] == 1
    assert any("Duplicate claim" in f for f in signals["risk_flags"])


def test_different_amount_is_not_a_duplicate(isolated_db):
    _seed(isolated_db, patient_name="Anita", hospital_name="Fortis", claim_amount=250000)

    signals = compute_fraud_signals(
        _claim_data(patient_name="Anita", hospital_name="Fortis", claim_amount=90000),
        RULES_RESULT,
    )
    assert signals["duplicate_count"] == 0


# --------------------------------------------------------------------- claim velocity
def test_high_velocity_flagged_at_threshold(isolated_db):
    now = datetime.now()
    for i in range(3):
        _seed(isolated_db, patient_name="Rahul", created_at=str(now - timedelta(days=i)))

    signals = compute_fraud_signals(_claim_data(patient_name="Rahul"), RULES_RESULT)
    assert signals["claims_last_30_days"] == 3
    assert any("velocity" in f.lower() for f in signals["risk_flags"])


def test_low_velocity_below_threshold_not_flagged(isolated_db):
    now = datetime.now()
    for i in range(2):
        _seed(isolated_db, patient_name="Rahul", created_at=str(now - timedelta(days=i)))

    signals = compute_fraud_signals(_claim_data(patient_name="Rahul"), RULES_RESULT)
    assert signals["claims_last_30_days"] == 2
    assert not any("velocity" in f.lower() for f in signals["risk_flags"])


def test_old_claims_outside_window_not_counted(isolated_db):
    now = datetime.now()
    for i in range(3):
        _seed(isolated_db, patient_name="Rahul", created_at=str(now - timedelta(days=90 + i)))

    signals = compute_fraud_signals(_claim_data(patient_name="Rahul"), RULES_RESULT)
    assert signals["claims_last_30_days"] == 0


# --------------------------------------------------------------------- amount outliers
def test_amount_outlier_flagged_when_far_above_average(isolated_db):
    for amount in (40000, 50000, 60000):
        _seed(isolated_db, diagnosis="Fracture", claim_amount=amount)

    signals = compute_fraud_signals(
        _claim_data(diagnosis="Fracture", claim_amount=300000), RULES_RESULT
    )
    assert signals["diagnosis_avg_amount"] == pytest.approx(50000)
    assert signals["amount_deviation_ratio"] >= 2.0
    assert any("outlier" in f.lower() for f in signals["risk_flags"])


def test_amount_within_normal_range_not_flagged(isolated_db):
    for amount in (40000, 50000, 60000):
        _seed(isolated_db, diagnosis="Fracture", claim_amount=amount)

    signals = compute_fraud_signals(
        _claim_data(diagnosis="Fracture", claim_amount=55000), RULES_RESULT
    )
    assert not any("outlier" in f.lower() for f in signals["risk_flags"])


def test_no_diagnosis_history_skips_outlier_check(isolated_db):
    signals = compute_fraud_signals(_claim_data(diagnosis="Never Seen Before"), RULES_RESULT)
    assert signals["diagnosis_avg_amount"] is None
    assert signals["amount_deviation_ratio"] is None


# --------------------------------------------------------------------- early large claim
def test_early_large_claim_flagged(isolated_db):
    claim = _claim_data(
        policy_start_date="2026-01-01",
        claim_date="2026-01-15",  # 14 days after inception
        claim_amount=150000,      # 75% of 200000 coverage
    )
    signals = compute_fraud_signals(claim, RULES_RESULT)
    assert any("Early large claim" in f for f in signals["risk_flags"])


def test_small_claim_soon_after_inception_not_flagged(isolated_db):
    claim = _claim_data(
        policy_start_date="2026-01-01",
        claim_date="2026-01-15",
        claim_amount=10000,  # well under 50% of coverage
    )
    signals = compute_fraud_signals(claim, RULES_RESULT)
    assert not any("Early large claim" in f for f in signals["risk_flags"])


def test_large_claim_long_after_inception_not_flagged(isolated_db):
    claim = _claim_data(
        policy_start_date="2020-01-01",
        claim_date="2026-01-15",  # years after inception
        claim_amount=150000,
    )
    signals = compute_fraud_signals(claim, RULES_RESULT)
    assert not any("Early large claim" in f for f in signals["risk_flags"])


def test_malformed_dates_do_not_crash_early_claim_check(isolated_db):
    claim = _claim_data(policy_start_date="not-a-date", claim_date="also-not-a-date")
    signals = compute_fraud_signals(claim, RULES_RESULT)  # should not raise
    assert not any("Early large claim" in f for f in signals["risk_flags"])


# --------------------------------------------------------------------- hospital rejection rate
def test_high_hospital_rejection_rate_flagged(isolated_db):
    _seed(isolated_db, hospital_name="RiskyHospital", status="rejected")
    _seed(isolated_db, hospital_name="RiskyHospital", status="rejected")
    _seed(isolated_db, hospital_name="RiskyHospital", status="approved")

    signals = compute_fraud_signals(_claim_data(hospital_name="RiskyHospital"), RULES_RESULT)
    assert signals["hospital_rejection_rate"] == pytest.approx(2 / 3)
    assert any("Hospital risk" in f for f in signals["risk_flags"])


def test_low_hospital_rejection_rate_not_flagged(isolated_db):
    _seed(isolated_db, hospital_name="GoodHospital", status="approved")
    _seed(isolated_db, hospital_name="GoodHospital", status="approved")
    _seed(isolated_db, hospital_name="GoodHospital", status="rejected")

    signals = compute_fraud_signals(_claim_data(hospital_name="GoodHospital"), RULES_RESULT)
    assert not any("Hospital risk" in f for f in signals["risk_flags"])


def test_hospital_with_too_few_claims_not_flagged_even_if_all_rejected(isolated_db):
    _seed(isolated_db, hospital_name="NewHospital", status="rejected")
    _seed(isolated_db, hospital_name="NewHospital", status="rejected")

    signals = compute_fraud_signals(_claim_data(hospital_name="NewHospital"), RULES_RESULT)
    assert not any("Hospital risk" in f for f in signals["risk_flags"])


# --------------------------------------------------------------------- previous claims self-report
def test_elevated_previous_claims_flagged(isolated_db):
    signals = compute_fraud_signals(_claim_data(previous_claims=6), RULES_RESULT)
    assert any("previous claims" in f for f in signals["risk_flags"])


def test_normal_previous_claims_not_flagged(isolated_db):
    signals = compute_fraud_signals(_claim_data(previous_claims=1), RULES_RESULT)
    assert not any("previous claims" in f for f in signals["risk_flags"])


# --------------------------------------------------------------------- risk score aggregation
def test_risk_score_medium_with_exactly_one_flag(isolated_db):
    signals = compute_fraud_signals(_claim_data(previous_claims=6), RULES_RESULT)
    assert len(signals["risk_flags"]) == 1
    assert signals["risk_score"] == "MEDIUM"


def test_risk_score_high_with_two_or_more_flags(isolated_db):
    _seed(isolated_db, patient_name="Multi", hospital_name="Apollo", claim_amount=250000)

    claim = _claim_data(
        patient_name="Multi",
        hospital_name="Apollo",
        claim_amount=250000,   # triggers duplicate
        previous_claims=7,      # triggers elevated history
    )
    signals = compute_fraud_signals(claim, RULES_RESULT)
    assert len(signals["risk_flags"]) >= 2
    assert signals["risk_score"] == "HIGH"
