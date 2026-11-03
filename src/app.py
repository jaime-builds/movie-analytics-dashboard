"""Flask application: configuration, extensions, request hooks and blueprints.

Routes live in src/routes/ (one blueprint per area of the site); helpers they
share are in src/helpers.py and src/featured.py.
"""

import logging
import time

import click
from flask import Flask, jsonify, redirect, render_template, request
from flask_wtf.csrf import CSRFError
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import HTTPException

from config.config import Config
from src.extensions import cache, csrf, limiter
from src.helpers import family_friendly_enabled, get_db_session
from src.logger import get_logger
from src.models import PageView, User, local_today
from src.routes.account import bp as account_bp
from src.routes.admin import bp as admin_bp
from src.routes.analytics import bp as analytics_bp
from src.routes.api import bp as api_bp
from src.routes.auth import bp as auth_bp
from src.routes.collections import bp as collections_bp
from src.routes.main import bp as main_bp
from src.routes.people import bp as people_bp

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Caching -- Redis in production, SimpleCache in local dev
# ---------------------------------------------------------------------------
_redis_url = Config.REDIS_URL

if _redis_url:
    _cache_config = {
        "CACHE_TYPE": "RedisCache",
        "CACHE_REDIS_URL": _redis_url,
        "CACHE_DEFAULT_TIMEOUT": 300,
    }
else:
    _cache_config = {
        "CACHE_TYPE": "SimpleCache",
        "CACHE_DEFAULT_TIMEOUT": 300,
    }

cache.init_app(app, config=_cache_config)
csrf.init_app(app)
# Before the request hooks below, so a rate-limited request is rejected first
limiter.init_app(app)

if Config.IS_PRODUCTION:
    from werkzeug.middleware.proxy_fix import ProxyFix

    # cloudflared is the single proxy hop, so trust exactly one X-Forwarded-*
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


# ── Request logging ───────────────────────────────────────────────────────
@app.before_request
def _log_request_start():
    """Stamp the request start time for duration tracking."""
    request._start_time = time.monotonic()


# ── Page view tracking ────────────────────────────────────────────────────
# Only real page routes are counted -- API calls and static assets are noise.
_UNTRACKED_PATH_PREFIXES = ("/api/", "/static/")

# Backends whose INSERT supports a native ON CONFLICT DO UPDATE upsert.
_PAGE_VIEW_UPSERTS = {
    "sqlite": sqlite_insert,
    "postgresql": postgresql_insert,
}


def _record_page_view(session_db, path, view_date):
    """Increment the view counter for (path, view_date), inserting it if new."""
    page_views = PageView.__table__
    upsert_insert = _PAGE_VIEW_UPSERTS.get(session_db.get_bind().dialect.name)

    if upsert_insert is not None:
        # One statement on the common path: insert, or bump the existing row.
        statement = upsert_insert(page_views).values(path=path, view_date=view_date, count=1)
        session_db.execute(
            statement.on_conflict_do_update(
                index_elements=["path", "view_date"],
                set_={"count": page_views.c.count + 1},
            )
        )
        session_db.commit()
        return

    # Other backends: try the insert, and fall back to an update on collision.
    try:
        # Savepoint so a losing race only discards this insert, not the session
        with session_db.begin_nested():
            session_db.execute(page_views.insert().values(path=path, view_date=view_date, count=1))
        session_db.commit()
    except IntegrityError:
        session_db.execute(
            page_views.update()
            .where(page_views.c.path == path, page_views.c.view_date == view_date)
            .values(count=page_views.c.count + 1)
        )
        session_db.commit()


@app.before_request
def _track_page_view():
    """Count GET requests to page routes for the admin analytics dashboard.

    Only requests that matched a route are counted, keyed by the route rule
    (for example ``/movie/<int:movie_id>``), so bot probes for random paths
    add nothing and the table holds one row per page type per day rather
    than one per movie, actor and director.
    """
    if request.method != "GET" or request.path.startswith(_UNTRACKED_PATH_PREFIXES):
        return
    if request.url_rule is None or request.endpoint == "static":
        return

    # This session only bumps a counter, so it deliberately leaves the rest of
    # the request alone: expire_on_commit is off and it is not closed. The
    # commit already returns the connection to the pool, while close() would
    # expunge instances from a session the request may still be using.
    session_db = get_db_session()
    expire_on_commit = session_db.expire_on_commit
    session_db.expire_on_commit = False
    try:
        _record_page_view(session_db, request.url_rule.rule[:255], local_today())
    except SQLAlchemyError as exc:
        # Analytics must never break the page it is counting
        session_db.rollback()
        logger.warning(
            f"Unable to record page view for {request.path}: {exc}",
            extra={"path": request.path},
        )
    finally:
        session_db.expire_on_commit = expire_on_commit


@app.after_request
def _log_request_end(response):
    """Log every completed request with method, path, status, and duration."""
    duration_ms = round((time.monotonic() - getattr(request, "_start_time", 0)) * 1000)
    status = response.status_code
    if request.path == "/api/v1/health" and status == 200:
        # The container healthcheck polls this every 30 seconds
        return response
    # Server errors and refused requests are worth an admin's attention; ordinary
    # 4xx (bots probing for /wp-login.php, stale links) would bury them
    if status >= 500:
        level = logging.ERROR
    elif status in (401, 403, 429):
        level = logging.WARNING
    else:
        level = logging.INFO
    logger.log(
        level,
        f"{request.method} {request.path} -> {response.status_code}",
        extra={
            "method": request.method,
            "path": request.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "ip": request.remote_addr,
        },
    )
    return response


