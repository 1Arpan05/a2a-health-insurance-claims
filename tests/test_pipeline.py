"""
Tests for pipeline.py orchestration: correct step ordering, correct
data wiring between the deterministic engines and the agents, and the
on_step callback contract. All agent functions and verify_bill are
mocked (pipeline.py binds its own references via `from x import y`,
so we monkeypatch those references on the pipeline module) so these
tests run in milliseconds with no LLM calls and no real file I/O.
"""

from datetime import datetime

import pytest

import pipeline


@pytest.fixture(autouse=True)
def mock_all_agents(monkeypatch):
    """Replaces every agent call in pipeline.py with a fast, canned stand-in."""
    monkeypatch.setattr(pipeline, "planner", lambda claim_text: "PLANNER OUTPUT")
    monkeypatch.setattr(
        pipeline, "verify_policy",
        lambda policy_name, coverage_limit, status_hint: f"POLICY VERIFIED ({status_hint})"
    )
    monkeypatch.setattr(pipeline, "coverage_check", lambda claim_text, rules_result: "COVERAGE OK")
    monkeypatch.setattr(pipeline, "fraud_check", lambda claim_text, fraud_signals: "FRAUD OK")
    monkeypatch.setattr(pipeline, "medical_check", lambda claim_text: "MEDICAL OK")
    monkeypatch.setattr(
        pipeline, "document_check",
        lambda claim_text, bill_verification=None: "DOCUMENT OK"
    )
    monkeypatch.setattr(pipeline, "reviewer", lambda agent_results: "FINAL RECOMMENDATION")
    monkeypatch.setattr(
        pipeline, "verify_bill",
        lambda file_bytes, filename, claimed_amount: {"status": "MATCH", "bill_total_found": claimed_amount}
    )


def _valid_claim_data(**overrides):
    claim = {
        "patient_name": "Test Patient",
        "patient_gender": "Female",
        "policy_number": "POL-TEST-001",
        "policy_name": "Star Gold",
        "hospital_name": "Test Hospital",
        "diagnosis": "Test Diagnosis",
        "treatment": "Test Treatment",
        "claim_amount": 150000,
        "claim_date": "2026-06-01",
        "previous_claims": 0,
        "policy_start_date": "2025-01-01",
        "last_premium_paid_date": "2026-01-01",
        "documents": {
            "hospital_bill": "yes", "discharge_summary": "yes", "diagnostic_reports": "yes",
            "prescription": "yes", "patient_identity_proof": "yes", "policy_copy": "yes",
        },
    }
    claim.update(overrides)
    return claim


# --------------------------------------------------------------------- basic shape
def test_run_pipeline_returns_all_expected_keys(isolated_db):
    result = pipeline.run_pipeline(_valid_claim_data())
    for key in ("claim_text", "rules_result", "fraud_signals", "bill_verification",
                "planner_output", "agent_results", "recommendation", "trace", "created_at"):
        assert key in result


def test_run_pipeline_calls_deterministic_rules_engine(isolated_db):
    result = pipeline.run_pipeline(_valid_claim_data(claim_amount=150000))
    assert result["rules_result"]["settlement"]["insurance_payable"] == 150000
    assert result["rules_result"]["hard_reject"] is False


def test_run_pipeline_calls_deterministic_fraud_engine(isolated_db):
    result = pipeline.run_pipeline(_valid_claim_data())
    assert result["fraud_signals"]["risk_score"] in ("LOW", "MEDIUM", "HIGH")


def test_run_pipeline_hard_reject_flows_through_to_rules_result(isolated_db):
    # claim dated before the policy started
    result = pipeline.run_pipeline(_valid_claim_data(claim_date="2020-01-01"))
    assert result["rules_result"]["hard_reject"] is True


# --------------------------------------------------------------------- step ordering
def test_run_pipeline_steps_run_in_expected_order(isolated_db):
    result = pipeline.run_pipeline(_valid_claim_data())
    task_order = [step["task"] for step in result["trace"]]
    assert task_order == [
        "rules_evaluation",
        "fraud_signal_evaluation",
        "plan",
        "policy_verification",
        "coverage_check",
        "fraud_check",
        "medical_check",
        "document_check",
        "recommendation",
    ]


