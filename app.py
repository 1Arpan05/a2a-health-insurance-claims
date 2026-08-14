import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agents.policy_agent import policy_check_cli
from agents.human_reviewer import human_review_cli
from agents.executor import execute
from pipeline import run_pipeline
from store import save_claim


print("\n===== HEALTH INSURANCE CLAIM SUBMISSION =====\n")

patient_name = input("Patient Name: ")
patient_gender = input("Patient Gender: ")
policy_number = input("Policy Number: ")
hospital_name = input("Hospital Name: ")
diagnosis = input("Diagnosis/Disease: ")
treatment = input("Treatment/Procedure: ")
claim_amount = input("Claim Amount (Rs.): ")
claim_date = input("Claim / Treatment Date (YYYY-MM-DD): ")
previous_claims = input("Number of Previous Claims: ")

# Policy timeline (needed to catch claims predating the policy / lapsed premiums)
policy_start_date = input("Policy Start Date (YYYY-MM-DD): ")
last_premium_paid_date = input("Last Premium Paid Date (YYYY-MM-DD): ")

# Document Inputs
hospital_bill = input("Hospital Bill Verified? (yes/no): ")
discharge_summary = input("Discharge Summary Verified? (yes/no): ")
diagnostic_reports = input("Diagnostic Reports Verified? (yes/no): ")
prescription = input("Prescription Verified? (yes/no): ")
patient_identity_proof = input("Patient Identity Proof Verified? (yes/no): ")
policy_copy = input("Policy Copy Verified? (yes/no): ")

# Optional: cross-check the hospital bill amount against a real uploaded file (PDF/image)
bill_path = input("Path to hospital bill file for OCR cross-check (optional, blank to skip): ").strip()
bill_upload = None
if bill_path:
    try:
        with open(bill_path, "rb") as f:
            bill_upload = {"bytes": f.read(), "filename": bill_path.split("/")[-1].split("\\")[-1]}
    except OSError as e:
        print(f"Could not read bill file ({e}) -- continuing without bill cross-check.")

# Policy Selection
policy_details = policy_check_cli()

claim_data = {
    "patient_name": patient_name,
    "patient_gender": patient_gender,
    "policy_number": policy_number,
    "policy_name": policy_details["policy_name"],
    "hospital_name": hospital_name,
    "diagnosis": diagnosis,
    "treatment": treatment,
    "claim_amount": claim_amount,
    "claim_date": claim_date,
    "previous_claims": previous_claims,
    "policy_start_date": policy_start_date,
    "last_premium_paid_date": last_premium_paid_date,
    "documents": {
        "hospital_bill": hospital_bill,
        "discharge_summary": discharge_summary,
        "diagnostic_reports": diagnostic_reports,
        "prescription": prescription,
        "patient_identity_proof": patient_identity_proof,
        "policy_copy": policy_copy,
    },
    "bill_upload": bill_upload,
}

print("\n===== RUNNING AGENT PIPELINE =====\n")

result = run_pipeline(claim_data, on_step=lambda name, out: print(f"\n[{name.upper()}]\n{out}"))

print("\n===== RULES ENGINE (deterministic) =====\n")
print(result["rules_result"])

print("\n===== REVIEWER RECOMMENDATION =====\n")
print(result["recommendation"])

decision, reason = human_review_cli(result["recommendation"])

print("\n===== EXECUTOR =====\n")
final_output = execute(decision, result["recommendation"])
print(final_output)

claim_id = save_claim({
    **claim_data,
    "rules_result": result["rules_result"],
    "fraud_signals": result["fraud_signals"],
    "bill_verification": result["bill_verification"],
    "agent_results": result["agent_results"],
    "recommendation": result["recommendation"],
    "human_decision": decision,
    "final_output": final_output,
    "trace": result["trace"],
    "status": "approved" if decision == "yes" else "rejected",
    "created_at": result["created_at"],
})

print(f"\nClaim saved with ID: {claim_id}")
