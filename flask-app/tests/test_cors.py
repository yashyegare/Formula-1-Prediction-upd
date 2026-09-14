"""
CORS allowlist tests.

The global CORS config (app.py) is the single source of truth: only origins in
CORS_ORIGINS (plus localhost dev origins) may get an Access-Control-Allow-Origin
response. This pins two properties that have each failed once:

  - No route may reflect an arbitrary Origin (a bare route-level @cross_origin()
    did exactly that on /predictGrid and /roster — reflect-all semantics override
    the global allowlist for that route).
  - The two production frontends must stay allowlisted, or their live roster
    fetches and predictions get silently blocked in the browser.
"""

FOREIGN = "https://evil-test.example.com"

# The two deployed frontends — must match Render's CORS_ORIGINS exactly.
PREDICTOR = "https://nextjs-app-yashyegare.vercel.app"
SIMULATOR = "https://formula-1-prediction-upd-fxzg.vercel.app"


def _acao(resp):
    return resp.headers.get("Access-Control-Allow-Origin")


def test_no_route_reflects_arbitrary_origin(client):
    """A foreign origin must never receive an ACAO header, on any route.
    (/api/init deliberately excluded: against the tests' empty temp DB it
    would trigger the live Jolpica fallback fetch — no network in unit tests.)"""
    for path in ("/roster", "/api/circuits", "/health"):
        resp = client.get(path, headers={"Origin": FOREIGN})
        assert _acao(resp) is None, f"{path} reflected a foreign Origin: {_acao(resp)}"


def test_predict_grid_preflight_rejects_foreign_origin(client):
    """/predictGrid used to carry a bare @cross_origin() that reflected any
    Origin on both the response and its preflight — regression-guard it."""
    resp = client.options(
        "/predictGrid",
        headers={
            "Origin": FOREIGN,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert _acao(resp) is None, "predictGrid preflight reflected a foreign Origin"


def test_predictor_origin_allowlisted(client):
    """The predictor's roster fetch breaks in the browser if this drifts."""
    resp = client.get("/roster", headers={"Origin": PREDICTOR})
    assert resp.status_code == 200
    assert _acao(resp) == PREDICTOR


def test_simulator_origin_allowlisted(client):
    """The season simulator's /api/init and /api/circuits fetches need this."""
    resp = client.get("/api/circuits", headers={"Origin": SIMULATOR})
    assert resp.status_code == 200
    assert _acao(resp) == SIMULATOR


def test_preflight_post_allowed_for_predictor(client):
    """POST predictions are non-simple requests: the browser preflights them."""
    resp = client.options(
        "/predictGrid",
        headers={
            "Origin": PREDICTOR,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code in (200, 204), resp.status_code
    assert _acao(resp) == PREDICTOR
    assert "POST" in resp.headers.get("Access-Control-Allow-Methods", "")
