from agent import ask

def execute(decision, results):

    decision = decision.strip().lower()

    if decision == "yes":

        return ask(
            """
            You are an Insurance Claims Notification Agent.

            The Human Reviewer has APPROVED the claim.

            Generate ONLY a claim approval email.

            Extract:
            - Patient Name
            - Policy Type
            - Coverage Limit
            - Claim Amount
            - Insurance Payable
            - Patient Payable
            - Settlement Type

            Format:

            Subject: Claim Approval Notification

            Dear <Patient Name>,

            We are pleased to inform you that your
            insurance claim has been approved.

            Include the settlement summary.

            Mention:
            - Claim Amount
            - Coverage Limit
            - Insurance Payable
            - Patient Payable
            - Settlement Type

            Contact Information:

            Phone: 1234567890
            Email: customer.support@upayuliv.com

            Signature:

            Snape
            AI Engineer
            Upay Uliv

            Do NOT generate any rejection content.
            and include transaction details and ID.
            """,
            str(results)
        )

    return ask(
        """
        You are an Insurance Claims Notification Agent.

        The Human Reviewer has REJECTED the claim.

        Generate ONLY a rejection email.

        Include the rejection reason.

        Contact Information:

        Phone: 1234567890
        Email: customer.support@upayuliv.com

        Signature:

        Snape
        AI Engineer
        Upay Uliv

        Do NOT generate any approval content.
        GIVE SHORT AND CONCISE ANSWERS.
        """,
        str(results)
    )