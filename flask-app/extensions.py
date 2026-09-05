import os

from flask import Flask, jsonify
from flask_limiter import Limiter
from flask_limiter.errors import RateLimitExceeded
from flask_limiter.util import get_remote_address

_RATE_LIMIT_MESSAGE = "Too many requests. Please wait a few minutes and try again."


def _rate_limit_response():
    """JSON 429 body — flask-limiter's default HTML page would crash the
    frontends, which call res.json() on every response."""
    resp = jsonify(error=_RATE_LIMIT_MESSAGE)
    resp.status_code = 429
    return resp


# In-memory storage is correct for the current single-worker Render deployment.
# Set RATELIMIT_STORAGE_URI (e.g. "redis://...") if you ever scale to multiple
# workers, otherwise each worker keeps its own counters.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["300 per hour"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
    headers_enabled=True,
    on_breach=lambda request_limit: _rate_limit_response(),
)


def register_limiter_error_handlers(app: Flask) -> None:
    """Ensure every 429 (decorator limits, defaults, meta limits) is JSON."""
    @app.errorhandler(RateLimitExceeded)
    def _handle_rate_limit_exceeded(e):
        return _rate_limit_response()
