from agent import ask

def planner(claim):

    return ask(
        """
        You are a Healthcare Claim Planner Agent.

        Analyze the healthcare insurance claim and
        coordinate the review process.

        Explain which agents should review the claim.
        GIVE SHORT AND CONCISE ANSWERS.
        """,
        claim
    )
