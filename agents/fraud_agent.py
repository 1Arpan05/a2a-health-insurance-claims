from agent import ask

def fraud_check(claim, fraud_signals=None):
    """
    fraud_signals (from fraud_engine.compute_fraud_signals) contains
    deterministic evidence computed from real claim history -- duplicate
    matches, claim velocity, amount outliers, early-claim risk, hospital
    rejection rate. The LLM explains this evidence rather than guessing
    at fraud indicators from a single claim with no data behind it.
    """
    evidence = f"\n\nFRAUD ENGINE EVIDENCE (deterministic, computed from claim history):\n{fraud_signals}" if fraud_signals else "\n\nFRAUD ENGINE EVIDENCE: none available (no historical data)."

    return ask(
        """
        You are a Fraud Detection Agent.

        A deterministic fraud engine has already scanned claim history
        for duplicate claims, claim velocity, amount outliers vs
        diagnosis, early large claims after policy inception, and
        hospital rejection-rate risk. Treat its risk_score and
        risk_flags as authoritative evidence -- do not invent
        additional fraud indicators beyond what's supported by the
        claim text and this evidence.

        Return:

        Risk Score: (LOW / MEDIUM / HIGH, matching the fraud engine's risk_score)
        Findings: (summarize each risk_flag in plain language; say "None" if no flags)
        Recommendation: (PASS if risk_score is LOW, FLAG FOR REVIEW if MEDIUM, FAIL if HIGH)

        GIVE SHORT AND CONCISE ANSWERS.
        """,
        claim + evidence
    )
