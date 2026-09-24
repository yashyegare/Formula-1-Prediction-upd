"""
Contract test for the race-intel blueprint registration in app.py.

The Phase-4 API ships as a standalone blueprint (race_intelligence_api.py)
that app.py must register. If registration drifts — blueprint removed,
renamed, or its routes renamed — the frontends silently lose the
race-intel endpoints while every other test still passes. This file pins
the registered routes.
"""

from app import app as flask_app
from race_intelligence_api import race_intel_bp

EXPECTED_ROUTES = {
    "/api/race-intel/season/<int:year>",
    "/api/race-intel/races/<int:year>",
    "/api/race-intel/race/<int:year>/<int:rnd>",
    "/api/race-intel/drivers/<int:year>/<int:rnd>",
    "/api/race-intel/next/<int:year>",
    "/api/race-intel/curves/<int:year>/<int:rnd>",
}


def test_race_intel_blueprint_registered():
    """app.py registers race_intel_bp under the race_intel blueprint name."""
    registered = {bp.name for bp in flask_app.blueprints.values()}
    assert "race_intel" in registered
    assert race_intel_bp.name == "race_intel"


def test_race_intel_routes_pinned():
    """Every expected route exists on the app with GET allowed."""
    rules = {r.rule: r for r in flask_app.url_map.iter_rules()}
    for route in EXPECTED_ROUTES:
        assert route in rules, f"route missing from app: {route}"
        assert "GET" in rules[route].methods, f"GET not allowed on {route}"


def test_race_intel_404_shape():
    """Unknown season returns the explicit JSON 404 the frontends rely on."""
    client = flask_app.test_client()
    resp = client.get("/api/race-intel/season/1997")
    assert resp.status_code == 404
    assert resp.is_json
    assert "error" in resp.get_json()
