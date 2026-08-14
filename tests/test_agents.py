"""
Tests for the agent wrapper functions, with the LLM call (agent.ask)
mocked out. These don't test "is the AI's answer good" -- that's not
a deterministic, testable question. They test the surrounding code:
did the right evidence get formatted into the prompt, does the
correct branch fire for approve vs reject, do pure helper functions
validate input correctly. Each agent module does `from agent import
ask`, binding its own local reference, so we monkeypatch that
reference on the *agent's* module, not on agent.py itself.
"""

import pytest

import agents.coverage_agent as coverage_agent
import agents.document_agent as document_agent
import agents.executor as executor
import agents.fraud_agent as fraud_agent
import agents.policy_agent as policy_agent
from agents.human_reviewer import record_human_decision
from rules_engine import POLICIES


def _capture_ask(monkeypatch, module):
    """Replaces module.ask with a fake that records its args and returns canned text."""
    calls = []

    def fake_ask(system, user):
        calls.append({"system": system, "user": user})
        return "MOCKED AGENT RESPONSE"

    monkeypatch.setattr(module, "ask", fake_ask)
    return calls


# --------------------------------------------------------------------- policy_agent
def test_get_policy_info_is_pure_lookup_no_llm_call():
    info = policy_agent.get_policy_info("Star Gold")
    assert info["coverage_limit"] == POLICIES["Star Gold"]["coverage_limit"]
    assert info["premium"] == POLICIES["Star Gold"]["premium"]


def test_get_policy_info_unknown_policy_raises():
    with pytest.raises(KeyError):
        policy_agent.get_policy_info("Not A Real Policy")


def test_verify_policy_passes_status_hint_into_prompt(monkeypatch):
    calls = _capture_ask(monkeypatch, policy_agent)
    policy_agent.verify_policy("Star Gold", 200000, "LAPSED")
    assert len(calls) == 1
    assert "LAPSED" in calls[0]["user"]
    assert "Star Gold" in calls[0]["user"]
    assert "200000" in calls[0]["user"]


def test_verify_policy_defaults_to_unknown_status_when_hint_missing(monkeypatch):
    calls = _capture_ask(monkeypatch, policy_agent)
    policy_agent.verify_policy("Star Silver", 100000, "")
    assert "UNKNOWN" in calls[0]["user"]


# --------------------------------------------------------------------- coverage_agent
def test_coverage_check_includes_rules_engine_evidence_when_provided(monkeypatch):
    calls = _capture_ask(monkeypatch, coverage_agent)
    rules_result = {"hard_reject": True, "recommended_decision": "REJECT"}
    coverage_agent.coverage_check("CLAIM TEXT HERE", rules_result)
    assert "DETERMINISTIC RULES ENGINE OUTPUT" in calls[0]["user"]
    assert "CLAIM TEXT HERE" in calls[0]["user"]
    assert "REJECT" in calls[0]["user"]


def test_coverage_check_omits_evidence_block_when_rules_result_is_none(monkeypatch):
    calls = _capture_ask(monkeypatch, coverage_agent)
    coverage_agent.coverage_check("CLAIM TEXT HERE", None)
    assert "DETERMINISTIC RULES ENGINE OUTPUT" not in calls[0]["user"]


# --------------------------------------------------------------------- fraud_agent
def test_fraud_check_includes_fraud_signals_evidence(monkeypatch):
    calls = _capture_ask(monkeypatch, fraud_agent)
    fraud_signals = {"risk_score": "HIGH", "risk_flags": ["Duplicate claim: 1 match."]}
    fraud_agent.fraud_check("CLAIM TEXT", fraud_signals)
    assert "FRAUD ENGINE EVIDENCE" in calls[0]["user"]
    assert "HIGH" in calls[0]["user"]
    assert "Duplicate claim" in calls[0]["user"]


def test_fraud_check_notes_no_data_when_signals_missing(monkeypatch):
    calls = _capture_ask(monkeypatch, fraud_agent)
    fraud_agent.fraud_check("CLAIM TEXT", None)
    assert "none available" in calls[0]["user"]


