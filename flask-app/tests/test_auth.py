"""
Auth flow tests.

Covers the four bugs fixed in production, plus validation, password reset,
and rate limiting:
  1. Cross-origin session cookies (SameSite=None; Secure)
  2. Login by email OR username
  3. Signup validation + duplicate rejection
  4. Password reset token flow (happy path + expiry)
"""

from datetime import datetime, timedelta
from unittest.mock import patch


# ── Signup ────────────────────────────────────────────────────────────────

def test_signup_success(client):
    res = client.post("/api/auth/signup", json={
        "username": "alice",
        "email": "alice@example.com",
        "password": "supersecret123",
    })
    assert res.status_code == 201
    body = res.get_json()
    assert body["user"]["username"] == "alice"
    assert body["user"]["email"] == "alice@example.com"


def test_signup_rejects_duplicate_username(client):
    payload = {
        "username": "bob",
        "email": "bob@example.com",
        "password": "supersecret123",
    }
    assert client.post("/api/auth/signup", json=payload).status_code == 201

    payload["email"] = "other@example.com"  # different email, same username
    res = client.post("/api/auth/signup", json=payload)
    assert res.status_code == 409
    assert "Username already taken" in res.get_json()["error"]


def test_signup_rejects_duplicate_email(client):
    payload = {
        "username": "carol",
        "email": "carol@example.com",
        "password": "supersecret123",
    }
    assert client.post("/api/auth/signup", json=payload).status_code == 201

    payload["username"] = "carol2"  # different username, same email
    res = client.post("/api/auth/signup", json=payload)
    assert res.status_code == 409
    assert "Email already registered" in res.get_json()["error"]


def test_signup_rejects_short_password(client):
    res = client.post("/api/auth/signup", json={
        "username": "dave", "email": "dave@example.com", "password": "short",
    })
    assert res.status_code == 400


def test_signup_rejects_bad_username(client):
    res = client.post("/api/auth/signup", json={
        "username": "bad name!", "email": "x@example.com", "password": "supersecret123",
    })
    assert res.status_code == 400


def test_signup_rejects_bad_email(client):
    res = client.post("/api/auth/signup", json={
        "username": "erin", "email": "not-an-email", "password": "supersecret123",
    })
    assert res.status_code == 400


# ── Login: username and email ─────────────────────────────────────────────

def test_login_by_username(client):
    client.post("/api/auth/signup", json={
        "username": "frank", "email": "frank@example.com", "password": "supersecret123",
    })
    res = client.post("/api/auth/login", json={
        "username": "frank", "password": "supersecret123",
    })
    assert res.status_code == 200
    assert res.get_json()["user"]["username"] == "frank"


def test_login_by_email(client):
    """Regression: get_user_by_email used to select no password_hash, which
    made email login crash with a 500."""
    client.post("/api/auth/signup", json={
        "username": "grace", "email": "grace@example.com", "password": "supersecret123",
    })
    res = client.post("/api/auth/login", json={
        "username": "grace@example.com", "password": "supersecret123",
    })
    assert res.status_code == 200
    assert res.get_json()["user"]["username"] == "grace"


def test_login_wrong_password(client):
    client.post("/api/auth/signup", json={
        "username": "heidi", "email": "heidi@example.com", "password": "supersecret123",
    })
    res = client.post("/api/auth/login", json={
        "username": "heidi", "password": "wrongpassword",
    })
    assert res.status_code == 401


def test_login_unknown_user(client):
    res = client.post("/api/auth/login", json={
        "username": "nobody", "password": "supersecret123",
    })
    assert res.status_code == 401


# ── Session / /api/auth/me ────────────────────────────────────────────────

def test_me_after_login(client):
    client.post("/api/auth/signup", json={
        "username": "ivan", "email": "ivan@example.com", "password": "supersecret123",
    })
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    assert res.get_json()["user"]["username"] == "ivan"


