from agent import ask

def coverage_check(claim, rules_result=None):
    """
    rules_result (from rules_engine.evaluate_claim) already contains the
    authoritative settlement math and any hard-reject reasons (lapsed
    policy, claim predating the policy). The LLM restates it clearly
    rather than recomputing it.
    """
    evidence = f"\n\nDETERMINISTIC RULES ENGINE OUTPUT (authoritative, do not override):\n{rules_result}" if rules_result else ""

    return ask(
        """
        You are a Healthcare Coverage Agent.

        A deterministic rules engine has already computed the settlement
        math and any hard-reject conditions (e.g. policy lapsed, claim
        date before policy start / within waiting period). Treat that
        output as ground truth -- do not recompute or contradict it.

        Business Rules:

        - Claims should not be rejected simply because
          the claim amount exceeds policy coverage.
        - Insurance Payable = min(Claim Amount, Coverage Limit)
        - Patient Payable = Claim Amount - Insurance Payable
        - If the rules engine flags a hard reject, report Settlement
          Type as REJECTED and state the reason from the rules engine.

        Return:

        Policy Type:
        Coverage Limit:
        Claim Amount:
        Insurance Payable:
        Patient Payable:
        Settlement Type:

        GIVE SHORT AND CONCISE ANSWERS.
        """,
        claim + evidence
    )