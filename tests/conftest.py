"""
Shared pytest fixtures.

The store module keeps a module-level DB_PATH pointing at the real
claims.db. Tests must never touch that file, so `isolated_db` points
DB_PATH at a throwaway SQLite file for the duration of each test.
Because store.py's functions look up `DB_PATH` as a global at call
time (not at import time), monkeypatching the attribute is enough --
no need to reload the module.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import store  # noqa: E402


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Points store.DB_PATH at a fresh temp SQLite file for this test only."""
    test_db_path = tmp_path / "test_claims.db"
    monkeypatch.setattr(store, "DB_PATH", test_db_path)
    store.init_db()
    yield store
