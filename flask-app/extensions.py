"""
Shared Flask extensions.

Kept in a separate module so blueprints (auth.py) can decorate routes with
rate limits without creating a circular import with app.py.
"""

import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# In-memory storage is correct for the current single-worker Render deployment.
# Set RATELIMIT_STORAGE_URI (e.g. "redis://...") if you ever scale to multiple
# workers, otherwise each worker keeps its own counters.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["300 per hour"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
    headers_enabled=True,
)
