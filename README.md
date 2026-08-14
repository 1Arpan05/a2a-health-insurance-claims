# Agent-to-Agent (A2A) Protocol

This project demonstrates planner, policy, damage, reviewer and executor agents communicating using a simple A2A protocol.

## Running of an Application:
1. pip install -r requirements.txt
2. add OPENAI_API_KEY to .env -> .env.example (Reference)
3. run python app.py (CLI) or `streamlit run streamlit_app.py` (web UI, role-based login)

## Running the test suite
1. pip install -r requirements-dev.txt
2. python -m pytest tests/ -v

The suite (101 tests) covers `rules_engine.py`, `fraud_engine.py`, and
`document_engine.py` with pure/deterministic tests (no mocking needed),
plus `pipeline.py` orchestration and the agent wrapper functions with
the LLM call (`agent.ask`) mocked out -- so the full suite runs in a
few seconds with zero API calls and zero cost, and never touches the
real `claims.db` (each test gets an isolated temp DB).


## Flowchart of the agents 

Claim Submission
      │
      ▼
Planner Agent
      │
      ├── Policy Agent
      │         │
      │         ▼
      │   Coverage Agent
      │
      ├── Fraud Agent
      ├── Medical Agent
      └── Document Agent
                │
                ▼
         Reviewer Agent
                │
                ▼
       Human Reviewer
          (Yes/No)
                │
                ▼
         Executor Agent
                │
                ▼
 Approved Payment /
 Claim Rejection Notice