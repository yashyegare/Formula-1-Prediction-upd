"""
Tests for the baseline security headers applied to every response.

These pin the prod-audit finding that the API previously shipped zero
security headers (no HSTS, nosniff, frame-deny, or referrer policy).
"""

EXPECTED_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def test_health_response_carries_all_security_headers(client):
    """The cheapest public endpoint must carry the full header set."""
    resp = client.get("/health")
    assert resp.status_code == 200
    for name, value in EXPECTED_HEADERS.items():
        assert resp.headers.get(name) == value, f"missing/incorrect {name}"


def test_security_headers_present_on_auth_error_responses(client):
    """401s from the auth blueprint get the headers too."""
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    for name, value in EXPECTED_HEADERS.items():
        assert resp.headers.get(name) == value


def test_existing_headers_are_never_overwritten(client):
    """setdefault semantics: an endpoint that sets a header deliberately
    (e.g. CORS's Access-Control-Allow-*) keeps its own value."""
    resp = client.get("/health",
                      headers={"Origin": "http://127.0.0.1:3000"})
    assert resp.status_code == 200
    # The security headers themselves are still present...
    for name, value in EXPECTED_HEADERS.items():
        assert resp.headers.get(name) == value
    # ...and CORS headers were set by flask-cors, not clobbered.
    assert resp.headers.get("Access-Control-Allow-Origin") is not None