def test_me_without_login_returns_401(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401
    assert res.get_json()["user"] is None


def test_session_cookies_cross_origin_safe(client):
    """Regression: cookies must carry SameSite=None; Secure so the Vercel
    frontend can hold the session against the Render backend."""
    res = client.post("/api/auth/signup", json={
        "username": "judy", "email": "judy@example.com", "password": "supersecret123",
    })
    set_cookies = [h for h in res.headers.getlist("Set-Cookie") if h.startswith(("session=", "remember_token="))]
    assert set_cookies, "expected session cookies after signup"
    for cookie in set_cookies:
        assert "SameSite=None" in cookie, f"missing SameSite=None: {cookie}"
        assert "Secure" in cookie, f"missing Secure: {cookie}"


def test_logout_clears_session(client):
    client.post("/api/auth/signup", json={
        "username": "mallory", "email": "mallory@example.com", "password": "supersecret123",
    })
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


# ── Password reset ────────────────────────────────────────────────────────

def test_forgot_password_returns_token_for_existing_user(client):
    client.post("/api/auth/signup", json={
        "username": "peggy", "email": "peggy@example.com", "password": "supersecret123",
    })
    res = client.post("/api/auth/forgot-password", json={"email": "peggy@example.com"})
    assert res.status_code == 200
    body = res.get_json()
    assert body.get("token"), "expected a reset token for an existing account"


def test_forgot_password_does_not_reveal_unknown_email(client):
    res = client.post("/api/auth/forgot-password", json={"email": "ghost@example.com"})
    assert res.status_code == 200
    body = res.get_json()
    assert "message" in body
    assert "token" not in body, "unknown email must not get a reset token"


def test_full_password_reset_flow(client):
    client.post("/api/auth/signup", json={
        "username": "trent", "email": "trent@example.com", "password": "oldpassword1",
    })
    token = client.post(
        "/api/auth/forgot-password", json={"email": "trent@example.com"}
    ).get_json()["token"]

    res = client.post("/api/auth/reset-password", json={
        "token": token, "password": "newpassword1",
    })
    assert res.status_code == 200

    # Old password is dead, new one works
    assert client.post("/api/auth/login", json={
        "username": "trent@example.com", "password": "oldpassword1",
    }).status_code == 401
    assert client.post("/api/auth/login", json={
        "username": "trent@example.com", "password": "newpassword1",
    }).status_code == 200


def test_reset_token_is_single_use(client):
    client.post("/api/auth/signup", json={
        "username": "victor", "email": "victor@example.com", "password": "supersecret123",
    })
    token = client.post(
        "/api/auth/forgot-password", json={"email": "victor@example.com"}
    ).get_json()["token"]
    assert client.post("/api/auth/reset-password", json={
        "token": token, "password": "newpassword1",
    }).status_code == 200

    res = client.post("/api/auth/reset-password", json={
        "token": token, "password": "anotherpassword",
    })
    assert res.status_code == 400


def test_expired_reset_token_rejected(client):
    from database import get_user_by_email, set_reset_token

    client.post("/api/auth/signup", json={
        "username": "walter", "email": "walter@example.com", "password": "supersecret123",
    })
    user = get_user_by_email("walter@example.com")
    set_reset_token(user["id"], "expired-token",
                    (datetime.utcnow() - timedelta(hours=2)).isoformat())

    res = client.post("/api/auth/reset-password", json={
        "token": "expired-token", "password": "newpassword1",
    })
    assert res.status_code == 400


# ── Rate limiting ─────────────────────────────────────────────────────────

def test_login_rate_limited_after_10_attempts(client):
    for _ in range(10):
        client.post("/api/auth/login", json={
            "username": "ghost", "password": "whatever",
        })
    res = client.post("/api/auth/login", json={
        "username": "ghost", "password": "whatever",
    })
    assert res.status_code == 429
    # Must be JSON — the frontends call res.json() on every response and
    # flask-limiter's default HTML error page would crash them.
    assert res.is_json
    assert "try again" in res.get_json()["error"].lower()


def test_signup_rate_limited_after_5_attempts(client):
    codes = []
    for i in range(6):
        res = client.post("/api/auth/signup", json={
            "username": f"ratelimit{i}",
            "email": f"ratelimit{i}@example.com",
            "password": "supersecret123",
        })
        codes.append(res.status_code)
    assert codes[:5] == [201] * 5
    assert codes[5] == 429


def test_password_reset_rate_limited_after_5_attempts(client):
    for _ in range(5):
        client.post("/api/auth/reset-password", json={
            "token": "bad", "password": "supersecret123",
        })
    res = client.post("/api/auth/reset-password", json={
        "token": "bad", "password": "supersecret123",
    })
    assert res.status_code == 429
    assert res.is_json  # JSON body, not flask-limiter's HTML default


def test_rate_limit_headers_present(client):
    res = client.get("/health")
    assert "X-RateLimit-Limit" in res.headers
    assert "X-RateLimit-Remaining" in res.headers
