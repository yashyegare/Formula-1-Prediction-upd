"""
Pytest fixtures for the auth flow tests.

Every test gets:
  - A throwaway SQLite DB in a temp directory (F1_DB_PATH)
  - A Flask app client with the real blueprints and real rate limits
  - flask-limiter's in-memory storage cleared between tests
"""

import os
import tempfile

import pytest

# Must be set BEFORE importing app/database so they pick up the temp paths.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only")
TMP_DIR = tempfile.mkdtemp(prefix="f1_test_")
os.environ["F1_DB_PATH"] = os.path.join(TMP_DIR, "test_f1_data.db")

# Import after env vars are set
from app import app as flask_app  # noqa: E402
from extensions import limiter  # noqa: E402
from database import init_db, get_connection  # noqa: E402


def _reset_rate_limits():
    try:
        limiter.reset()
    except Exception:
        storage = getattr(limiter, "_storage", None)
        if storage is not None and hasattr(storage, "clear"):
            storage.clear()


@pytest.fixture()
def client():
    """Fresh app client per test: clean rate limits, re-init schema, wipe users."""
    _reset_rate_limits()
    init_db()
    with flask_app.test_client() as c:
        yield c
    with get_connection() as conn:
        conn.execute("DELETE FROM users")
        conn.commit()
