"""
CSRF protection tests (Origin/Referer verification).

The rule being tested: a state-changing request that carries session
credentials must present an allowlisted Origin (or Referer fallback);
everything else passes through untouched.
"""

FOREIGN = "https://evil.example"


def _signup(client, username="csrfuser"):
    return client.post("/api/auth/signup", json={
        "username": username, "email": f"{username}@example.com",
        "password": "supersecret123",
    })


def test_csrf_blocks_foreign_origin_with_session(client):
    assert _signup(client).status_code == 201  # client now holds session cookies
    res = client.post("/api/auth/logout", headers={"Origin": FOREIGN})
    assert res.status_code == 403
    assert res.get_json()["error"] == "Cross-origin request blocked"


def test_csrf_allows_allowlisted_origin_with_session(client):
    assert _signup(client).status_code == 201
    res = client.post("/api/auth/logout", headers={"Origin": "http://localhost:3000"})
    assert res.status_code == 200


def test_csrf_allows_other_dev_origin(client):
    assert _signup(client).status_code == 201
    res = client.post("/api/auth/logout", headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 200


def test_csrf_ignores_cookieless_requests(client):
    """Without ambient cookies there is nothing to hijack — foreign Origin
    must NOT be blocked (this is what keeps curl/scripts/server clients working)."""
    res = client.post("/api/auth/login", json={
        "username": "nobody", "password": "wrong",
    }, headers={"Origin": FOREIGN})
    assert res.status_code == 401  # reached the endpoint; auth failed normally


def test_csrf_ignores_safe_methods(client):
    assert _signup(client).status_code == 201
    res = client.get("/api/auth/me", headers={"Origin": FOREIGN})
    assert res.status_code == 200  # GET is never CSRF-relevant


def test_csrf_falls_back_to_referer(client):
    assert _signup(client).status_code == 201

    # No Origin header, allowlisted Referer → allowed
    res = client.post("/api/auth/logout", headers={
        "Referer": "http://localhost:5173/some/page",
    })
    assert res.status_code == 200


def test_csrf_rejects_foreign_referer_without_origin(client):
    assert _signup(client).status_code == 201
    res = client.post("/api/auth/logout", headers={
        "Referer": "https://evil.example/attack",
    })
    assert res.status_code == 403


def test_csrf_allows_missing_origin_and_referer(client):
    """No Origin and no Referer means a non-browser client (curl, health
    checks, server-to-server) — those can't be CSRF victims, let them through."""
    assert _signup(client).status_code == 201
    res = client.post("/api/auth/logout")
    assert res.status_code == 200