# --------------------------------------------------------------------- document_agent
def test_document_check_no_upload_forbids_match_mismatch_wording_in_prompt(monkeypatch):
    calls = _capture_ask(monkeypatch, document_agent)
    document_agent.document_check("CLAIM TEXT", bill_verification=None)
    system_prompt = calls[0]["system"]
    assert "No bill was uploaded for cross-check" in system_prompt
    assert "Do NOT use the words MATCH" in system_prompt
    assert "No document was uploaded" in calls[0]["user"]


def test_document_check_with_upload_includes_status_branching_instructions(monkeypatch):
    calls = _capture_ask(monkeypatch, document_agent)
    bill_verification = {"status": "MISMATCH", "bill_total_found": 60000, "claimed_amount": 80000}
    document_agent.document_check("CLAIM TEXT", bill_verification)
    system_prompt = calls[0]["system"]
    assert "A bill WAS uploaded" in system_prompt
    assert 'Do NOT say "no bill was uploaded"' in system_prompt
    assert "MISMATCH" in calls[0]["user"]  # the evidence dict itself is in the user message


def test_document_check_upload_and_no_upload_produce_different_prompts(monkeypatch):
    """Regression guard for the exact bug that was fixed: the two branches
    must not bleed into each other."""
    calls = _capture_ask(monkeypatch, document_agent)
    document_agent.document_check("CLAIM", bill_verification={"status": "MATCH"})
    document_agent.document_check("CLAIM", bill_verification=None)
    uploaded_prompt, no_upload_prompt = calls[0]["system"], calls[1]["system"]

    assert uploaded_prompt != no_upload_prompt
    # the "no bill was uploaded" branch's positive instruction must only
    # appear in the no-upload prompt, not leak into the uploaded one
    assert "No bill was uploaded for cross-check" in no_upload_prompt
    assert "No bill was uploaded for cross-check" not in uploaded_prompt
    assert "A bill WAS uploaded" in uploaded_prompt
    assert "A bill WAS uploaded" not in no_upload_prompt


# --------------------------------------------------------------------- executor
def test_execute_approve_branch_generates_approval_prompt(monkeypatch):
    calls = _capture_ask(monkeypatch, executor)
    executor.execute("yes", {"claim_amount": 50000})
    assert "APPROVED" in calls[0]["system"]
    assert "Do NOT generate any rejection content" in calls[0]["system"]


def test_execute_reject_branch_generates_rejection_prompt(monkeypatch):
    calls = _capture_ask(monkeypatch, executor)
    executor.execute("no", {"claim_amount": 50000})
    assert "REJECTED" in calls[0]["system"]
    assert "Do NOT generate any approval content" in calls[0]["system"]


def test_execute_is_case_and_whitespace_insensitive(monkeypatch):
    calls = _capture_ask(monkeypatch, executor)
    executor.execute("  YES  ", {})
    assert "APPROVED" in calls[0]["system"]


def test_execute_passes_results_into_user_message(monkeypatch):
    calls = _capture_ask(monkeypatch, executor)
    results = {"claim_amount": 12345, "settlement_type": "FULL SETTLEMENT"}
    executor.execute("yes", results)
    assert "12345" in calls[0]["user"]
    assert "FULL SETTLEMENT" in calls[0]["user"]


# --------------------------------------------------------------------- human_reviewer (pure)
def test_record_human_decision_normalizes_case_and_whitespace():
    decision, reason = record_human_decision("  YES  ", "looks fine")
    assert decision == "yes"
    assert reason == "looks fine"


def test_record_human_decision_accepts_no():
    decision, _ = record_human_decision("No")
    assert decision == "no"


@pytest.mark.parametrize("bad_input", ["maybe", "", "approve", None])
def test_record_human_decision_rejects_invalid_values(bad_input):
    with pytest.raises(ValueError):
        record_human_decision(bad_input)
