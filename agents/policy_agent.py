from agent import ask
from rules_engine import POLICIES


def get_policy_info(policy_name):
    """Pure lookup -- no I/O, safe to call from CLI or Streamlit."""
    return {
        "policy_name": policy_name,
        "coverage_limit": POLICIES[policy_name]["coverage_limit"],
        "premium": POLICIES[policy_name]["premium"],
        "frequency": POLICIES[policy_name]["frequency"],
        "waiting_period_days": POLICIES[policy_name]["waiting_period_days"],
    }


def verify_policy(policy_name, coverage_limit, policy_status_hint=""):
    """
    Ask the LLM to summarize policy verification. policy_status_hint
    (e.g. "ACTIVE"/"LAPSED"/"GRACE") comes from the deterministic
    rules engine -- the LLM is told the status, not asked to guess it.
    """
    return ask(
        """
        You are an Insurance Policy Verification Agent.

        Verify the selected policy and return:

        Policy Type
        Coverage Limit
        Policy Status
        Eligibility

        Use the Policy Status provided in the input exactly as given.
        Do NOT assume the policy is active -- rely only on the status supplied.
        GIVE SHORT AND CONCISE ANSWERS.
        """,
        f"Policy Type: {policy_name}\nCoverage Limit: {coverage_limit}\n"
        f"Policy Status: {policy_status_hint or 'UNKNOWN'}"
    )


def policy_check_cli():
    """CLI-only helper that collects the policy choice via input()."""
    print("\n===== POLICY SELECTION =====\n")
    for i, (policy, details) in enumerate(POLICIES.items(), start=1):
        print(f"{i}. {policy} - Coverage: Rs.{details['coverage_limit']:,} "
              f"| Premium: Rs.{details['premium']:,}/{details['frequency']}")

    choice = int(input("\nSelect Policy (1-5): "))
    policy_name = list(POLICIES.keys())[choice - 1]
    return get_policy_info(policy_name)
