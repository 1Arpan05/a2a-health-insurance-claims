"""
Streamlit UI for the A2A health insurance claims pipeline, with
role-based auth: claimants submit and track their own claims;
reviewers/admins see the full agent trace and make the Approve/Reject
call; only decided claims and their public notification are visible
to the claimant who filed them.

Run with:
    streamlit run streamlit_app.py
"""

import pandas as pd
import streamlit as st

from agents.executor import execute
from auth import create_user, seed_default_accounts, verify_login
from document_engine import extraction_capabilities
from pipeline import run_pipeline
from rules_engine import get_policy_catalog
from store import (
    finalize_claim,
    get_metrics_summary,
    list_claims,
    list_claims_by_submitter,
    list_pending_claims,
    save_claim,
)

st.set_page_config(page_title="A2A Health Insurance Claims", layout="wide")
seed_default_accounts()

POLICIES = get_policy_catalog()

for key, default in [
    ("user", None),
    ("pipeline_result", None),
    ("claim_data", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ==================================================================== AUTH GATE
def render_login():
    st.title("A2A Health Insurance Claims")
    tab_login, tab_register = st.tabs(["Login", "Register (Claimant)"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log In")
        if submitted:
            user = verify_login(username, password)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Invalid username or password.")

    with tab_register:
        st.caption("Self-registration creates a claimant account. Reviewer/admin accounts are provisioned separately.")
        with st.form("register_form"):
            new_username = st.text_input("Choose a username")
            new_password = st.text_input("Choose a password", type="password")
            confirm_password = st.text_input("Confirm password", type="password")
            register = st.form_submit_button("Register")
        if register:
            if new_password != confirm_password:
                st.error("Passwords do not match.")
            else:
                try:
                    create_user(new_username, new_password, role="claimant")
                    st.success("Account created. Please log in.")
                except ValueError as e:
                    st.error(str(e))


if not st.session_state.user:
    render_login()
    st.stop()

user = st.session_state.user
role = user["role"]

st.sidebar.markdown(f"**Logged in as:** {user['username']} ({role})")
if st.sidebar.button("Log Out"):
    st.session_state.user = None
    st.session_state.pipeline_result = None
    st.session_state.claim_data = None
    st.rerun()

if role == "claimant":
    nav_options = ["Submit Claim", "My Claims"]
else:  # reviewer / admin
    nav_options = ["Pending Review", "All Claims", "Metrics Dashboard"]

page = st.sidebar.radio("Navigate", nav_options)

st.sidebar.markdown("### Policy Catalog")
for name, details in POLICIES.items():
    st.sidebar.markdown(
        f"**{name}** — Rs.{details['coverage_limit']:,} cover, "
        f"Rs.{details['premium']:,}/{details['frequency']}"
    )


# ==================================================================== Submit Claim (claimant)
if page == "Submit Claim":
    st.title("Health Insurance Claim Submission")

    with st.form("claim_form"):
        col1, col2 = st.columns(2)
        with col1:
            patient_name = st.text_input("Patient Name")
            patient_gender = st.selectbox("Patient Gender", ["Male", "Female", "Other"])
            policy_number = st.text_input("Policy Number")
            hospital_name = st.text_input("Hospital Name")
            diagnosis = st.text_input("Diagnosis / Disease")
            treatment = st.text_input("Treatment / Procedure")
        with col2:
            policy_name = st.selectbox("Policy Type", list(POLICIES.keys()))
            claim_amount = st.number_input("Claim Amount (Rs.)", min_value=0.0, step=1000.0)
            claim_date = st.date_input("Claim / Treatment Date")
            previous_claims = st.number_input("Number of Previous Claims", min_value=0, step=1)
            policy_start_date = st.date_input("Policy Start Date")
            last_premium_paid_date = st.date_input("Last Premium Paid Date")

        st.markdown("#### Document Verification")
        d1, d2, d3 = st.columns(3)
        with d1:
            hospital_bill = st.checkbox("Hospital Bill Verified")
            discharge_summary = st.checkbox("Discharge Summary Verified")
        with d2:
            diagnostic_reports = st.checkbox("Diagnostic Reports Verified")
            prescription = st.checkbox("Prescription Verified")
        with d3:
            patient_identity_proof = st.checkbox("Patient Identity Proof Verified")
            policy_copy = st.checkbox("Policy Copy Verified")

        st.markdown("#### Hospital Bill Upload (optional)")
        caps = extraction_capabilities()
        if not caps["image_ocr"]:
            st.caption(
                "⚠️ OCR for scanned images/PDFs isn't available on this server "
                "(Tesseract not installed) -- PDF files with embedded text are still supported."
            )
        bill_file = st.file_uploader("Upload hospital bill for automated cross-check", type=["pdf", "png", "jpg", "jpeg"])

        submitted = st.form_submit_button("Submit Claim")

    if submitted:
        claim_data = {
            "patient_name": patient_name,
            "patient_gender": patient_gender,
            "policy_number": policy_number,
            "policy_name": policy_name,
            "hospital_name": hospital_name,
            "diagnosis": diagnosis,
            "treatment": treatment,
            "claim_amount": claim_amount,
            "claim_date": str(claim_date),
            "previous_claims": previous_claims,
            "policy_start_date": str(policy_start_date),
            "last_premium_paid_date": str(last_premium_paid_date),
            "documents": {
                "hospital_bill": "yes" if hospital_bill else "no",
                "discharge_summary": "yes" if discharge_summary else "no",
                "diagnostic_reports": "yes" if diagnostic_reports else "no",
                "prescription": "yes" if prescription else "no",
                "patient_identity_proof": "yes" if patient_identity_proof else "no",
                "policy_copy": "yes" if policy_copy else "no",
            },
            "bill_upload": (
                {"bytes": bill_file.getvalue(), "filename": bill_file.name} if bill_file else None
            ),
        }

        with st.spinner("Processing your claim -- this may take a minute..."):
            result = run_pipeline(claim_data)

        claim_id = save_claim({
            **claim_data,
            "rules_result": result["rules_result"],
            "fraud_signals": result["fraud_signals"],
            "bill_verification": result["bill_verification"],
            "agent_results": result["agent_results"],
            "recommendation": result["recommendation"],
            "trace": result["trace"],
            "status": "pending_review",
            "created_at": result["created_at"],
            "submitted_by": user["username"],
        })

        st.success(
            f"Claim submitted successfully. Claim ID: **{claim_id}**\n\n"
            "It is now awaiting review. Check 'My Claims' for status updates."
        )

# ==================================================================== My Claims (claimant)
elif page == "My Claims":
    st.title("My Claims")
    claims = list_claims_by_submitter(user["username"])

    if not claims:
        st.info("You haven't submitted any claims yet.")
    else:
        for c in claims:
            status_label = c["status"].replace("_", " ").upper()
            with st.expander(f"{c['created_at']} — {c['hospital_name']} — {status_label} (Rs.{c['claim_amount']:,.0f})"):
                st.write(f"**Claim ID:** {c['claim_id']}")
                st.write(f"**Diagnosis:** {c['diagnosis']}  |  **Policy:** {c['policy_name']}")
                st.write(f"**Status:** {status_label}")
                if c["status"] == "pending_review":
                    st.info("Your claim is awaiting review. No decision has been made yet.")
                else:
                    st.write(f"**Decided:** {c['decided_at']}")
                    st.markdown("**Notification:**")
                    st.markdown(c["final_output"])

# ==================================================================== Pending Review (reviewer/admin)
elif page == "Pending Review":
    st.title("Pending Review")
    pending = list_pending_claims()

    if not pending:
        st.info("No claims awaiting review.")
    else:
        for c in pending:
            with st.expander(f"{c['created_at']} — {c['patient_name']} — {c['policy_name']} (Rs.{c['claim_amount']:,.0f})"):
                st.write(f"**Claim ID:** {c['claim_id']}  |  **Submitted by:** {c['submitted_by']}")
                st.write(f"**Hospital:** {c['hospital_name']}  |  **Diagnosis:** {c['diagnosis']}")

                r1, r2, r3 = st.columns(3)
                r1.metric("Fraud Risk", c["fraud_risk_score"] or "UNKNOWN")
                r2.metric("Insurance Payable", f"Rs.{(c['insurance_payable'] or 0):,.0f}")
                r3.metric("Patient Payable", f"Rs.{(c['patient_payable'] or 0):,.0f}")

                st.markdown("**Reviewer Recommendation:**")
                st.markdown(c["recommendation"])

                with st.expander("Full Agent Trace (audit log)"):
                    st.text(c["trace"])

                with st.form(f"review_form_{c['claim_id']}"):
                    decision_label = st.radio("Final Decision", ["Approve", "Reject"], key=f"decision_{c['claim_id']}")
                    reason = st.text_area("Reason / notes (optional)", key=f"reason_{c['claim_id']}")
                    decide = st.form_submit_button("Confirm Decision")

                if decide:
                    decision = "yes" if decision_label == "Approve" else "no"
                    final_output = execute(decision, c["recommendation"])
                    finalize_claim(c["claim_id"], decision, final_output, user["username"], reason)
                    st.success(f"Claim {c['claim_id']} {'approved' if decision == 'yes' else 'rejected'}.")
                    st.rerun()

# ==================================================================== All Claims (reviewer/admin)
elif page == "All Claims":
    st.title("All Claims")
    claims = list_claims()

    if not claims:
        st.info("No claims submitted yet.")
    else:
        for c in claims:
            risk = c.get("fraud_risk_score") or "UNKNOWN"
            status_label = c["status"].replace("_", " ").upper()
            with st.expander(
                f"{c['created_at']} — {c['patient_name']} — {c['policy_name']} — "
                f"{status_label} (Rs.{c['claim_amount']:,.0f}) — Fraud Risk: {risk}"
            ):
                st.write(f"**Claim ID:** {c['claim_id']}")
                st.write(f"**Submitted by:** {c['submitted_by'] or 'N/A'}  |  **Reviewed by:** {c['reviewed_by'] or 'N/A'}")
                st.write(f"**Hospital:** {c['hospital_name']}  |  **Diagnosis:** {c['diagnosis']}")
                st.write(f"**Status:** {status_label}")
                if c.get("decision_reason"):
                    st.write(f"**Decision Reason:** {c['decision_reason']}")
                st.markdown("**Recommendation:**")
                st.markdown(c["recommendation"])
                if c["status"] != "pending_review":
                    st.markdown("**Final Notification:**")
                    st.markdown(c["final_output"])

# ==================================================================== Metrics Dashboard (reviewer/admin)
else:
    st.title("Metrics Dashboard")
    metrics = get_metrics_summary()

    if metrics["total_claims"] == 0:
        st.info("No claims submitted yet -- submit a claim to populate the dashboard.")
    else:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total Claims", metrics["total_claims"])
        m2.metric("Pending Review", metrics["pending_count"])
        m3.metric("Approval Rate", f"{metrics['approval_rate']:.0f}%")
        m4.metric("Avg Claim Amount", f"Rs.{metrics['avg_claim_amount']:,.0f}")
        m5.metric("High Fraud-Risk Claims", metrics["high_risk_count"])

        p1, p2 = st.columns(2)
        p1.metric("Total Insurance Payable (Approved)", f"Rs.{metrics['total_insurance_payable']:,.0f}")
        p2.metric("Total Patient Payable (Approved)", f"Rs.{metrics['total_patient_payable']:,.0f}")

        st.subheader("Claims by Status")
        status_df = pd.DataFrame(
            {
                "Status": ["Approved", "Rejected", "Pending Review"],
                "Count": [metrics["approved_count"], metrics["rejected_count"], metrics["pending_count"]],
            }
        ).set_index("Status")
        st.bar_chart(status_df)

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Claims by Policy Type")
            if metrics["claims_by_policy"]:
                policy_df = pd.DataFrame(
                    list(metrics["claims_by_policy"].items()), columns=["Policy", "Count"]
                ).set_index("Policy")
                st.bar_chart(policy_df)

        with col_b:
            st.subheader("Claims by Fraud Risk")
            if metrics["claims_by_fraud_risk"]:
                risk_df = pd.DataFrame(
                    list(metrics["claims_by_fraud_risk"].items()), columns=["Risk", "Count"]
                ).set_index("Risk")
                st.bar_chart(risk_df)
