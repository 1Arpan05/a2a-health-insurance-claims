from agent import ask

def medical_check(claim):

    return ask(
        """
        You are a Medical Review Agent.

        Validate:

        - Diagnosis
        - Medical necessity
        - Treatment legitimacy
        - Hospitalization requirement

        Return medical assessment.
        GIVE SHORT AND CONCISE ANSWERS.
        """,
        claim
    )