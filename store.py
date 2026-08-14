"""
Persistent claim store (SQLite). Enables claim history, duplicate-claim
detection, and an audit trail across runs -- none of which is possible
when every run of the CLI is stateless.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "claims.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY,
            created_at TEXT,
            patient_name TEXT,
            policy_number TEXT,
            policy_name TEXT,
            hospital_name TEXT,
            diagnosis TEXT,
            claim_amount REAL,
            claim_date TEXT,
            rules_result TEXT,
            agent_results TEXT,
            recommendation TEXT,
            human_decision TEXT,
            final_output TEXT,
            trace TEXT,
            status TEXT,
            fraud_risk_score TEXT,
            fraud_flags TEXT,
            insurance_payable REAL,
            patient_payable REAL,
            bill_verification TEXT,
            submitted_by TEXT,
            reviewed_by TEXT,
            decision_reason TEXT,
            decided_at TEXT
        )
    """)
    # Backward-compatible migration for DBs created before these columns existed.
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(claims)").fetchall()}
    for col, col_type in [
        ("fraud_risk_score", "TEXT"),
        ("fraud_flags", "TEXT"),
        ("insurance_payable", "REAL"),
        ("patient_payable", "REAL"),
        ("bill_verification", "TEXT"),
        ("submitted_by", "TEXT"),
        ("reviewed_by", "TEXT"),
        ("decision_reason", "TEXT"),
        ("decided_at", "TEXT"),
    ]:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE claims ADD COLUMN {col} {col_type}")
    conn.commit()
    conn.close()