def test_trace_entries_have_sender_and_receiver(isolated_db):
    result = pipeline.run_pipeline(_valid_claim_data())
    for step in result["trace"]:
        assert step["sender"]
        assert step["receiver"]
        assert step["status"] == "done"


# --------------------------------------------------------------------- agent_results wiring
def test_agent_results_contains_all_agent_outputs(isolated_db):
    result = pipeline.run_pipeline(_valid_claim_data())
    agent_results = result["agent_results"]
    assert agent_results["policy"] == "POLICY VERIFIED (ACTIVE)"
    assert agent_results["coverage"] == "COVERAGE OK"
    assert agent_results["fraud"] == "FRAUD OK"
    assert agent_results["medical"] == "MEDICAL OK"
    assert agent_results["document"] == "DOCUMENT OK"
    assert "rules_engine" in agent_results
    assert "fraud_signals" in agent_results


def test_policy_verification_receives_rules_engine_status_hint(isolated_db):
    # lapsed policy -> verify_policy should be called with status "LAPSED"
    result = pipeline.run_pipeline(_valid_claim_data(
        policy_start_date="2020-01-01", last_premium_paid_date="2020-01-01", claim_date="2026-06-01"
    ))
    assert "LAPSED" in result["agent_results"]["policy"]


def test_recommendation_comes_from_reviewer(isolated_db):
    result = pipeline.run_pipeline(_valid_claim_data())
    assert result["recommendation"] == "FINAL RECOMMENDATION"


# --------------------------------------------------------------------- bill upload wiring
def test_no_bill_upload_means_no_bill_verification(isolated_db):
    result = pipeline.run_pipeline(_valid_claim_data())
    assert result["bill_verification"] is None
    task_order = [step["task"] for step in result["trace"]]
    assert "bill_verification" not in task_order


def test_bill_upload_triggers_verify_bill_and_adds_trace_step(isolated_db):
    claim_data = _valid_claim_data(bill_upload={"bytes": b"fake pdf bytes", "filename": "bill.pdf"})
    result = pipeline.run_pipeline(claim_data)
    assert result["bill_verification"] is not None
    assert result["bill_verification"]["status"] == "MATCH"
    task_order = [step["task"] for step in result["trace"]]
    assert "bill_verification" in task_order
    # bill_verification must run before document_check consumes it
    assert task_order.index("bill_verification") < task_order.index("document_check")


def test_bill_upload_with_no_bytes_is_treated_as_no_upload(isolated_db):
    claim_data = _valid_claim_data(bill_upload={"bytes": None, "filename": "bill.pdf"})
    result = pipeline.run_pipeline(claim_data)
    assert result["bill_verification"] is None


# --------------------------------------------------------------------- on_step callback contract
def test_on_step_callback_invoked_for_every_trace_entry(isolated_db):
    seen = []
    pipeline.run_pipeline(_valid_claim_data(), on_step=lambda name, output: seen.append(name))
    result_trace_tasks = [
        "rules_evaluation", "fraud_signal_evaluation", "plan", "policy_verification",
        "coverage_check", "fraud_check", "medical_check", "document_check", "recommendation",
    ]
    assert seen == result_trace_tasks


def test_pipeline_works_without_on_step_callback(isolated_db):
    # on_step is optional -- must not raise if omitted
    result = pipeline.run_pipeline(_valid_claim_data())
    assert result["recommendation"] == "FINAL RECOMMENDATION"


# --------------------------------------------------------------------- created_at
def test_created_at_is_a_recent_timestamp(isolated_db):
    before = datetime.now()
    result = pipeline.run_pipeline(_valid_claim_data())
    created_at = datetime.strptime(result["created_at"], "%Y-%m-%d %H:%M:%S.%f")
    assert created_at >= before