# ── Security headers and HTTPS ────────────────────────────────────────────
# Inline scripts and onclick handlers are still used by the templates, so
# script-src keeps 'unsafe-inline'. The policy still blocks scripts from any
# other origin, plugins, framing and form posts to other sites.
_CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "font-src 'self' https://cdn.jsdelivr.net",
        "img-src 'self' data: https://image.tmdb.org",
        "connect-src 'self'",
        "frame-src https://www.youtube-nocookie.com https://www.youtube.com",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)


@app.before_request
def _redirect_plain_http():
    """Send visitors who reached Cloudflare over plain HTTP to HTTPS.

    Only requests that came through the tunnel carry X-Forwarded-Proto, so
    direct LAN access on the container port keeps working over HTTP.
    """
    if not Config.IS_PRODUCTION:
        return None
    if request.headers.get("X-Forwarded-Proto", "").lower() != "http":
        return None
    https_url = request.url.replace("http://", "https://", 1)
    # 308 keeps the method and body for anything that isn't a plain read
    return redirect(https_url, code=301 if request.method in ("GET", "HEAD") else 308)


@app.after_request
def _set_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
    )
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


# ── Error pages ───────────────────────────────────────────────────────────
_ERROR_PAGE_TEXT = {
    400: ("Bad request", "That request couldn't be processed."),
    403: ("Not allowed", "You don't have access to this page."),
    404: ("Page not found", "That page doesn't exist, or it has moved."),
    405: ("Not allowed", "That action isn't available here."),
    429: (
        "Slow down",
        "Too many requests from your connection. Wait a minute and try again.",
    ),
    500: ("Something went wrong", "The error has been logged. Try again in a moment."),
}


def _wants_json():
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def _error_response(status_code):
    title, message = _ERROR_PAGE_TEXT.get(status_code, ("Error", "Something went wrong."))
    if _wants_json():
        return jsonify({"error": title}), status_code
    try:
        return (
            render_template(
                "error.html",
                status_code=status_code,
                title=title,
                message=message,
                config=Config,
            ),
            status_code,
        )
    except Exception:  # pragma: no cover - last resort if the template itself fails
        return f"{status_code} {title}", status_code


@app.errorhandler(HTTPException)
def _handle_http_exception(exc):
    """Render common 4xx errors as a page (or JSON under /api/) instead of bare text."""
    if exc.code in _ERROR_PAGE_TEXT and exc.code != 500:
        return _error_response(exc.code)
    return exc


@app.errorhandler(Exception)
def _handle_unhandled_exception(exc):
    """Log unhandled exceptions as ERROR and show a generic error page."""
    # Let Flask handle its own HTTP exceptions (404, 405, etc.) normally
    if isinstance(exc, HTTPException):
        return exc
    logger.error(
        f"Unhandled exception on {request.method} {request.path}: {exc}",
        exc_info=True,
        extra={"ip": request.remote_addr, "path": request.path},
    )
    return _error_response(500)


@app.errorhandler(CSRFError)
def _handle_csrf_error(exc):
    """Return a clear CSRF failure for forms and fetch requests."""
    if (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
        or request.path.startswith("/api/")
    ):
        return jsonify({"error": "CSRF token missing or invalid"}), 400

    return "CSRF token missing or invalid", 400


# ── Template filters and context ──────────────────────────────────────────
@app.template_filter("format_currency")
def format_currency(value):
    """Format number as currency"""
    if not value:
        return "N/A"
    return f"${value:,.0f}"


@app.template_filter("format_runtime")
def format_runtime(minutes):
    """Format runtime in minutes to hours and minutes"""
    if not minutes:
        return "N/A"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


@app.template_filter("format_date")
def format_date(date_obj):
    """Format date as 'Month Day, Year' (e.g., March 23, 2026)"""
    if not date_obj:
        return "N/A"
    return date_obj.strftime("%B %d, %Y")


@app.context_processor
def _inject_display_preferences():
    return {"family_friendly": family_friendly_enabled()}


# ── Blueprints ────────────────────────────────────────────────────────────
for _blueprint in (
    auth_bp,
    main_bp,
    people_bp,
    account_bp,
    collections_bp,
    analytics_bp,
    api_bp,
    admin_bp,
):
    app.register_blueprint(_blueprint)


# ── Command line ──────────────────────────────────────────────────────────
@app.cli.command("set-admin")
@click.argument("username")
@click.option("--revoke", is_flag=True, help="Remove admin rights instead of granting them.")
def set_admin_command(username, revoke):
    """Grant (or with --revoke, remove) admin rights for USERNAME.

    In production: docker exec dashboard-app flask --app src.app set-admin <username>
    """
    session_db = get_db_session()
    try:
        user = session_db.query(User).filter_by(username=username).first()
        if user is None:
            raise click.ClickException(f"No user named {username!r}")
        user.is_admin = not revoke
        session_db.commit()
        click.echo(f"{username} is {'no longer' if revoke else 'now'} an admin.")
    finally:
        session_db.close()


if __name__ == "__main__":
    app.run(debug=Config.DEBUG)