def save_claim(record: dict) -> str:
    """record is a dict of claim fields + results. Returns claim_id."""
    init_db()
    claim_id = record.get("claim_id") or str(uuid.uuid4())
    settlement = (record.get("rules_result") or {}).get("settlement", {})
    fraud_signals = record.get("fraud_signals") or {}
    conn = _connect()
    conn.execute("""
        INSERT INTO claims (
            claim_id, created_at, patient_name, policy_number, policy_name,
            hospital_name, diagnosis, claim_amount, claim_date,
            rules_result, agent_results, recommendation, human_decision,
            final_output, trace, status, fraud_risk_score, fraud_flags,
            insurance_payable, patient_payable, bill_verification,
            submitted_by, reviewed_by, decision_reason, decided_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        claim_id,
        record.get("created_at") or str(datetime.now()),
        record.get("patient_name"),
        record.get("policy_number"),
        record.get("policy_name"),
        record.get("hospital_name"),
        record.get("diagnosis"),
        record.get("claim_amount"),
        record.get("claim_date"),
        json.dumps(record.get("rules_result", {})),
        json.dumps(record.get("agent_results", {})),
        record.get("recommendation", ""),
        record.get("human_decision", ""),
        record.get("final_output", ""),
        json.dumps(record.get("trace", [])),
        record.get("status", "pending"),
        fraud_signals.get("risk_score", "UNKNOWN"),
        json.dumps(fraud_signals.get("risk_flags", [])),
        settlement.get("insurance_payable"),
        settlement.get("patient_payable"),
        json.dumps(record.get("bill_verification")) if record.get("bill_verification") else None,
        record.get("submitted_by"),
        record.get("reviewed_by"),
        record.get("decision_reason"),
        record.get("decided_at"),
    ))
    conn.commit()
    conn.close()
    return claim_id


def update_claim(claim_id: str, **fields):
    init_db()
    conn = _connect()
    for key, value in fields.items():
        if key in ("rules_result", "agent_results", "trace"):
            value = json.dumps(value)
        conn.execute(f"UPDATE claims SET {key} = ? WHERE claim_id = ?", (value, claim_id))
    conn.commit()
    conn.close()


def get_claim(claim_id: str) -> dict:
    init_db()
    conn = _connect()
    row = conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_claims(limit: int = 100) -> list:
    init_db()
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM claims ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_claims_by_submitter(username: str, limit: int = 100) -> list:
    """Claimant-facing view: only claims they personally submitted."""
    init_db()
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM claims WHERE submitted_by = ? ORDER BY created_at DESC LIMIT ?",
        (username, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_pending_claims(limit: int = 100) -> list:
    """Reviewer queue: claims awaiting a human decision."""
    init_db()
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM claims WHERE status = 'pending_review' ORDER BY created_at ASC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def finalize_claim(claim_id: str, decision: str, final_output: str, reviewed_by: str, reason: str = "") -> None:
    """Records a reviewer's Approve/Reject decision against a pending claim."""
    update_claim(
        claim_id,
        status="approved" if decision == "yes" else "rejected",
        human_decision=decision,
        final_output=final_output,
        reviewed_by=reviewed_by,
        decision_reason=reason,
        decided_at=str(datetime.now()),
    )


def find_possible_duplicates(patient_name: str, hospital_name: str, claim_amount: float) -> list:
    """Simple duplicate-claim heuristic used by the fraud agent."""
    init_db()
    conn = _connect()
    rows = conn.execute("""
        SELECT * FROM claims
        WHERE patient_name = ? AND hospital_name = ? AND ABS(claim_amount - ?) < 1
    """, (patient_name, hospital_name, claim_amount)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def claims_by_patient_since(patient_name: str, since_date: str) -> list:
    """Claim velocity: how many claims has this patient filed recently (any hospital)."""
    init_db()
    conn = _connect()
    rows = conn.execute("""
        SELECT * FROM claims WHERE patient_name = ? AND created_at >= ?
        ORDER BY created_at DESC
    """, (patient_name, since_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def diagnosis_amount_stats(diagnosis: str, exclude_claim_id: str = None) -> dict:
    """Average/max historical claim amount for a given diagnosis, used to flag outliers."""
    init_db()
    conn = _connect()
    query = "SELECT claim_amount FROM claims WHERE diagnosis = ?"
    params = [diagnosis]
    if exclude_claim_id:
        query += " AND claim_id != ?"
        params.append(exclude_claim_id)
    rows = [r[0] for r in conn.execute(query, params).fetchall() if r[0] is not None]
    conn.close()
    if not rows:
        return {"count": 0, "avg": None, "max": None}
    return {"count": len(rows), "avg": sum(rows) / len(rows), "max": max(rows)}


def hospital_claim_stats(hospital_name: str) -> dict:
    """Basic per-hospital volume + rejection-rate stats, used as a fraud signal."""
    init_db()
    conn = _connect()
    rows = conn.execute(
        "SELECT status FROM claims WHERE hospital_name = ?", (hospital_name,)
    ).fetchall()
    conn.close()
    total = len(rows)
    rejected = sum(1 for r in rows if r[0] == "rejected")
    return {
        "total_claims": total,
        "rejected_claims": rejected,
        "rejection_rate": (rejected / total) if total else 0.0,
    }


def get_metrics_summary() -> dict:
    """Aggregate stats for the dashboard."""
    init_db()
    conn = _connect()
    rows = conn.execute("SELECT * FROM claims").fetchall()
    conn.close()
    claims = [dict(r) for r in rows]

    total = len(claims)
    approved = [c for c in claims if c["status"] == "approved"]
    rejected = [c for c in claims if c["status"] == "rejected"]
    pending = [c for c in claims if c["status"] == "pending_review"]
    decided_count = len(approved) + len(rejected)

    total_claim_amount = sum(c["claim_amount"] or 0 for c in claims)
    total_insurance_payable = sum(c["insurance_payable"] or 0 for c in approved)
    total_patient_payable = sum(c["patient_payable"] or 0 for c in approved)

    by_policy = {}
    for c in claims:
        by_policy[c["policy_name"]] = by_policy.get(c["policy_name"], 0) + 1

    by_risk = {}
    for c in claims:
        risk = c["fraud_risk_score"] or "UNKNOWN"
        by_risk[risk] = by_risk.get(risk, 0) + 1

    return {
        "total_claims": total,
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "pending_count": len(pending),
        "approval_rate": (len(approved) / decided_count * 100) if decided_count else 0.0,
        "avg_claim_amount": (total_claim_amount / total) if total else 0.0,
        "total_insurance_payable": total_insurance_payable,
        "total_patient_payable": total_patient_payable,
        "claims_by_policy": by_policy,
        "claims_by_fraud_risk": by_risk,
        "high_risk_count": by_risk.get("HIGH", 0),
    }
