"""
Lightweight username/password auth with roles, backed by SQLite.

Scoped deliberately small for this project's size: no OAuth/SSO/session
tokens, just salted-hash password storage and a role column. Claimants
can self-register; reviewer/admin accounts are seeded, not
self-registerable, so a claimant can never grant themselves review
authority.
"""

import hashlib
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "claims.db"

ROLES = ("claimant", "reviewer", "admin")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def _hash_password(password: str, salt: bytes = None) -> tuple:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return digest.hex(), salt.hex()


def create_user(username: str, password: str, role: str = "claimant") -> None:
    if role not in ROLES:
        raise ValueError(f"Invalid role: {role}")
    if not username or not password:
        raise ValueError("Username and password are required.")

    init_auth_db()
    conn = _connect()
    existing = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        conn.close()
        raise ValueError(f"Username '{username}' is already taken.")

    password_hash, salt = _hash_password(password)
    conn.execute(
        "INSERT INTO users (username, password_hash, salt, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (username, password_hash, salt, role, str(datetime.now())),
    )
    conn.commit()
    conn.close()


def verify_login(username: str, password: str) -> dict:
    """Returns {"username": ..., "role": ...} on success, None on failure."""
    init_auth_db()
    conn = _connect()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not row:
        return None

    computed_hash, _ = _hash_password(password, bytes.fromhex(row["salt"]))
    if computed_hash != row["password_hash"]:
        return None

    return {"username": row["username"], "role": row["role"]}


def seed_default_accounts() -> None:
    """
    Idempotently seeds one reviewer and one admin account so the app is
    usable out of the box. Prints credentials once to the console so
    whoever runs it can log in and change them.
    """
    init_auth_db()
    conn = _connect()
    existing = {row[0] for row in conn.execute("SELECT username FROM users").fetchall()}
    conn.close()

    defaults = [
        ("reviewer1", "reviewer123", "reviewer"),
        ("admin", "admin123", "admin"),
    ]
    created = []
    for username, password, role in defaults:
        if username not in existing:
            create_user(username, password, role)
            created.append((username, password, role))

    if created:
        print("\n===== SEEDED DEFAULT ACCOUNTS (change these passwords) =====")
        for username, password, role in created:
            print(f"  {role.upper():9s} username={username!r:15s} password={password!r}")
        print("==============================================================\n")
