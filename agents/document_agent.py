from agent import ask

def document_check(claim, bill_verification=None):
    """
    bill_verification (from document_engine.verify_bill) contains the
    actual extracted bill total cross-checked against the claimed
    amount -- when available, this is real evidence instead of a
    self-reported "verified: yes" checkbox.
    """
    bill_was_uploaded = bool(bill_verification)

    if bill_was_uploaded:
        evidence = f"\n\nUPLOADED BILL VERIFICATION (extracted from the actual document):\n{bill_verification}"
        bill_instruction = """
        A bill WAS uploaded and cross-checked. For the Hospital Bill line
        item specifically, use the UPLOADED BILL VERIFICATION evidence's
        "status" field as authoritative:
          - status MATCH -> report Hospital Bill as "Verified (matches uploaded bill)"
          - status MISMATCH -> report Hospital Bill as "Verified (checkbox), but MISMATCH
            with uploaded bill" and call it out as a document risk with the amounts involved
          - status "COULD NOT VERIFY" -> report Hospital Bill as "Verified (checkbox), but
            uploaded bill could not be automatically cross-checked"
        Do NOT say "no bill was uploaded" -- one was.
        """
    else:
        evidence = "\n\nUPLOADED BILL VERIFICATION: No document was uploaded for automated cross-check."
        bill_instruction = """
        No bill was uploaded for cross-check. For the Hospital Bill line item,
        report only "Verified" or "Not Verified" based on the self-reported
        checkbox in the claim text, and note that no uploaded document was
        available to cross-check the amount. Do NOT use the words MATCH,
        MISMATCH, or "could not verify" anywhere -- those terms describe
        actual extracted evidence, which does not exist in this case.
        """

    return ask(
        f"""
        You are a Document Verification Agent.

        Verify:

        - Hospital Bills
        - Discharge Summary
        - Prescriptions
        - Diagnostic Reports
        - Patient Identity Proof

        For Discharge Summary, Diagnostic Reports, Prescription, Patient
        Identity Proof, and Policy Copy: report only "Verified" or
        "Not Verified" based on the self-reported checkbox in the claim text.

        For the Hospital Bill specifically: {bill_instruction}

        Return document verification report.
        """,
        claim + evidence
    )
