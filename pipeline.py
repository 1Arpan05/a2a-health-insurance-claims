"""
Shared claim-processing pipeline. Both the CLI (app.py) and the
Streamlit UI (streamlit_app.py) call run_pipeline() so the agent
orchestration logic exists in exactly one place.
"""

from datetime import datetime

from protocol import Message
from logger import log
from rules_engine import evaluate_claim
from fraud_engine import compute_fraud_signals
from document_engine import verify_bill
from agents.planner import planner
from agents.policy_agent import verify_policy
from agents.coverage_agent import coverage_check
from agents.fraud_agent import fraud_check
from agents.medical_agent import medical_check
from agents.document_agent import document_check
from agents.reviewer import reviewer


def _build_claim_text(claim_data: dict, rules_result: dict) -> str:
    docs = claim_data.get("documents", {})
    return f"""
Patient Name : {claim_data['patient_name']}
Patient Gender : {claim_data.get('patient_gender', '')}
Policy Number : {claim_data['policy_number']}
Policy Type : {claim_data['policy_name']}
Policy Coverage Limit : {rules_result['policy_catalog_entry']['coverage_limit']}
Policy Start Date : {claim_data.get('policy_start_date')}
Last Premium Paid Date : {claim_data.get('last_premium_paid_date')}
Policy Status (rules engine) : {rules_result['policy_status']['status']}
Hospital Name : {claim_data['hospital_name']}
Diagnosis : {claim_data['diagnosis']}
Treatment : {claim_data['treatment']}
Claim Date : {claim_data.get('claim_date')}
Claim Amount : {claim_data['claim_amount']}
Previous Claims : {claim_data.get('previous_claims', 0)}

DOCUMENT STATUS

Hospital Bill Verified : {docs.get('hospital_bill', 'no')}
Discharge Summary Verified : {docs.get('discharge_summary', 'no')}
Diagnostic Reports Verified : {docs.get('diagnostic_reports', 'no')}
Prescription Verified : {docs.get('prescription', 'no')}
Patient Identity Proof Verified : {docs.get('patient_identity_proof', 'no')}
Policy Copy Verified : {docs.get('policy_copy', 'no')}
"""


def run_pipeline(claim_data: dict, on_step=None) -> dict:
    """
    claim_data keys: patient_name, patient_gender, policy_number,
    policy_name, hospital_name, diagnosis, treatment, claim_amount,
    claim_date, previous_claims, policy_start_date,
    last_premium_paid_date, documents{...},
    optional bill_upload={"bytes": <raw bytes>, "filename": "bill.pdf"}

    on_step(name, output) is an optional callback fired after each
    agent completes -- Streamlit uses it to render progress live.
    """
    trace = []

    def step(sender, receiver, task, message, status="done"):
        msg = Message(sender=sender, receiver=receiver, task=task, message=str(message)[:4000], status=status)
        trace.append(msg.__dict__)
        try:
            log(msg)
        except Exception:
            pass  # logging must never break the pipeline
        if on_step:
            on_step(task, message)
        return msg

    # 1. Deterministic rules engine runs first -- ground truth for everything downstream
    rules_result = evaluate_claim(claim_data)
    step("rules_engine", "planner", "rules_evaluation", rules_result)

    claim_text = _build_claim_text(claim_data, rules_result)

    # 2. Deterministic fraud signals from claim history (duplicates, velocity,
    #    amount outliers, early-large-claim risk, hospital rejection rate)
    fraud_signals = compute_fraud_signals(claim_data, rules_result)
    step("fraud_engine", "fraud_agent", "fraud_signal_evaluation", fraud_signals)

    # 3. Planner
    planner_output = planner(claim_text)
    step("planner", "all_agents", "plan", planner_output)

    # 4. Specialist agents
    policy_verification = verify_policy(
        rules_result["policy_name"],
        rules_result["policy_catalog_entry"]["coverage_limit"],
        rules_result["policy_status"]["status"],
    )
    step("policy_agent", "reviewer", "policy_verification", policy_verification)

    coverage_result = coverage_check(claim_text, rules_result)
    step("coverage_agent", "reviewer", "coverage_check", coverage_result)

    fraud_result = fraud_check(claim_text, fraud_signals)
    step("fraud_agent", "reviewer", "fraud_check", fraud_result)

    medical_result = medical_check(claim_text)
    step("medical_agent", "reviewer", "medical_check", medical_result)

    bill_upload = claim_data.get("bill_upload")
    bill_verification = None
    if bill_upload and bill_upload.get("bytes"):
        bill_verification = verify_bill(
            bill_upload["bytes"], bill_upload["filename"], float(claim_data["claim_amount"])
        )
        step("document_engine", "document_agent", "bill_verification", bill_verification)

    document_result = document_check(claim_text, bill_verification)
    step("document_agent", "reviewer", "document_check", document_result)

    agent_results = {
        "policy": policy_verification,
        "coverage": coverage_result,
        "fraud": fraud_result,
        "medical": medical_result,
        "document": document_result,
        "rules_engine": rules_result,
        "fraud_signals": fraud_signals,
        "bill_verification": bill_verification,
    }

    # 5. Reviewer
    recommendation = reviewer(agent_results)
    step("reviewer", "human_reviewer", "recommendation", recommendation)

    return {
        "claim_text": claim_text,
        "rules_result": rules_result,
        "fraud_signals": fraud_signals,
        "bill_verification": bill_verification,
        "planner_output": planner_output,
        "agent_results": agent_results,
        "recommendation": recommendation,
        "trace": trace,
        "created_at": str(datetime.now()),
    }
