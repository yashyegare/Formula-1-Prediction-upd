"""
Security helpers: shared origin allowlist + CSRF protection.

Why Origin verification instead of CSRF tokens:
The frontends live on other origins (Vercel) and talk to this API with
credentials: "include" over SameSite=None cookies. A classic token would
require a token-issuance flow on every client. Origin checking is the
OWASP-recommended alternative for this setup ("Verifying Origin with
Standard Headers"): browsers always attach Origin to cross-origin POSTs
and cannot be scripted to forge it.

Scope: only requests that carry ambient credentials (the Flask session or
the flask-login remember_token cookie) are subject to the check — those are
the only requests CSRF can abuse. Cookie-less clients (curl, scripts,
health checks) are unaffected, and so are unauthenticated endpoints.
"""

import os
import re

from flask import jsonify, request

# Dev origins are always allowed; production frontends are appended from the
# CORS_ORIGINS env var (comma-separated). This is the single source of truth
# shared by the CORS configuration and the CSRF check.
_DEFAULT_DEV_ORIGINS = [
    "http://localhost:3000",   # Next.js dev
    "http://localhost:5173",   # Astro dev
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]


def get_allowed_origins() -> list:
    origins = list(_DEFAULT_DEV_ORIGINS)
    extra = os.environ.get("CORS_ORIGINS", "")
    if extra:
        origins.extend(o.strip() for o in extra.split(",") if o.strip())
    return origins


_REFERER_ORIGIN_RE = re.compile(r"^(https?://[^/]+)")


def register_csrf_protection(app):
    """Block state-changing browser requests whose Origin is not allowlisted."""

    @app.before_request
    def _csrf_verify_origin():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None

        # No ambient credentials → nothing for CSRF to hijack.
        cookie_names = {app.config.get("SESSION_COOKIE_NAME", "session"), "remember_token"}
        if not (cookie_names & set(request.cookies.keys())):
            return None

        origin = request.headers.get("Origin", "")
        if not origin:
            # Fallback for older browsers: derive origin from Referer.
            match = _REFERER_ORIGIN_RE.match(request.headers.get("Referer", ""))
            origin = match.group(1) if match else ""

        if not origin:
            # Browsers always send Origin on cross-origin POSTs, so a request
            # without one is a non-browser client (curl, server-to-server).
            # It could not be tricked into carrying a forged form post.
            return None

        if origin not in get_allowed_origins():
            return jsonify({"error": "Cross-origin request blocked"}), 403

        return None
