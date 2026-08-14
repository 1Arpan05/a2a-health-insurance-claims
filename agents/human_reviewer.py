def human_review_cli(review):
    """CLI-only helper -- collects the decision via input()."""
    print("\n========== HUMAN REVIEW ==========\n")
    decision = input("\nFinal Decision (yes/no): ").strip().lower()
    reason = input("Reason / notes (optional): ").strip()
    return decision, reason


def record_human_decision(decision: str, reason: str = ""):
    """Pure helper -- normalizes a decision coming from any UI (CLI, Streamlit)."""
    decision = (decision or "").strip().lower()
    if decision not in ("yes", "no"):
        raise ValueError("decision must be 'yes' or 'no'")
    return decision, reason
