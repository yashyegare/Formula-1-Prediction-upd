"""
Injection-regression tests for update_user_profile().

update_user_profile() builds its UPDATE clause dynamically from optional
kwargs. Today every value goes through a parameterized placeholder and the
column list is a fixed allowlist — but a refactor could reintroduce f-string
interpolation of user data into the SQL text, and there was no test to catch
it. These tests pin the contract:

  1. Hostile strings are stored as LITERAL data (parameterized), never
     interpreted as SQL — the stored value round-trips byte-for-byte.
  2. The column set is closed: display_name and avatar_url only.
  3. HTTP surface: PUT /api/auth/profile with hostile JSON payloads must
     succeed storing literal data or 400 — never 500, never SQL effects.

Run against BOTH backends by CI (SQLite + PostgreSQL).
"""

import json

import pytest

from database import (
    create_user,
    get_user_by_email,
    get_connection,
    _fetchone,
    _is_pg,
    update_user_profile,
)

HOSTILE_PAYLOADS = [
    # Classic break-out attempts
    "alice', avatar_url='https://evil.example/x.png",
    'alice"; DROP TABLE users;--',
    # Multi-statement smuggling
    "bob'; DELETE FROM predictions;--",
    # Comment / UNION tricks
    "carol' --",
    "dave' UNION SELECT email, password_hash FROM users;--",
    # Column-name smuggling: try to set a column the allowlist doesn't expose
    "eve = 1, password_hash = 'pwned",
    # Reset-token tampering via value text
    "frank', reset_token='deadbeef', reset_token_expires='2099-01-01",
    # Odd but legal unicode/emoji names (must round-trip unharmed)
    "赵妮可 🏎️",
    "O'Brien \"The\\Legend\"",  # quotes + backslash soup
]


def _mk_user(name: str) -> int:
    suffix = str(abs(hash(name)) % 10**8)
    email = f"inj{suffix}@example.com"
    create_user(f"inj_u_{suffix}", email, "x" * 32, name)
    return get_user_by_email(email)["id"]


def _row_for(user_id: int, sql: str, params: tuple = ()) -> dict:
    ph = "%s" if _is_pg() else "?"
    with get_connection() as conn:
        return _fetchone(conn, sql.replace("PH", ph), (user_id, *params))


# ── Direct database-layer contract ───────────────────────────────────────────

@pytest.mark.parametrize("hostile", HOSTILE_PAYLOADS)
def test_hostile_display_name_stored_as_literal(hostile):
    user_id = _mk_user(hostile[:12].replace(" ", "") or "blank")

    # The function itself must never raise on hostile input.
    update_user_profile(user_id, display_name=hostile)

    row = _row_for(user_id, "SELECT display_name FROM users WHERE id = PH")
    assert row["display_name"] == hostile  # byte-for-byte literal round-trip


def test_users_table_survives_drop_table_attempt():
    """The classic '; DROP TABLE users;--' payload must leave the table intact."""
    user_id = _mk_user("droptable")
    update_user_profile(user_id, display_name="x'; DROP TABLE users;--")

    with get_connection() as conn:
        row = _fetchone(conn, "SELECT COUNT(*) AS n FROM users", ())
    assert row["n"] >= 1


def test_password_hash_cannot_be_set_via_display_name():
    user_id = _mk_user("smuggler")
    update_user_profile(
        user_id,
        display_name="x', password_hash='attacker-controlled-hash",
    )
    row = _row_for(
        user_id,
        "SELECT display_name, password_hash FROM users WHERE id = PH",
    )
    # Literal data everywhere: no column beyond display_name was touched.
    assert row["display_name"].startswith("x', password_hash=")
    assert row["password_hash"] == "x" * 32  # unchanged


def test_dynamic_builder_only_sets_requested_columns():
    user_id = _mk_user("shape")
    before = _row_for(user_id, "SELECT * FROM users WHERE id = PH")
    update_user_profile(user_id, avatar_url="https://example.com/a.png")
    after = _row_for(user_id, "SELECT * FROM users WHERE id = PH")

    assert after["avatar_url"] == "https://example.com/a.png"
    for col in before.keys():
        if col in ("avatar_url", "display_name"):
            continue
        assert before[col] == after[col], f"unexpected mutation of column {col!r}"


def test_update_with_no_fields_is_a_noop():
    user_id = _mk_user("noop")
    before = _row_for(user_id, "SELECT * FROM users WHERE id = PH")
    update_user_profile(user_id)  # nothing to set → early return, no crash
    after = _row_for(user_id, "SELECT * FROM users WHERE id = PH")
    assert dict(before) == dict(after)


# ── HTTP surface: PUT /api/auth/profile ──────────────────────────────────────

def _signup(client, username):
    res = client.post("/api/auth/signup", json={
        "username": username,
        "email": f"{username}@example.com",
        "password": "supersecret123",
    })
    assert res.status_code == 201
    return res


@pytest.mark.parametrize("hostile", HOSTILE_PAYLOADS)
def test_put_profile_hostile_names_never_500_or_corrupt(client, hostile):
    _signup(client, "httpuser")

    res = client.put(
        "/api/auth/profile",
        data=json.dumps({"displayName": hostile}),
        content_type="application/json",
    )
    # Literal storage (200) or input validation (400) are both acceptable;
    # a 500 means the SQL layer choked on the value.
    assert res.status_code in (200, 400), res.get_data(as_text=True)

    if res.status_code == 200:
        body = client.get("/api/auth/profile").get_json()
        assert body["user"]["displayName"] == hostile


def test_put_profile_json_injection_types_rejected(client):
    """Non-string JSON types must be rejected, not coerced into SQL."""
    _signup(client, "jsonuser")
    for bad in [{"displayName": {"$gt": ""}}, {"displayName": ["a"]}, {"displayName": None}]:
        res = client.put(
            "/api/auth/profile",
            data=json.dumps(bad),
            content_type="application/json",
        )
        assert res.status_code == 400


def test_put_profile_unauthenticated_is_401_json(client):
    res = client.put(
        "/api/auth/profile",
        data=json.dumps({"displayName": "x"}),
        content_type="application/json",
    )
    assert res.status_code == 401
    assert res.is_json  # JSON 401, not the historic HTML redirect
