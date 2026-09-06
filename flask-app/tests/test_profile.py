"""
Profile endpoint tests: GET/PUT/DELETE /api/auth/profile.

Covers auth enforcement, user field shape, prediction history,
display-name updates, and full account deletion.
"""

from database import get_user_by_email, save_prediction


def _signup(client, username, email=None):
    return client.post("/api/auth/signup", json={
        "username": username,
        "email": email or f"{username}@example.com",
        "password": "supersecret123",
    })


# ── GET /api/auth/profile ─────────────────────────────────────────────────

def test_get_profile_requires_auth(client):
    res = client.get("/api/auth/profile")
    assert res.status_code == 401


def test_get_profile_returns_user_fields(client):
    _signup(client, "profa")
    res = client.get("/api/auth/profile")
    assert res.status_code == 200
    user = res.get_json()["user"]
    assert user["username"] == "profa"
    assert user["email"] == "profa@example.com"
    assert user["id"]


def test_get_profile_empty_history(client):
    _signup(client, "profb")
    body = client.get("/api/auth/profile").get_json()
    assert body["predictions"] == []


def test_get_profile_includes_prediction_history(client):
    _signup(client, "profc")
    user = get_user_by_email("profc@example.com")
    save_prediction(user["id"], 2024, '{"grid": []}')
    save_prediction(user["id"], 2025, '{"grid": []}', points_system="classic")

    body = client.get("/api/auth/profile").get_json()
    seasons = [p["season"] for p in body["predictions"]]
    assert seasons == [2025, 2024]  # ordered newest season first

    p2025 = body["predictions"][0]
    assert p2025["pointsSystem"] == "classic"
    assert "locked" in p2025
    assert "accuracyScore" in p2025
    assert "createdAt" in p2025
    assert "updatedAt" in p2025


# ── PUT /api/auth/profile ─────────────────────────────────────────────────

def test_update_profile_requires_auth(client):
    res = client.put("/api/auth/profile", json={"displayName": "Nope"})
    assert res.status_code == 401


def test_update_profile_success(client):
    _signup(client, "profd")
    res = client.put("/api/auth/profile", json={"displayName": "Speed Queen"})
    assert res.status_code == 200
    assert res.get_json()["displayName"] == "Speed Queen"

    body = client.get("/api/auth/profile").get_json()
    assert body["user"]["displayName"] == "Speed Queen"


def test_update_profile_rejects_blank_name(client):
    _signup(client, "profe")
    for bad in ("", "   "):
        res = client.put("/api/auth/profile", json={"displayName": bad})
        assert res.status_code == 400


def test_update_profile_rejects_missing_name(client):
    _signup(client, "proff")
    res = client.put("/api/auth/profile", json={})
    assert res.status_code == 400


# ── DELETE /api/auth/profile ──────────────────────────────────────────────

def test_delete_account_requires_auth(client):
    res = client.delete("/api/auth/profile")
    assert res.status_code == 401


def test_delete_account_kills_session_and_login(client):
    _signup(client, "profg")
    assert client.get("/api/auth/me").status_code == 200

    res = client.delete("/api/auth/profile")
    assert res.status_code == 200

    # Session is invalidated and the account can no longer log in
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={
        "username": "profg", "password": "supersecret123",
    }).status_code == 401
