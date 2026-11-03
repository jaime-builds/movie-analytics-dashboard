"""Flask extensions, created here and bound to the app in src/app.py.

Route modules import them from here, so they never import src.app.
"""

from flask import request
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

from config.config import Config

cache = Cache()
csrf = CSRFProtect()


def _is_admin_endpoint():
    return request.blueprint == "admin"


# ---------------------------------------------------------------------------
# Rate limiting
# Production runs one Gunicorn process with threads, so the in-memory store is
# shared by every request. REDIS_URL still switches to Redis if one is added.
# The default is generous so normal browsing never hits it; login and register
# carry their own tight limits, and admin pages are exempt.
# ---------------------------------------------------------------------------
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["2000 per day", "600 per hour"],
    default_limits_exempt_when=_is_admin_endpoint,
    storage_uri=Config.REDIS_URL or "memory://",
)
