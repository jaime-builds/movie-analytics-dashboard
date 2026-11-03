import csv
import hashlib
import io
import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Dict, Optional
from urllib.parse import unquote, urlsplit

import click
from flask import (
    Flask,
    Response,
    abort,
    flash,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
)
from flask import session as flask_session
from flask import url_for
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy import (
    and_,
    case,
    desc,
    exists,
    extract,
    func,
    literal,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import aliased, contains_eager, selectinload
from werkzeug.exceptions import HTTPException

from config.config import Config
from src.logger import get_log_file_path, get_logger
from src.models import (
    Cast,
    Collection,
    Crew,
    Genre,
    Movie,
    MovieOfTheDay,
    PageView,
    Person,
    ProductionCompany,
    Rating,
    Review,
    Session,
    SiteSetting,
    User,
    collection_movies_table,
    local_today,
    movie_companies_table,
    movie_genres_table,
    user_favorites_table,
    user_watchlist_table,
    utcnow,
)
from src.tmdb_api import TMDBClient

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

cache = Cache()
cache.init_app(app, config=_cache_config)

csrf = CSRFProtect()
csrf.init_app(app)

# Input limits shared by routes and templates
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
MAX_REVIEW_LENGTH = 5000
MAX_COLLECTION_DESCRIPTION_LENGTH = 2000
# Deepest page any paginated listing will serve; keeps OFFSET far from the
# bigint limit Postgres enforces (an out-of-range OFFSET is a 500, not a 404)
MAX_PAGE = 10_000

# Home page "Top Rated" needs this many votes, so a niche title rated 9.4 by
# a few hundred people can't outrank the classics (FS-60)
TOP_RATED_MIN_VOTES = 1000

# Hidden Gems defaults, shared with Movie of the Day
GEM_MIN_RATING = 7.0
GEM_MAX_POPULARITY = 20.0
GEM_MIN_VOTES = 50


def _is_admin_endpoint():
    return bool(request.endpoint and request.endpoint.startswith("admin_"))


# ---------------------------------------------------------------------------
# Rate limiting
# Production runs one Gunicorn process with threads, so the in-memory store is
# shared by every request. REDIS_URL still switches to Redis if one is added.
# The default is generous so normal browsing never hits it; login and register
# carry their own tight limits, and admin pages are exempt.
# ---------------------------------------------------------------------------
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["2000 per day", "600 per hour"],
    default_limits_exempt_when=_is_admin_endpoint,
    storage_uri=_redis_url if _redis_url else "memory://",
)

if Config.IS_PRODUCTION:
    from werkzeug.middleware.proxy_fix import ProxyFix

    # cloudflared is the single proxy hop, so trust exactly one X-Forwarded-*
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


def get_db_session():
    """Get a new database session"""
    return Session()


def _association_filters(table, **column_values):
    return [table.c[column] == value for column, value in column_values.items()]


def _association_exists(session_db, table, **column_values):
    return bool(
        session_db.query(exists().where(*_association_filters(table, **column_values))).scalar()
    )


def _association_count(session_db, table, **column_values):
    return (
        session_db.query(func.count())
        .select_from(table)
        .filter(*_association_filters(table, **column_values))
        .scalar()
        or 0
    )


def _collection_movies_page(session_db, collection_id, offset, limit):
    return (
        session_db.query(Movie)
        .join(collection_movies_table, Movie.id == collection_movies_table.c.movie_id)
        .filter(collection_movies_table.c.collection_id == collection_id)
        .order_by(collection_movies_table.c.added_at, Movie.id)
        .offset(offset)
        .limit(limit)
        .all()
    )


# ==========================================
# REQUEST LOGGING
# ==========================================


@app.before_request
def _log_request_start():
    """Stamp the request start time for duration tracking."""
    request._start_time = time.monotonic()


# ==========================================
# PAGE VIEW TRACKING
# ==========================================

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


# ==========================================
# SECURITY HEADERS AND HTTPS
# ==========================================

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


# ==========================================
# ERROR PAGES
# ==========================================

_ERROR_PAGE_TEXT = {
    400: ("Bad request", "That request couldn't be processed."),
    403: ("Not allowed", "You don't have access to this page."),
    404: ("Page not found", "That page doesn't exist, or it has moved."),
    405: ("Not allowed", "That action isn't available here."),
    429: ("Slow down", "Too many requests from your connection. Wait a minute and try again."),
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
                "error.html", status_code=status_code, title=title, message=message, config=Config
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


def get_current_user(session_db):
    """Get the currently logged-in user from session.

    Banned accounts are logged out here rather than in a dedicated
    before_request hook: this app opens a fresh DB session per route, so a
    separate hook would repeat the user lookup on every authenticated
    request. Every auth-aware route already funnels through this function,
    so enforcing the ban here costs nothing extra. Returning None lets the
    request continue and redirect/render as it would for a logged-out user.
    """
    user_id = flask_session.get("user_id")
    if not user_id:
        return None

    user = session_db.query(User).filter_by(id=user_id).first()

    # A logout or ban bumps the user's session version, which invalidates every
    # cookie issued before it, including copies taken from another device.
    if user is not None and flask_session.get("session_version", 0) != (user.session_version or 0):
        flask_session.clear()
        return None

    if user is not None and user.is_banned:
        flask_session.clear()
        logger.warning(
            f"Banned user blocked: {user.username}",
            extra={
                "user_id": user.id,
                "username": user.username,
                "ip": request.remote_addr,
            },
        )
        flash("Your account has been suspended.", "danger")
        return None

    return user


def _start_user_session(user):
    """Log a user in with a fresh session (avoids session fixation)."""
    family_friendly = flask_session.get("family_friendly")
    flask_session.clear()
    if family_friendly:
        flask_session["family_friendly"] = True
    flask_session["user_id"] = user.id
    flask_session["session_version"] = user.session_version or 0


def admin_required(view_func):
    """Restrict a route to administrators: login redirect if logged out, else 403."""

    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        session_db = get_db_session()
        try:
            user = get_current_user(session_db)
            if not user and request.method == "GET":
                flash("Please log in to continue", "warning")
                return redirect(url_for("login", next=_current_relative_url()))
            if not user or not user.is_admin:
                logger.warning(
                    f"Denied admin access to {request.path}",
                    extra={
                        "user_id": user.id if user else None,
                        "path": request.path,
                        "ip": request.remote_addr,
                    },
                )
                abort(403)
        finally:
            session_db.close()

        return view_func(*args, **kwargs)

    return wrapped_view


def _visible_content_filters(model):
    """Filters hiding soft-deleted rows and rows authored by banned users.

    The query must already join `User` on the author. Banned users' content is
    excluded everywhere -- including rating aggregates -- so a ban hides an
    account's contributions consistently across the site.
    """
    return (model.is_deleted.is_(False), User.is_banned.is_(False))


def _visible_reviews_query(session_db, movie_id):
    """Reviews for a movie that are safe to show to other users."""
    return (
        session_db.query(Review)
        .join(User, Review.user_id == User.id)
        .filter(Review.movie_id == movie_id, *_visible_content_filters(Review))
    )


def _public_rating_stats(session_db, movie_id):
    """Return (average, count) of a movie's publicly visible user ratings."""
    avg_rating, num_ratings = (
        session_db.query(func.avg(Rating.rating), func.count(Rating.id))
        .join(User, Rating.user_id == User.id)
        .filter(Rating.movie_id == movie_id, *_visible_content_filters(Rating))
        .one()
    )
    return avg_rating, num_ratings or 0


def _get_site_setting(session_db, key, default=None):
    """Read a site_settings value, falling back to `default` when unset."""
    setting = session_db.query(SiteSetting).filter_by(key=key).first()
    if setting is None or setting.value is None:
        return default
    return setting.value


def _set_site_setting(session_db, key, value):
    """Insert or update a site_settings row."""
    setting = session_db.query(SiteSetting).filter_by(key=key).first()
    if setting is None:
        session_db.add(SiteSetting(key=key, value=value))
    else:
        setting.value = value
    session_db.commit()


def _registration_enabled(session_db) -> bool:
    """Whether new account registration is currently allowed."""
    return _get_site_setting(session_db, "registration_enabled", "true") == "true"


def _is_safe_relative_redirect(target: Optional[str]) -> bool:
    """Allow only local relative redirects such as /favorites."""
    if not target:
        return False

    target = target.strip()
    decoded = unquote(target)
    if not decoded or "\r" in decoded or "\n" in decoded or "\\" in decoded:
        return False

    parsed = urlsplit(decoded)
    if parsed.scheme or parsed.netloc:
        return False

    return decoded.startswith("/") and not decoded.startswith("//")


def _safe_next_url() -> Optional[str]:
    """Return a safe next URL from form/query params, or None."""
    next_url = request.form.get("next") or request.args.get("next")
    if _is_safe_relative_redirect(next_url):
        return next_url.strip()
    return None


def _current_relative_url() -> str:
    """Use the current path/query as a safe login return target."""
    return request.full_path if request.query_string else request.path


def _contains_pattern(text: str) -> str:
    """A LIKE pattern matching `text` anywhere, with % and _ taken literally.

    Use with `.ilike(pattern, escape="\\")`.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _html_page_arg(name: str = "page", default: int = 1) -> int:
    """Clamp HTML pagination to a page number between 1 and MAX_PAGE."""
    value = request.args.get(name, default=default, type=int)
    if not value or value < 1:
        return default
    return min(value, MAX_PAGE)


def _api_positive_int_arg(name: str, default: int, max_value: Optional[int] = None):
    """Parse a positive integer API argument, capping optional maximums."""
    raw_value = request.args.get(name)
    if raw_value in (None, ""):
        value = default
    else:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return None, (
                jsonify({"error": f"Invalid {name}: must be an integer"}),
                400,
            )

    if value < 1:
        return None, (jsonify({"error": f"Invalid {name}: must be at least 1"}), 400)

    if max_value is None and name == "page":
        max_value = MAX_PAGE
    if max_value is not None:
        value = min(value, max_value)

    return value, None


def get_trailer_for_movie(tmdb_id: int) -> Optional[Dict]:
    """Fetch the best YouTube trailer for a movie from TMDB API."""
    client = TMDBClient()
    try:
        videos_data = client.get_movie_videos(tmdb_id)
    except Exception as exc:
        logger.warning(f"Unable to fetch trailer for tmdb_id={tmdb_id}: {exc}", exc_info=True)
        return None

    results = videos_data.get("results", [])

    youtube_videos = [v for v in results if v.get("site") == "YouTube"]
    if not youtube_videos:
        return None

    # Priority: official trailers > any trailer > teasers > any video
    for filter_fn in [
        lambda v: v.get("type") == "Trailer" and v.get("official"),
        lambda v: v.get("type") == "Trailer",
        lambda v: v.get("type") == "Teaser",
    ]:
        matches = [v for v in youtube_videos if filter_fn(v)]
        if matches:
            return matches[0]

    return youtube_videos[0]


def get_similar_movies(session, movie_id, limit=6, movie=None):
    """
    Get similar movies based on shared genres.
    Sorted by:
    1. Number of matching genres (descending)
    2. Vote average (descending)
    3. Popularity (descending)

    Pass `movie` when the caller already loaded it, to skip a query.
    """
    if movie is None:
        movie = session.query(Movie).filter_by(id=movie_id).first()

    if not movie or not movie.genres:
        # If no movie or no genres, return popular movies
        return (
            _content_filtered(session.query(Movie))
            .filter(Movie.id != movie_id)
            .filter(Movie.vote_count > 20)
            .order_by(desc(Movie.popularity), Movie.id)
            .limit(limit)
            .all()
        )

    # Get genre IDs for the current movie
    movie_genre_ids = [genre.id for genre in movie.genres]

    # Create subquery to count matching genres for each movie
    genre_match_subquery = (
        select(
            movie_genres_table.c.movie_id,
            func.count(movie_genres_table.c.genre_id).label("match_count"),
        )
        .where(movie_genres_table.c.genre_id.in_(movie_genre_ids))
        .group_by(movie_genres_table.c.movie_id)
        .subquery()
    )

    # Query for similar movies with genre match count
    similar_movies = (
        _content_filtered(session.query(Movie))
        .join(genre_match_subquery, Movie.id == genre_match_subquery.c.movie_id)
        .filter(Movie.id != movie_id)
        .filter(Movie.vote_count > 20)
        .order_by(
            desc(genre_match_subquery.c.match_count),  # Most genre matches first
            desc(Movie.vote_average),  # Then by rating
            desc(Movie.popularity),  # Then by popularity
            Movie.id,
        )
        .limit(limit)
        .all()
    )

    return similar_movies


def get_personalized_recommendations(session_db, user, limit=6, exclude_ids=()):
    """
    Get personalized movie recommendations based on user's favorites.

    Algorithm:
    1. Get all genres from user's favorite movies
    2. Find highly-rated movies in those genres the user hasn't favorited,
       watchlisted or rated (and not in exclude_ids, e.g. the page's movie)
    3. Weight by genre overlap and rating
    """
    favorite_ids = select(user_favorites_table.c.movie_id).where(
        user_favorites_table.c.user_id == user.id
    )
    seen_filters = [
        Movie.id.notin_(favorite_ids),
        Movie.id.notin_(
            select(user_watchlist_table.c.movie_id).where(user_watchlist_table.c.user_id == user.id)
        ),
        Movie.id.notin_(select(Rating.movie_id).where(Rating.user_id == user.id)),
    ]
    if exclude_ids:
        seen_filters.append(Movie.id.notin_(list(exclude_ids)))

    # Genres of the user's favorites, in one query
    favorite_genre_ids = [
        row[0]
        for row in session_db.query(movie_genres_table.c.genre_id)
        .filter(movie_genres_table.c.movie_id.in_(favorite_ids))
        .distinct()
        .all()
    ]

    if not favorite_genre_ids:
        # No favorites (or none with genres): popular highly-rated movies
        return (
            _content_filtered(session_db.query(Movie))
            .filter(Movie.vote_count > 100, *seen_filters)
            .order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
            .limit(limit)
            .all()
        )

    # Count genre matches for each movie
    genre_match_subquery = (
        select(
            movie_genres_table.c.movie_id,
            func.count(movie_genres_table.c.genre_id).label("match_count"),
        )
        .where(movie_genres_table.c.genre_id.in_(favorite_genre_ids))
        .group_by(movie_genres_table.c.movie_id)
        .subquery()
    )

    return (
        _content_filtered(session_db.query(Movie))
        .join(genre_match_subquery, Movie.id == genre_match_subquery.c.movie_id)
        .filter(Movie.vote_count > 50, *seen_filters)
        .order_by(
            desc(genre_match_subquery.c.match_count),  # Most genre matches
            desc(Movie.vote_average),  # Then by rating
            desc(Movie.popularity),  # Then by popularity
            Movie.id,
        )
        .limit(limit)
        .all()
    )


def _featured_filters():
    """Movies allowed on the home page: not mature, not hidden by an admin."""
    return (Movie.is_mature.is_(False), Movie.hide_from_featured.is_(False))


def family_friendly_enabled() -> bool:
    """Whether this visitor turned on the family-friendly toggle (session cookie)."""
    return has_request_context() and bool(flask_session.get("family_friendly"))


def _content_filtered(query):
    """Hide mature movies from a Movie query when the family-friendly toggle is on."""
    if family_friendly_enabled():
        return query.filter(Movie.is_mature.is_(False))
    return query


def _pick_movie_of_the_day(session_db, today):
    """Deterministically choose today's movie id from the eligible gem pool."""
    pool_query = session_db.query(Movie.id).filter(
        Movie.vote_average >= GEM_MIN_RATING,
        Movie.popularity <= GEM_MAX_POPULARITY,
        Movie.vote_count >= GEM_MIN_VOTES,
        *_featured_filters(),
    )

    recent_ids = [
        row.movie_id
        for row in session_db.query(MovieOfTheDay.movie_id)
        .order_by(desc(MovieOfTheDay.shown_date))
        .limit(30)
        .all()
    ]

    # Only IDs are loaded; the chosen movie is fetched on its own afterwards
    candidates = [
        row.id for row in pool_query.filter(Movie.id.notin_(recent_ids)).order_by(Movie.id).all()
    ]
    if not candidates:
        # Anti-repeat window exhausted the pool — fall back to the full pool
        candidates = [row.id for row in pool_query.order_by(Movie.id).all()]
    if not candidates:
        return None

    digest = hashlib.sha256(today.isoformat().encode("utf-8")).hexdigest()
    return candidates[int(digest, 16) % len(candidates)]


def get_movie_of_the_day(session_db):
    """Return today's featured movie, selecting and recording one if needed.

    Candidates come from the Hidden Gems pool (same criteria as /hidden-gems
    defaults), excluding the last 30 daily picks. The pick is deterministic
    per calendar day: a sha256 hash of the ISO date indexes into the candidate
    list sorted by movie id, so concurrent workers agree on the same movie
    without locking. (Python's built-in hash() is per-process randomized, so
    it can't be used here.)
    """
    today = local_today()

    existing = (
        session_db.query(MovieOfTheDay).filter(MovieOfTheDay.shown_date == today).one_or_none()
    )
    if existing:
        movie = (
            session_db.query(Movie)
            .filter(Movie.id == existing.movie_id, *_featured_filters())
            .one_or_none()
        )
        if movie is not None:
            return movie
        # Today's pick was flagged mature or hidden after it was chosen: swap it
        replacement_id = _pick_movie_of_the_day(session_db, today)
        if replacement_id is None:
            return None
        existing.movie_id = replacement_id
        session_db.commit()
        return session_db.query(Movie).filter(Movie.id == replacement_id).one_or_none()

    pick_id = _pick_movie_of_the_day(session_db, today)
    if pick_id is None:
        return None

    try:
        # Savepoint so a losing race only discards this insert, not the session
        with session_db.begin_nested():
            session_db.add(MovieOfTheDay(movie_id=pick_id, shown_date=today))
        session_db.commit()
    except IntegrityError:
        # Another worker inserted today's row first — use its pick instead
        existing = (
            session_db.query(MovieOfTheDay).filter(MovieOfTheDay.shown_date == today).one_or_none()
        )
        if existing is None:
            return None
        return session_db.query(Movie).filter(Movie.id == existing.movie_id).one_or_none()

    return session_db.query(Movie).filter(Movie.id == pick_id).one_or_none()


# ==========================================
# USER AUTHENTICATION ROUTES
# ==========================================


def _username_taken(session_db, username):
    """Usernames are unique regardless of case, so "Admin" can't shadow "admin"."""
    return session_db.query(exists().where(func.lower(User.username) == username.lower())).scalar()


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    session_db = get_db_session()
    try:
        # Registration can be switched off site-wide from the admin dashboard
        registration_enabled = _registration_enabled(session_db)
        if not registration_enabled:
            return render_template("register.html", registration_enabled=False)

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            password_confirm = request.form.get("password_confirm", "")

            def _form_error(message):
                flash(message, "danger")
                return render_template(
                    "register.html", registration_enabled=True, username=username
                )

            # Validation
            if not username or not password:
                return _form_error("Username and password are required")

            if len(username) < 3:
                return _form_error("Username must be at least 3 characters")

            if len(username) > 30:
                return _form_error("Username must be 30 characters or fewer")

            if not USERNAME_PATTERN.match(username):
                return _form_error(
                    "Username can only use letters, numbers, underscores, hyphens and periods"
                )

            if len(password) < 6:
                return _form_error("Password must be at least 6 characters")

            if password != password_confirm:
                return _form_error("Passwords do not match")

            # Check if username exists (case-insensitive)
            if _username_taken(session_db, username):
                return _form_error("Username already exists. Please choose another.")

            # Create new user
            user = User(username=username)
            user.set_password(password)
            session_db.add(user)
            try:
                session_db.commit()
            except IntegrityError:
                # Two signups for the same name at once: the unique index wins
                session_db.rollback()
                return _form_error("Username already exists. Please choose another.")

            # Log the user in
            _start_user_session(user)
            logger.info(
                f"New user registered: {username}",
                extra={
                    "user_id": user.id,
                    "username": username,
                    "ip": request.remote_addr,
                },
            )
            flash(f"Welcome, {username}! Your account has been created.", "success")
            return redirect(url_for("index"))

        return render_template("register.html", registration_enabled=True)
    finally:
        session_db.close()


def _login_username_key():
    return "login-user:" + request.form.get("username", "").strip().lower()


def _login_failed(response):
    # A successful login redirects; a failed one re-renders the form
    return response.status_code != 302


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute;30 per hour", methods=["POST"])
@limiter.limit(
    "10 per hour",
    methods=["POST"],
    key_func=_login_username_key,
    deduct_when=_login_failed,
)
def login():
    session_db = get_db_session()
    try:
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            user = session_db.query(User).filter_by(username=username).first()

            if user and user.check_password(password):
                _start_user_session(user)
                logger.info(
                    f"Successful login: {username}",
                    extra={
                        "user_id": user.id,
                        "username": username,
                        "ip": request.remote_addr,
                    },
                )
                flash(f"Welcome back, {username}!", "success")

                # Redirect to 'next' page if it exists, otherwise home
                next_page = _safe_next_url()
                return redirect(next_page if next_page else url_for("index"))

            logger.warning(
                f"Failed login attempt: {username}",
                extra={"username": username, "ip": request.remote_addr},
            )
            flash("Invalid username or password", "danger")
            return render_template("login.html", next_url=_safe_next_url(), username=username)

        return render_template("login.html", next_url=_safe_next_url())
    finally:
        session_db.close()


@app.route("/logout", methods=["POST"])
def logout():
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if user is not None:
            # Invalidate this cookie and any copy of it
            user.session_version = (user.session_version or 0) + 1
            session_db.commit()
    finally:
        session_db.close()

    family_friendly = flask_session.get("family_friendly")
    flask_session.clear()
    if family_friendly:
        # A display preference, not part of the login: keep it
        flask_session["family_friendly"] = True
    flash("You have been logged out successfully.", "info")
    return redirect(url_for("index"))


# ==========================================
# FAVORITES / WATCHLIST ROUTES
# ==========================================


def _user_list_movies(session_db, table, user_id):
    """A user's favorites or watchlist, newest additions first, genres preloaded."""
    return (
        session_db.query(Movie)
        .join(table, table.c.movie_id == Movie.id)
        .filter(table.c.user_id == user_id)
        .options(selectinload(Movie.genres))
        .order_by(desc(table.c.added_at).nulls_last(), Movie.title, Movie.id)
        .all()
    )


@app.route("/favorites")
def favorites():
    """Display user's favorite movies"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your favorites", "warning")
            return redirect(url_for("login", next=_current_relative_url()))

        favorites = _user_list_movies(session_db, user_favorites_table, user.id)

        return render_template(
            "favorites.html", favorites=favorites, current_user=user, config=Config
        )
    finally:
        session_db.close()


@app.route("/watchlist")
def watchlist():
    """Display user's watchlist"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your watchlist", "warning")
            return redirect(url_for("login", next=_current_relative_url()))

        watchlist = _user_list_movies(session_db, user_watchlist_table, user.id)

        return render_template(
            "watchlist.html", watchlist=watchlist, current_user=user, config=Config
        )
    finally:
        session_db.close()


def _insert_association(session_db, table, **values):
    """Insert a link row and commit; False if it already existed.

    The existence check before this can race with a double-click or a second
    tab, so the insert runs in a savepoint and a duplicate-key error just means
    the row is already there.
    """
    try:
        with session_db.begin_nested():
            session_db.execute(table.insert().values(**values))
        inserted = True
    except IntegrityError:
        inserted = False
    session_db.commit()
    return inserted


def _toggle_user_list(movie_id, table, add):
    """Add a movie to, or remove it from, the user's favorites or watchlist."""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        present = _association_exists(session_db, table, user_id=user.id, movie_id=movie.id)
        if add:
            if not present and _insert_association(
                session_db, table, user_id=user.id, movie_id=movie.id
            ):
                return jsonify({"status": "added"})
            return jsonify({"status": "already_added"})

        if present:
            session_db.execute(
                table.delete().where(table.c.user_id == user.id, table.c.movie_id == movie.id)
            )
            session_db.commit()
            return jsonify({"status": "removed"})
        return jsonify({"status": "not_found"})
    finally:
        session_db.close()


@app.route("/movie/<int:movie_id>/favorite", methods=["POST"])
def add_favorite(movie_id):
    return _toggle_user_list(movie_id, user_favorites_table, add=True)


@app.route("/movie/<int:movie_id>/unfavorite", methods=["POST"])
def remove_favorite(movie_id):
    return _toggle_user_list(movie_id, user_favorites_table, add=False)


@app.route("/movie/<int:movie_id>/watchlist", methods=["POST"])
def add_watchlist(movie_id):
    return _toggle_user_list(movie_id, user_watchlist_table, add=True)


@app.route("/movie/<int:movie_id>/unwatchlist", methods=["POST"])
def remove_watchlist(movie_id):
    return _toggle_user_list(movie_id, user_watchlist_table, add=False)


# ==========================================
# NEW: RATINGS & REVIEWS ROUTES (FEATURE 1)
# ==========================================


@app.route("/movie/<int:movie_id>/rate", methods=["POST"])
def rate_movie(movie_id):
    """Submit or update a rating for a movie"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        # Get rating value from form
        rating_value = request.form.get("rating", type=int)

        # Validate rating
        if not rating_value or rating_value < 1 or rating_value > 5:
            return jsonify({"error": "Rating must be between 1 and 5"}), 400

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        # Check if user already rated this movie. Soft-deleted rows are
        # included: the unique (user, movie) index means a moderated rating
        # would otherwise be silently overwritten and stay hidden.
        existing_rating = (
            session_db.query(Rating).filter_by(user_id=user.id, movie_id=movie_id).first()
        )

        if existing_rating and existing_rating.is_deleted:
            return jsonify({"error": "This rating was removed by a moderator"}), 403

        if existing_rating:
            # Update existing rating
            existing_rating.rating = rating_value
            flash(f"Your rating has been updated to {rating_value} stars", "success")
        else:
            # Create new rating
            new_rating = Rating(user_id=user.id, movie_id=movie_id, rating=rating_value)
            session_db.add(new_rating)
            flash(f"You rated this movie {rating_value} stars", "success")

        session_db.commit()

        # Calculate new average rating (publicly visible ratings only)
        avg_rating, num_ratings = _public_rating_stats(session_db, movie_id)

        return jsonify(
            {
                "status": "success",
                "rating": rating_value,
                "avg_rating": float(avg_rating) if avg_rating else 0,
                "num_ratings": num_ratings,
            }
        )
    finally:
        session_db.close()


@app.route("/movie/<int:movie_id>/review", methods=["POST"])
def submit_review(movie_id):
    """Submit a review for a movie"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to submit a review", "warning")
            return redirect(url_for("login", next=_current_relative_url()))

        review_content = request.form.get("review_content", "").strip()

        # Validate review content
        if not review_content:
            flash("Review cannot be empty", "danger")
            return redirect(url_for("movie_detail", movie_id=movie_id))

        if len(review_content) < 10:
            flash("Review must be at least 10 characters long", "danger")
            return redirect(url_for("movie_detail", movie_id=movie_id))

        if len(review_content) > MAX_REVIEW_LENGTH:
            flash(f"Review must be {MAX_REVIEW_LENGTH} characters or fewer", "danger")
            return redirect(url_for("movie_detail", movie_id=movie_id))

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            flash("Movie not found", "danger")
            return redirect(url_for("index"))

        # Check if user already reviewed this movie. Soft-deleted rows are
        # included: the unique (user, movie) constraint means a moderated
        # review would otherwise be silently overwritten and stay hidden.
        existing_review = (
            session_db.query(Review).filter_by(user_id=user.id, movie_id=movie_id).first()
        )

        if existing_review and existing_review.is_deleted:
            flash("This review was removed by a moderator and cannot be edited.", "danger")
            return redirect(url_for("movie_detail", movie_id=movie_id))

        if existing_review:
            # Update existing review
            existing_review.content = review_content
            flash("Your review has been updated", "success")
        else:
            # Create new review
            new_review = Review(user_id=user.id, movie_id=movie_id, content=review_content)
            session_db.add(new_review)
            flash("Your review has been submitted", "success")

        session_db.commit()
        return redirect(url_for("movie_detail", movie_id=movie_id))
    finally:
        session_db.close()


@app.route("/movie/<int:movie_id>/review/<int:review_id>/delete", methods=["POST"])
def delete_review(movie_id, review_id):
    """Delete a review"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        review = session_db.query(Review).filter_by(id=review_id, movie_id=movie_id).first()

        if not review:
            return jsonify({"error": "Review not found"}), 404

        # Check if user owns this review
        if review.user_id != user.id:
            return jsonify({"error": "Unauthorized"}), 403

        # A moderated review stays as the moderator left it; deleting it would
        # let the author wipe the record and post a fresh one
        if review.is_deleted:
            return jsonify({"error": "This review was removed by a moderator"}), 403

        session_db.delete(review)
        session_db.commit()

        flash("Review deleted successfully", "success")
        return jsonify({"status": "deleted"})
    finally:
        session_db.close()


# ==========================================
# NEW: RECOMMENDATIONS ROUTE (FEATURE 2)
# ==========================================


@app.route("/recommendations")
def recommendations():
    """User's personalized recommendations page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to see personalized recommendations", "warning")
            return redirect(url_for("login", next=_current_relative_url()))

        # Get personalized recommendations
        recommended_movies = get_personalized_recommendations(session_db, user, limit=12)

        return render_template(
            "recommendations.html",
            recommendations=recommended_movies,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


# ==========================================
# DIRECTOR ROUTES
# ==========================================


# Director and studio listings count a movie once it has this many votes;
# the detail pages use the same rule so the counts agree
LISTING_MIN_VOTES = 10

_DIRECTOR_SORTS = {
    "movies": lambda q: (desc("movie_count"), Person.id),
    "avg_rating": lambda q: (desc("avg_rating"), desc("movie_count"), Person.id),
    "total_revenue": lambda q: (desc("total_revenue"), Person.id),
    "name": lambda q: (Person.name, Person.id),
}
_DIRECTOR_MIN_MOVIES = (1, 3, 5, 10)


@app.route("/directors")
def directors():
    """Director spotlight page: search, sort and minimum count run in SQL"""
    session_db = get_db_session()
    try:
        page = _html_page_arg()
        per_page = 24

        user = get_current_user(session_db)

        search = request.args.get("q", "").strip()
        sort_by = request.args.get("sort", "movies")
        if sort_by not in _DIRECTOR_SORTS:
            sort_by = "movies"
        min_movies = request.args.get("min_movies", default=3, type=int)
        if min_movies not in _DIRECTOR_MIN_MOVIES:
            min_movies = 3

        directors_query = (
            session_db.query(
                Person.id,
                Person.name,
                func.count(Movie.id).label("movie_count"),
                func.avg(Movie.vote_average).label("avg_rating"),
                func.sum(Movie.revenue).label("total_revenue"),
            )
            .join(Crew, Person.id == Crew.person_id)
            .join(Movie, Crew.movie_id == Movie.id)
            .filter(Crew.job == "Director")
            .filter(Movie.vote_count > LISTING_MIN_VOTES)
        )
        if search:
            directors_query = directors_query.filter(
                Person.name.ilike(_contains_pattern(search), escape="\\")
            )
        directors_query = (
            directors_query.group_by(Person.id, Person.name)
            .having(func.count(Movie.id) >= min_movies)
            .order_by(*_DIRECTOR_SORTS[sort_by](directors_query))
        )

        total = directors_query.order_by(None).count()
        total_pages = (total + per_page - 1) // per_page if total else 1
        page = max(1, min(page, total_pages))
        directors_data = directors_query.limit(per_page).offset((page - 1) * per_page).all()

        # Top 3 rated movies for every director on the page, in one query
        director_ids = [d.id for d in directors_data]
        top_by_director = {director_id: [] for director_id in director_ids}
        if director_ids:
            rank = (
                func.row_number()
                .over(
                    partition_by=Crew.person_id,
                    order_by=(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id),
                )
                .label("rank")
            )
            ranked = (
                select(
                    Crew.person_id,
                    Movie.id,
                    Movie.title,
                    Movie.release_date,
                    Movie.vote_average,
                    rank,
                )
                .join(Movie, Crew.movie_id == Movie.id)
                .where(
                    Crew.person_id.in_(director_ids),
                    Crew.job == "Director",
                    Movie.vote_count > LISTING_MIN_VOTES,
                )
                .subquery()
            )
            for row in session_db.execute(
                select(ranked).where(ranked.c.rank <= 3).order_by(ranked.c.person_id, ranked.c.rank)
            ):
                top_by_director[row.person_id].append(
                    {
                        "id": row.id,
                        "title": row.title,
                        "year": row.release_date.year if row.release_date else None,
                        "vote_average": row.vote_average,
                    }
                )

        directors_list = [
            {
                "id": d.id,
                "name": d.name,
                "movie_count": d.movie_count,
                "avg_rating": d.avg_rating or 0,
                "total_revenue": int(d.total_revenue or 0),
                "top_movies": top_by_director[d.id],
            }
            for d in directors_data
        ]

        return render_template(
            "directors.html",
            directors=directors_list,
            page=page,
            total_pages=total_pages,
            total=total,
            search=search,
            sort_by=sort_by,
            min_movies=min_movies,
            min_movie_options=_DIRECTOR_MIN_MOVIES,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/director/<int:director_id>")
def director_detail(director_id):
    """Individual director filmography page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)

        # Get director info
        director = session_db.query(Person).filter_by(id=director_id).first()
        if not director:
            abort(404)

        # Every movie directed by this person, newest first (undated last on
        # every database: Postgres would otherwise put NULL dates first)
        movies = (
            session_db.query(Movie)
            .join(Crew, Movie.id == Crew.movie_id)
            .filter(Crew.person_id == director_id)
            .filter(Crew.job == "Director")
            .options(selectinload(Movie.genres))
            .order_by(desc(Movie.release_date).nulls_last(), Movie.id)
            .distinct()
            .all()
        )
        if not movies:
            # A real person, but not a director (an actor-only id, for example)
            abort(404)

        # Calculate statistics. Averages use rated movies only: TMDB reports
        # 0.0 for movies nobody has voted on yet.
        total_movies = len(movies)
        rated_values = [
            float(m.vote_average) for m in movies if m.vote_average is not None and m.vote_count
        ]
        avg_rating = sum(rated_values) / len(rated_values) if rated_values else None
        total_revenue = sum(m.revenue or 0 for m in movies)

        years = [m.release_date.year for m in movies if m.release_date]
        first_year = min(years) if years else None
        last_year = max(years) if years else None
        years_active = (last_year - first_year + 1) if first_year and last_year else 0

        # Genre distribution
        genre_counts = {}
        for movie in movies:
            for genre in movie.genres:
                genre_counts[genre.name] = genre_counts.get(genre.name, 0) + 1

        genres = [
            {"name": name, "count": count}
            for name, count in sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)
        ]

        # Chart data (movies by year)
        year_data = {}
        for movie in movies:
            if movie.release_date:
                year = movie.release_date.year
                if year not in year_data:
                    year_data[year] = {"ratings": [], "revenues": []}
                if movie.vote_average is not None and movie.vote_count:
                    year_data[year]["ratings"].append(float(movie.vote_average))
                year_data[year]["revenues"].append((movie.revenue or 0) / 1000000)

        chart_years = sorted(year_data.keys())
        # None leaves a gap in the chart for years with no rated movie, instead
        # of plotting a misleading 0
        chart_ratings = [
            (
                round(sum(year_data[y]["ratings"]) / len(year_data[y]["ratings"]), 2)
                if year_data[y]["ratings"]
                else None
            )
            for y in chart_years
        ]
        chart_revenues = [sum(year_data[y]["revenues"]) for y in chart_years]

        stats = {
            "total_movies": total_movies,
            "avg_rating": avg_rating,
            "total_revenue": total_revenue,
            "years_active": years_active,
            "first_year": first_year,
            "last_year": last_year,
            "genres": genres,
        }

        chart_data = {
            "years": chart_years,
            "ratings": chart_ratings,
            "revenues": chart_revenues,
        }

        movies_list = [
            {
                "id": m.id,
                "title": m.title,
                "year": m.release_date.year if m.release_date else None,
                "poster_path": m.poster_path,
                "vote_average": m.vote_average,
                "revenue": m.revenue,
                "runtime": m.runtime,
                "genres": [g.name for g in m.genres],
            }
            for m in movies
        ]

        return render_template(
            "director_detail.html",
            director=director,
            movies=movies_list,
            stats=stats,
            chart_data=chart_data,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


# ==========================================
# MAIN ROUTES
# ==========================================


# Data that only changes at the weekly sync is cached for this long
AGGREGATE_CACHE_SECONDS = 3600


def _cached(key, compute, timeout=AGGREGATE_CACHE_SECONDS):
    """Return compute() through the app cache under `key`.

    compute must return plain, picklable data (no ORM objects). The suite runs
    with caching off and calls compute() directly with the request's session.
    """
    if app.config.get("TESTING"):
        return compute()
    value = cache.get(key)
    if value is None:
        value = compute()
        cache.set(key, value, timeout=timeout)
    return value


def _year_range_filter(column, first_year, last_year):
    """Rows whose date falls in first_year..last_year, written so an index on
    the date column can be used (extract('year', ...) can't use one)."""
    return and_(
        column >= date(first_year, 1, 1),
        column < date(last_year + 1, 1, 1),
    )


def _year_options(session_db):
    """Distinct release years, newest first, for filter dropdowns."""

    def compute():
        rows = (
            session_db.query(extract("year", Movie.release_date).label("year"))
            .filter(Movie.release_date.isnot(None))
            .distinct()
            .order_by(desc("year"))
            .all()
        )
        return [int(y[0]) for y in rows if y[0]]

    return _cached("options:years", compute)


def _genre_options(session_db):
    """(id, name) pairs for genre dropdowns."""

    def compute():
        return [
            {"id": g.id, "name": g.name}
            for g in session_db.query(Genre.id, Genre.name).order_by(Genre.name).all()
        ]

    return _cached("options:genres", compute)


def _decade_options():
    return list(range(1920, utcnow().year + 1, 10))


def _home_stats(session_db):
    """Hero counts, cached (they only change at the weekly sync)."""

    def compute():
        total_movies = session_db.query(func.count(Movie.id)).scalar()
        total_genres = session_db.query(func.count(Genre.id)).scalar()
        total_directors = (
            session_db.query(func.count(func.distinct(Crew.person_id)))
            .filter(Crew.job == "Director")
            .scalar()
        )
        return total_movies, total_genres, total_directors

    return _cached("home:stats", compute)


@app.route("/")
def index():
    """Homepage with featured movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        # Every home page list skips mature and admin-hidden movies (FS-60)
        featured = session.query(Movie).filter(*_featured_filters())

        # Top rated, among movies with enough votes for the average to mean something
        top_movies = (
            featured.filter(Movie.vote_count >= TOP_RATED_MIN_VOTES)
            .order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
            .limit(12)
            .all()
        )

        # Upcoming releases (soonest first)
        upcoming_movies = (
            featured.filter(Movie.release_date >= local_today())
            .order_by(Movie.release_date, Movie.id)
            .limit(12)
            .all()
        )

        # Most popular
        popular_movies = featured.order_by(desc(Movie.popularity), Movie.id).limit(12).all()

        # Featured movie of the day (from the Hidden Gems pool)
        movie_of_the_day = get_movie_of_the_day(session)

        total_movies, total_genres, total_directors = _home_stats(session)

        return render_template(
            "index.html",
            top_movies=top_movies,
            top_rated_min_votes=TOP_RATED_MIN_VOTES,
            upcoming_movies=upcoming_movies,
            popular_movies=popular_movies,
            movie_of_the_day=movie_of_the_day,
            total_movies=total_movies,
            total_genres=total_genres,
            total_directors=total_directors,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


def _apply_movie_filters(
    query,
    genre_id=None,
    year=None,
    decade=None,
    rating_min=None,
    rating_max=None,
    runtime_min=None,
    runtime_max=None,
    min_vote_count=None,
    status=None,
):
    """Filters shared by /movies and /api/v1/movies, so infinite scroll's API
    pages match the server-rendered first page exactly."""
    if genre_id:
        query = query.join(Movie.genres).filter(Genre.id == genre_id)
    # Decade takes precedence over year when both are given
    if decade:
        query = query.filter(_year_range_filter(Movie.release_date, decade, decade + 9))
    elif year:
        query = query.filter(_year_range_filter(Movie.release_date, year, year))
    if rating_min is not None:
        query = query.filter(Movie.vote_average >= rating_min)
    if rating_max is not None:
        query = query.filter(Movie.vote_average <= rating_max)
    if runtime_min is not None:
        query = query.filter(Movie.runtime >= runtime_min)
    if runtime_max is not None:
        query = query.filter(Movie.runtime <= runtime_max)
    if min_vote_count:
        query = query.filter(Movie.vote_count >= min_vote_count)
    if status:
        query = query.filter(Movie.status == status)
    return query


def _num(value):
    """Decimal or None as float or None; keeps a real 0.0 as 0.0."""
    return float(value) if value is not None else None


def _movie_summary(movie):
    """JSON shape for a movie in API lists."""
    return {
        "id": movie.id,
        "tmdb_id": movie.tmdb_id,
        "title": movie.title,
        "original_title": movie.original_title,
        "overview": movie.overview,
        "release_date": movie.release_date.isoformat() if movie.release_date else None,
        "runtime": movie.runtime,
        "vote_average": _num(movie.vote_average),
        "vote_count": movie.vote_count,
        "popularity": _num(movie.popularity),
        "poster_path": movie.poster_path,
        "backdrop_path": movie.backdrop_path,
        "genres": [{"id": g.id, "name": g.name} for g in movie.genres],
    }


# Sorts shared by /movies and /api/v1/movies. Every ordering ends with
# Movie.id, so pages never repeat or skip movies with equal values.
MOVIE_SORTS = ("popularity", "rating", "release_date", "upcoming", "title")


def _apply_movie_sort(query, sort_by):
    if sort_by == "rating":
        return query.filter(Movie.vote_count > 50).order_by(
            desc(Movie.vote_average), desc(Movie.vote_count), Movie.id
        )
    if sort_by == "release_date":
        return query.filter(Movie.release_date.isnot(None)).order_by(
            desc(Movie.release_date), Movie.id
        )
    if sort_by == "upcoming":
        return query.filter(Movie.release_date >= local_today()).order_by(
            Movie.release_date, Movie.id
        )
    if sort_by == "title":
        return query.order_by(Movie.title, Movie.id)
    return query.order_by(desc(Movie.popularity).nulls_last(), Movie.id)


@app.route("/movies")
def movies():
    """All movies page with filters and pagination"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        # Get filter parameters
        genre_id = request.args.get("genre", type=int)
        sort_by = request.args.get("sort", default="popularity")
        page = _html_page_arg()

        # Advanced filter parameters
        year = request.args.get("year", type=int)
        decade = request.args.get("decade", type=int)
        rating_min = request.args.get("rating_min", type=float)
        rating_max = request.args.get("rating_max", type=float)
        runtime_min = request.args.get("runtime_min", type=int)
        runtime_max = request.args.get("runtime_max", type=int)
        min_vote_count = request.args.get("min_vote_count", type=int)
        status_filter = request.args.get("status", "")

        query = _apply_movie_filters(
            _content_filtered(session.query(Movie)),
            genre_id=genre_id,
            year=year,
            decade=decade,
            rating_min=rating_min,
            rating_max=rating_max,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            min_vote_count=min_vote_count,
            status=status_filter,
        )
        if sort_by not in MOVIE_SORTS:
            sort_by = "popularity"
        query = _apply_movie_sort(query, sort_by)

        # Pagination
        per_page = 20
        offset = (page - 1) * per_page
        total_movies = query.order_by(None).count()
        movies_list = query.limit(per_page).offset(offset).all()

        all_genres = _genre_options(session)
        available_years = _year_options(session)
        available_decades = _decade_options()

        # Calculate pagination info
        total_pages = (total_movies + per_page - 1) // per_page

        return render_template(
            "movies.html",
            movies=movies_list,
            genres=all_genres,
            current_genre=genre_id,
            current_sort=sort_by,
            page=page,
            total_pages=total_pages,
            total_movies=total_movies,
            available_years=available_years,
            available_decades=available_decades,
            selected_year=year,
            selected_decade=decade,
            selected_rating_min=rating_min,
            selected_rating_max=rating_max,
            selected_runtime_min=runtime_min,
            selected_runtime_max=runtime_max,
            selected_min_vote_count=min_vote_count,
            selected_status=status_filter,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@app.route("/hidden-gems")
def hidden_gems():
    """Hidden gems page - high rated, low popularity movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        # Get filter parameters
        genre_id = request.args.get("genre", type=int)
        decade = request.args.get("decade", type=int)
        min_rating = request.args.get("min_rating", default=GEM_MIN_RATING, type=float)
        max_popularity = request.args.get("max_popularity", default=GEM_MAX_POPULARITY, type=float)
        sort_by = request.args.get("sort", default="gem_score")
        page = _html_page_arg()
        per_page = 24

        # Base query for hidden gems
        query = _content_filtered(session.query(Movie)).filter(
            Movie.vote_average >= min_rating,
            Movie.popularity <= max_popularity,
            Movie.vote_count >= GEM_MIN_VOTES,
        )

        # Apply genre filter
        if genre_id:
            query = query.join(Movie.genres).filter(Genre.id == genre_id)

        # Apply decade filter
        if decade:
            query = query.filter(_year_range_filter(Movie.release_date, decade, decade + 9))

        # Apply sorting (Movie.id last keeps pages stable)
        if sort_by == "rating":
            query = query.order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
        elif sort_by == "most_hidden":
            query = query.order_by(Movie.popularity, Movie.id)
        elif sort_by == "release_date":
            query = query.filter(Movie.release_date.isnot(None)).order_by(
                desc(Movie.release_date), Movie.id
            )
        else:  # gem_score (default)
            query = query.order_by(
                desc(Movie.vote_average / (func.log(Movie.popularity + 2) * 2)), Movie.id
            )

        # Get total count for pagination
        total_gems = query.order_by(None).count()

        # Apply pagination
        offset = (page - 1) * per_page
        gems_list = query.limit(per_page).offset(offset).all()

        all_genres = _genre_options(session)
        available_decades = _decade_options()

        # Calculate pagination info
        total_pages = (total_gems + per_page - 1) // per_page

        return render_template(
            "hidden_gems.html",
            gems=gems_list,
            genres=all_genres,
            selected_genre=genre_id,
            selected_decade=decade,
            min_rating=min_rating,
            max_popularity=max_popularity,
            sort_by=sort_by,
            page=page,
            total_pages=total_pages,
            total_gems=total_gems,
            available_decades=available_decades,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@app.route("/top-actors")
def top_actors():
    """Top actors page - actors who appear in most movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        sort_by = request.args.get("sort", default="movie_count")
        if sort_by not in ("movie_count", "avg_rating", "avg_popularity", "name"):
            sort_by = "movie_count"
        page = _html_page_arg()
        per_page = 24

        def compute():
            # Count movies per actor. The aggregate scans the whole cast table,
            # so the result is cached; Person.id last keeps pages stable.
            query = (
                session.query(
                    Person.id,
                    Person.name,
                    Person.profile_path,
                    func.count(func.distinct(Cast.movie_id)).label("movie_count"),
                    func.avg(Movie.vote_average).label("avg_rating"),
                    func.avg(Movie.popularity).label("avg_popularity"),
                    func.count().over().label("total_actors"),
                )
                .join(Cast, Person.id == Cast.person_id)
                .join(Movie, Cast.movie_id == Movie.id)
                .filter(Movie.vote_count > 20)
                .group_by(Person.id, Person.name, Person.profile_path)
                .having(func.count(func.distinct(Cast.movie_id)) >= 2)
            )
            orderings = {
                "avg_rating": (desc("avg_rating"), Person.id),
                "avg_popularity": (desc("avg_popularity"), Person.id),
                "name": (Person.name, Person.id),
                "movie_count": (desc("movie_count"), Person.id),
            }
            rows = (
                query.order_by(*orderings[sort_by])
                .limit(per_page)
                .offset((page - 1) * per_page)
                .all()
            )
            total = rows[0].total_actors if rows else query.order_by(None).count()
            return total, [
                {
                    "person": {"id": r.id, "name": r.name, "profile_path": r.profile_path},
                    "movie_count": r.movie_count,
                    "avg_rating": float(r.avg_rating) if r.avg_rating is not None else None,
                    "avg_popularity": (
                        float(r.avg_popularity) if r.avg_popularity is not None else None
                    ),
                }
                for r in rows
            ]

        total_actors, actors_list = _cached(f"top_actors:{sort_by}:{page}", compute)

        # Calculate pagination info
        total_pages = (total_actors + per_page - 1) // per_page

        return render_template(
            "top_actors.html",
            actors=actors_list,
            sort_by=sort_by,
            page=page,
            total_pages=total_pages,
            total_actors=total_actors,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@app.route("/actor/<int:actor_id>")
def actor_detail(actor_id):
    """Actor detail page with filmography"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        # Get actor info
        actor = session.query(Person).filter_by(id=actor_id).first()

        if not actor:
            abort(404)

        # Filmography, newest first (undated movies last on every database)
        filmography_raw = (
            session.query(Movie, Cast)
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id)
            .order_by(desc(Movie.release_date).nulls_last(), Movie.id, Cast.cast_order)
            .all()
        )
        if not filmography_raw:
            # A real person, but not in any cast (a director-only id, for example)
            abort(404)

        # (movie, character, cast_order), one entry per movie: an actor with two
        # roles in one film gets them joined rather than listed twice
        filmography = []
        by_movie = {}
        for movie, cast in filmography_raw:
            character = cast.character_name or "Unknown"
            if movie.id in by_movie:
                index = by_movie[movie.id]
                previous_movie, previous_character, order = filmography[index]
                filmography[index] = (previous_movie, f"{previous_character} / {character}", order)
                continue
            by_movie[movie.id] = len(filmography)
            filmography.append((movie, character, cast.cast_order or 0))

        # Calculate statistics
        total_movies = len(filmography)
        avg_rating = (
            session.query(func.avg(Movie.vote_average))
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id, Movie.vote_count > 20)
            .scalar()
        )

        # Get genres this actor appears in most
        top_genres = (
            session.query(Genre.name, func.count(func.distinct(Movie.id)).label("count"))
            .join(Movie.genres)
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id)
            .group_by(Genre.name)
            .order_by(desc("count"), Genre.name)
            .limit(5)
            .all()
        )

        return render_template(
            "actor_detail.html",
            actor=actor,
            filmography=filmography,
            total_movies=total_movies,
            avg_rating=round(avg_rating, 1) if avg_rating else None,
            top_genres=top_genres,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


TMDB_EXTRAS_CACHE_SECONDS = 24 * 3600


def _tmdb_movie_extras(tmdb_id):
    """Trailer and US watch providers for a movie, cached per movie for a day."""

    def compute():
        trailer = get_trailer_for_movie(tmdb_id)
        try:
            watch_providers = TMDBClient().get_watch_providers(tmdb_id)
        except Exception as exc:
            logger.warning(
                f"Unable to fetch watch providers for tmdb_id={tmdb_id}: {exc}",
                exc_info=True,
            )
            watch_providers = {}
        return {"trailer": trailer, "watch_providers": watch_providers}

    return _cached(f"tmdb:extras:{tmdb_id}", compute, timeout=TMDB_EXTRAS_CACHE_SECONDS)


@app.route("/movie/<int:movie_id>")
def movie_detail(movie_id):
    """Movie detail page with ratings and reviews"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        movie = session.query(Movie).filter_by(id=movie_id).first()

        if not movie:
            abort(404)

        # Get cast (top 10)
        cast = (
            session.query(Cast, Person)
            .join(Person)
            .filter(Cast.movie_id == movie_id)
            .order_by(Cast.cast_order)
            .limit(10)
            .all()
        )

        # Get directors
        directors = (
            session.query(Crew, Person)
            .join(Person)
            .filter(Crew.movie_id == movie_id, Crew.job == "Director")
            .all()
        )

        # Get similar movies (sorted by genre match and rating)
        similar_movies = get_similar_movies(session, movie_id, limit=6, movie=movie)

        # Trailer and streaming providers come from TMDB. Both are cached for a
        # day per movie, so a slow TMDB can't hold up every movie page view.
        tmdb_extras = _tmdb_movie_extras(movie.tmdb_id)
        trailer = tmdb_extras["trailer"]
        watch_providers = tmdb_extras["watch_providers"]

        # Check if movie is in user's favorites/watchlist (EXISTS, not the whole list)
        is_favorited = False
        is_in_watchlist = False
        if user:
            is_favorited = _association_exists(
                session, user_favorites_table, user_id=user.id, movie_id=movie.id
            )
            is_in_watchlist = _association_exists(
                session, user_watchlist_table, user_id=user.id, movie_id=movie.id
            )

        # The user's own rating and review, so the forms show what they wrote
        user_rating = None
        user_review = None
        if user:
            user_rating = (
                session.query(Rating)
                .filter_by(user_id=user.id, movie_id=movie_id, is_deleted=False)
                .first()
            )
            user_review = (
                session.query(Review).filter_by(user_id=user.id, movie_id=movie_id).first()
            )

        # NEW: Get average rating and count (publicly visible ratings only)
        avg_rating, num_ratings = _public_rating_stats(session, movie_id)

        # NEW: Get reviews (paginated)
        review_page = _html_page_arg()
        per_page = 10

        # The join to User already happens for the visibility filter; reuse it so
        # review.user.username doesn't cost one query per review
        reviews_query = (
            _visible_reviews_query(session, movie_id)
            .options(contains_eager(Review.user))
            .order_by(desc(Review.created_at), desc(Review.id))
        )

        total_reviews = reviews_query.order_by(None).count()
        reviews = reviews_query.limit(per_page).offset((review_page - 1) * per_page).all()
        total_review_pages = (total_reviews + per_page - 1) // per_page

        # NEW: Get personalized recommendations (if user logged in)
        personalized_recs = []
        if user:
            personalized_recs = get_personalized_recommendations(
                session, user, limit=6, exclude_ids=[movie.id]
            )

        return render_template(
            "movie_detail.html",
            movie=movie,
            cast=cast,
            directors=directors,
            similar_movies=similar_movies,
            trailer=trailer,
            watch_providers=watch_providers,
            current_user=user,
            is_favorited=is_favorited,
            is_in_watchlist=is_in_watchlist,
            user_rating=user_rating,
            user_review=user_review,
            max_review_length=MAX_REVIEW_LENGTH,
            avg_rating=round(avg_rating, 1) if avg_rating else None,
            num_ratings=num_ratings or 0,
            reviews=reviews,
            review_page=review_page,
            total_reviews=total_reviews,
            total_review_pages=total_review_pages,
            personalized_recommendations=personalized_recs,
            config=Config,
        )
    finally:
        session.close()


# A movie counts toward a rating average once it has this many votes
ANALYTICS_MIN_VOTES = 50


def _number(value, digits=None):
    """Plain float (rounded) or None, so cached data and JSON never carry Decimal."""
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if digits is not None else value


def _analytics_data(session):
    """Every aggregate on /analytics, as plain data, cached between syncs."""

    def compute():
        genre_stats = [
            {"name": name, "count": count}
            for name, count in session.query(Genre.name, func.count(Movie.id).label("count"))
            .join(Movie.genres)
            .group_by(Genre.name)
            .order_by(desc("count"), Genre.name)
            .all()
        ]

        year_stats = [
            {"year": int(year), "count": count}
            for year, count in session.query(
                extract("year", Movie.release_date).label("year"),
                func.count(Movie.id).label("count"),
            )
            .filter(Movie.release_date.isnot(None))
            .group_by("year")
            .order_by("year")
            .all()
        ]

        genre_ratings = [
            {"name": name, "avg_rating": _number(avg, 2), "count": count}
            for name, avg, count in session.query(
                Genre.name,
                func.avg(Movie.vote_average).label("avg_rating"),
                func.count(Movie.id).label("count"),
            )
            .join(Movie.genres)
            .filter(Movie.vote_count > ANALYTICS_MIN_VOTES)
            .group_by(Genre.name)
            .having(func.count(Movie.id) >= 3)
            .order_by(desc("avg_rating"), Genre.name)
            .all()
        ]

        # Box office by genre: a movie with several genres counts toward each
        box_office_by_genre = [
            {
                "name": name,
                "total_revenue": int(total or 0),
                "avg_revenue": int(avg or 0),
                "count": count,
            }
            for name, total, avg, count in session.query(
                Genre.name,
                func.sum(Movie.revenue).label("total_revenue"),
                func.avg(Movie.revenue).label("avg_revenue"),
                func.count(Movie.id).label("count"),
            )
            .join(Movie.genres)
            .filter(Movie.revenue > 0)
            .group_by(Genre.name)
            .order_by(desc("total_revenue"), Genre.name)
            .all()
        ]

        # Budget vs revenue scatter data (up to 300 movies with known budget)
        budget_revenue_scatter = [
            [title, budget, revenue, _number(rating)]
            for title, budget, revenue, rating in session.query(
                Movie.title, Movie.budget, Movie.revenue, Movie.vote_average
            )
            .filter(Movie.budget > 1_000_000, Movie.revenue > 0)
            .order_by(desc(Movie.revenue), Movie.id)
            .limit(300)
            .all()
        ]

        # Most profitable movies (revenue - budget), top 15
        most_profitable = [
            [title, budget, revenue]
            for title, budget, revenue in session.query(Movie.title, Movie.budget, Movie.revenue)
            .filter(Movie.budget > 1_000_000, Movie.revenue > 0)
            .order_by(desc(Movie.revenue - Movie.budget), Movie.id)
            .limit(15)
            .all()
        ]

        # Top production companies (grouped by id: names aren't unique)
        top_companies = [
            {"name": name, "movie_count": count, "avg_rating": _number(avg, 2)}
            for _, name, count, avg in session.query(
                ProductionCompany.id,
                ProductionCompany.name,
                func.count(Movie.id).label("movie_count"),
                func.avg(Movie.vote_average).label("avg_rating"),
            )
            .join(ProductionCompany.movies)
            .filter(Movie.vote_count > ANALYTICS_MIN_VOTES)
            .group_by(ProductionCompany.id, ProductionCompany.name)
            .having(func.count(Movie.id) >= 2)
            .order_by(desc("movie_count"), ProductionCompany.id)
            .limit(10)
            .all()
        ]

        total_movies = session.query(func.count(Movie.id)).scalar()
        avg_rating = (
            session.query(func.avg(Movie.vote_average))
            .filter(Movie.vote_count > ANALYTICS_MIN_VOTES)
            .scalar()
        )
        total_revenue = session.query(func.sum(Movie.revenue)).filter(Movie.revenue > 0).scalar()

        return {
            "genre_stats": genre_stats,
            "year_stats": year_stats,
            "genre_ratings": genre_ratings,
            "box_office_by_genre": box_office_by_genre,
            "budget_revenue_scatter": budget_revenue_scatter,
            "most_profitable": most_profitable,
            "top_companies": top_companies,
            "total_movies": total_movies,
            "avg_rating": _number(avg_rating, 1) or 0,
            "total_revenue": int(total_revenue or 0),
        }

    return _cached("analytics:page", compute)


@app.route("/analytics")
def analytics():
    """Analytics dashboard"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        data = _analytics_data(session)
        return render_template(
            "analytics.html",
            **data,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@app.route("/analytics/export/csv")
@limiter.limit("20 per hour")
def analytics_export_csv():
    """Export analytics data as a CSV file download"""
    session = get_db_session()
    try:
        # Genre statistics
        genre_stats = (
            session.query(
                Genre.name,
                func.count(Movie.id).label("count"),
                # Same rule as /analytics: only movies with enough votes count
                # toward the average (unrated movies are stored as 0.0)
                func.avg(
                    case(
                        (Movie.vote_count > ANALYTICS_MIN_VOTES, Movie.vote_average),
                        else_=None,
                    )
                ).label("avg_rating"),
            )
            .join(Movie.genres)
            .group_by(Genre.name)
            .order_by(desc("count"), Genre.name)
            .all()
        )

        # Movies by year
        year_stats = (
            session.query(
                extract("year", Movie.release_date).label("year"),
                func.count(Movie.id).label("count"),
            )
            .filter(Movie.release_date.isnot(None))
            .group_by("year")
            .order_by("year")
            .all()
        )

        # Top 25 movies by rating
        top_rated = (
            session.query(
                Movie.title,
                Movie.vote_average,
                Movie.vote_count,
                Movie.revenue,
                Movie.release_date,
            )
            .filter(Movie.vote_count > 100)
            .order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
            .limit(25)
            .all()
        )

        # Top 25 movies by revenue
        top_revenue = (
            session.query(
                Movie.title,
                Movie.budget,
                Movie.revenue,
                Movie.vote_average,
                Movie.release_date,
            )
            .filter(Movie.revenue > 0)
            .order_by(desc(Movie.revenue), Movie.id)
            .limit(25)
            .all()
        )

        # Build CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)

        # --- Section 1: Genre Statistics ---
        writer.writerow(["GENRE STATISTICS"])
        writer.writerow(["Genre", "Movie Count", "Average Rating"])
        for name, count, avg_rating in genre_stats:
            writer.writerow([name, count, f"{avg_rating:.2f}" if avg_rating else "N/A"])

        writer.writerow([])

        # --- Section 2: Movies by Release Year ---
        writer.writerow(["MOVIES BY RELEASE YEAR"])
        writer.writerow(["Year", "Movie Count"])
        for year, count in year_stats:
            writer.writerow([year, count])

        writer.writerow([])

        # --- Section 3: Top 25 Movies by Rating ---
        writer.writerow(["TOP 25 MOVIES BY RATING"])
        writer.writerow(["Title", "Rating", "Vote Count", "Revenue", "Release Year"])
        for title, rating, vote_count, revenue, release_date in top_rated:
            writer.writerow(
                [
                    title,
                    f"{rating:.1f}" if rating else "N/A",
                    vote_count or 0,
                    f"${revenue:,}" if revenue else "N/A",
                    release_date.year if release_date else "N/A",
                ]
            )

        writer.writerow([])

        # --- Section 4: Top 25 Movies by Revenue ---
        writer.writerow(["TOP 25 MOVIES BY REVENUE"])
        writer.writerow(["Title", "Budget", "Revenue", "Rating", "Release Year"])
        for title, budget, revenue, rating, release_date in top_revenue:
            writer.writerow(
                [
                    title,
                    f"${budget:,}" if budget else "N/A",
                    f"${revenue:,}" if revenue else "N/A",
                    f"{rating:.1f}" if rating else "N/A",
                    release_date.year if release_date else "N/A",
                ]
            )

        output.seek(0)
        filename = f"movie_analytics_{utcnow().strftime('%Y%m%d')}.csv"

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        session.close()


SEARCH_RESULT_LIMIT = 50


def _movie_search_query(session, text):
    """Title or overview matches, % and _ taken literally, title matches first."""
    pattern = _contains_pattern(text)
    title_match = Movie.title.ilike(pattern, escape="\\")
    return (
        session.query(Movie)
        .filter(title_match | Movie.overview.ilike(pattern, escape="\\"))
        .order_by(
            case((title_match, 0), else_=1),
            desc(Movie.popularity).nulls_last(),
            Movie.id,
        )
    )


@app.route("/search")
def search():
    """Search movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        query = request.args.get("q", "").strip()

        if not query:
            return render_template(
                "search.html",
                movies=[],
                query="",
                total=0,
                limit=SEARCH_RESULT_LIMIT,
                current_user=user,
                config=Config,
            )

        search_query = _content_filtered(_movie_search_query(session, query))
        total = search_query.order_by(None).count()
        movies_list = search_query.limit(SEARCH_RESULT_LIMIT).all()

        return render_template(
            "search.html",
            movies=movies_list,
            query=query,
            total=total,
            limit=SEARCH_RESULT_LIMIT,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


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


# ==========================================
# RESTful API ENDPOINTS
# ==========================================


@app.route("/api/v1/movies", methods=["GET"])
@limiter.limit("60 per minute")
def api_get_movies():
    """Get list of movies with filtering and pagination"""
    session = get_db_session()
    try:
        # Get query parameters
        page, error = _api_positive_int_arg("page", 1)
        if error:
            return error
        per_page, error = _api_positive_int_arg("per_page", 20, max_value=100)
        if error:
            return error
        sort_by = request.args.get("sort", default="popularity")
        if sort_by not in MOVIE_SORTS:
            sort_by = "popularity"

        query = _apply_movie_filters(
            session.query(Movie),
            genre_id=request.args.get("genre", type=int),
            year=request.args.get("year", type=int),
            decade=request.args.get("decade", type=int),
            rating_min=request.args.get("min_rating", type=float),
            rating_max=request.args.get("max_rating", type=float),
            runtime_min=request.args.get("runtime_min", type=int),
            runtime_max=request.args.get("runtime_max", type=int),
            min_vote_count=request.args.get("min_vote_count", type=int),
            status=request.args.get("status", ""),
        )
        # Opt-in: infinite scroll passes this when the family-friendly toggle is on
        if request.args.get("exclude_mature") in ("1", "true"):
            query = query.filter(Movie.is_mature.is_(False))
        query = _apply_movie_sort(query, sort_by)

        # Pagination
        total = query.order_by(None).count()
        offset = (page - 1) * per_page
        movies = query.options(selectinload(Movie.genres)).limit(per_page).offset(offset).all()

        movies_data = [_movie_summary(movie) for movie in movies]

        return jsonify(
            {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": (total + per_page - 1) // per_page,
                "movies": movies_data,
            }
        )
    finally:
        session.close()


@app.route("/api/v1/movies/<int:movie_id>", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def api_get_movie(movie_id):
    """Get detailed information about a specific movie"""
    session = get_db_session()
    try:
        movie = session.query(Movie).filter_by(id=movie_id).first()

        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        # Get cast
        cast_data = (
            session.query(Cast, Person)
            .join(Person)
            .filter(Cast.movie_id == movie_id)
            .order_by(Cast.cast_order)
            .limit(10)
            .all()
        )

        # Get crew
        crew_data = session.query(Crew, Person).join(Person).filter(Crew.movie_id == movie_id).all()

        # Get average rating (publicly visible ratings only)
        avg_rating, num_ratings = _public_rating_stats(session, movie_id)

        # Serialize movie data
        movie_data = {
            "id": movie.id,
            "tmdb_id": movie.tmdb_id,
            "title": movie.title,
            "original_title": movie.original_title,
            "overview": movie.overview,
            "release_date": (movie.release_date.isoformat() if movie.release_date else None),
            "runtime": movie.runtime,
            "budget": movie.budget,
            "revenue": movie.revenue,
            "vote_average": _num(movie.vote_average),
            "vote_count": movie.vote_count,
            "popularity": _num(movie.popularity),
            "poster_path": movie.poster_path,
            "backdrop_path": movie.backdrop_path,
            "imdb_id": movie.imdb_id,
            "tagline": movie.tagline,
            "status": movie.status,
            "genres": [{"id": g.id, "name": g.name} for g in movie.genres],
            "production_companies": [{"id": c.id, "name": c.name} for c in movie.companies],
            "cast": [
                {
                    "person_id": person.id,
                    "name": person.name,
                    "character": cast.character_name,
                    "order": cast.cast_order,
                    "profile_path": person.profile_path,
                }
                for cast, person in cast_data
            ],
            "crew": [
                {
                    "person_id": person.id,
                    "name": person.name,
                    "job": crew.job,
                    "department": crew.department,
                }
                for crew, person in crew_data
            ],
            "user_rating": {
                "average": _num(avg_rating),
                "count": num_ratings or 0,
            },
        }

        return jsonify(movie_data)
    finally:
        session.close()


@app.route("/api/v1/movies/search", methods=["GET"])
@limiter.limit("30 per minute")
def api_search_movies():
    """Search for movies by title"""
    session = get_db_session()
    try:
        query_text = request.args.get("q", "").strip()
        page, error = _api_positive_int_arg("page", 1)
        if error:
            return error
        per_page, error = _api_positive_int_arg("per_page", 20, max_value=100)
        if error:
            return error

        if not query_text:
            return jsonify({"error": "Query parameter 'q' is required"}), 400

        search_query = _movie_search_query(session, query_text)

        total = search_query.order_by(None).count()
        offset = (page - 1) * per_page
        movies = search_query.limit(per_page).offset(offset).all()

        # Serialize
        movies_data = []
        for movie in movies:
            movies_data.append(
                {
                    "id": movie.id,
                    "tmdb_id": movie.tmdb_id,
                    "title": movie.title,
                    "overview": movie.overview,
                    "release_date": (
                        movie.release_date.isoformat() if movie.release_date else None
                    ),
                    "vote_average": _num(movie.vote_average),
                    "poster_path": movie.poster_path,
                }
            )

        return jsonify(
            {
                "query": query_text,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": (total + per_page - 1) // per_page,
                "movies": movies_data,
            }
        )
    finally:
        session.close()


@app.route("/api/v1/genres", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def api_get_genres():
    """Get all genres"""
    session = get_db_session()
    try:
        genres = session.query(Genre).order_by(Genre.name).all()

        genres_data = [
            {"id": genre.id, "tmdb_id": genre.tmdb_id, "name": genre.name} for genre in genres
        ]

        return jsonify({"genres": genres_data})
    finally:
        session.close()


@app.route("/api/v1/analytics/overview", methods=["GET"])
@limiter.limit("100 per day")
@cache.cached(timeout=3600)
def api_analytics_overview():
    """Get overview analytics"""
    session = get_db_session()
    try:
        # Total movies
        total_movies = session.query(func.count(Movie.id)).scalar()

        # Average rating
        avg_rating = (
            session.query(func.avg(Movie.vote_average)).filter(Movie.vote_count > 50).scalar()
        )

        # Total revenue
        total_revenue = session.query(func.sum(Movie.revenue)).filter(Movie.revenue > 0).scalar()

        # Movies by year
        movies_by_year = (
            session.query(
                extract("year", Movie.release_date).label("year"),
                func.count(Movie.id).label("count"),
            )
            .filter(Movie.release_date.isnot(None))
            .group_by("year")
            .order_by("year")
            .all()
        )

        return jsonify(
            {
                "total_movies": total_movies,
                "average_rating": _num(avg_rating),
                # SUM(bigint) is NUMERIC on Postgres (a Decimal, which JSON would
                # send as a string); int() keeps it a number everywhere
                "total_revenue": int(total_revenue or 0),
                "movies_by_year": [
                    {"year": int(year), "count": count} for year, count in movies_by_year
                ],
            }
        )
    finally:
        session.close()


@app.route("/api/v1/analytics/genres", methods=["GET"])
@limiter.limit("100 per day")
@cache.cached(timeout=3600)
def api_analytics_genres():
    """Get genre analytics"""
    session = get_db_session()
    try:
        # Genre distribution
        genre_stats = (
            session.query(
                Genre.name,
                func.count(Movie.id).label("count"),
                func.avg(Movie.vote_average).label("avg_rating"),
            )
            .join(Movie.genres)
            .filter(Movie.vote_count > 50)
            .group_by(Genre.name)
            .order_by(desc("count"), Genre.name)
            .all()
        )

        genres_data = [
            {
                "name": name,
                "movie_count": count,
                "average_rating": _num(avg_rating),
            }
            for name, count, avg_rating in genre_stats
        ]

        return jsonify({"genres": genres_data})
    finally:
        session.close()


@app.route("/api/v1/analytics/top-movies", methods=["GET"])
@limiter.limit("100 per day")
@cache.cached(
    timeout=3600,
    # Key on the two real parameters only, so junk query strings can't fill the cache
    make_cache_key=lambda: "api_top_movies:%s:%s"
    % (request.args.get("metric", "rating"), request.args.get("limit", "10")),
)
def api_analytics_top_movies():
    """Get top movies by various metrics"""
    session = get_db_session()
    try:
        metric = request.args.get("metric", "rating")
        limit, error = _api_positive_int_arg("limit", 10, max_value=100)
        if error:
            return error

        if metric == "rating":
            movies = (
                session.query(Movie)
                .filter(Movie.vote_count > 100)
                .order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
                .limit(limit)
                .all()
            )
        elif metric == "revenue":
            movies = (
                session.query(Movie)
                .filter(Movie.revenue > 0)
                .order_by(desc(Movie.revenue), Movie.id)
                .limit(limit)
                .all()
            )
        elif metric == "popularity":
            movies = (
                session.query(Movie)
                .order_by(desc(Movie.popularity).nulls_last(), Movie.id)
                .limit(limit)
                .all()
            )
        else:
            return (
                jsonify({"error": "Invalid metric. Use: rating, revenue, or popularity"}),
                400,
            )

        movies_data = [
            {
                "id": movie.id,
                "title": movie.title,
                "vote_average": _num(movie.vote_average),
                "revenue": movie.revenue,
                "popularity": _num(movie.popularity),
            }
            for movie in movies
        ]

        return jsonify({"metric": metric, "movies": movies_data})
    finally:
        session.close()


@app.route("/api/v1/actors/search", methods=["GET"])
@limiter.limit("60 per minute")
def api_search_actors():
    """Search actors by name — used by Common Films autocomplete."""
    session = get_db_session()
    try:
        q = request.args.get("q", "").strip()
        # Optional: only return actors who share movies with already-selected actors
        with_ids = request.args.getlist("with", type=int)  # list of already-selected person IDs
        per_page, error = _api_positive_int_arg("per_page", 8, max_value=20)
        if error:
            return error

        if not q or len(q) < 2:
            return jsonify({"actors": []})

        query = (
            session.query(
                Person.id,
                Person.name,
                Person.profile_path,
                func.count(func.distinct(Cast.movie_id)).label("movie_count"),
            )
            .join(Cast, Person.id == Cast.person_id)
            .filter(Person.name.ilike(_contains_pattern(q), escape="\\"))
            .group_by(Person.id, Person.name, Person.profile_path)
        )

        # If actors already selected, restrict to those who share at least one
        # movie with ALL of them (avoids dead-end combinations)
        if with_ids:
            for wid in with_ids:
                shared_movies = (
                    session.query(Cast.movie_id).filter(Cast.person_id == wid).subquery()
                )
                query = query.filter(Cast.movie_id.in_(shared_movies))

        query = query.order_by(desc("movie_count"), Person.id).limit(per_page)
        results = query.all()

        return jsonify(
            {
                "actors": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "profile_path": r.profile_path,
                        "movie_count": r.movie_count,
                    }
                    for r in results
                ]
            }
        )
    finally:
        session.close()


@app.route("/api/v1/actors", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def api_get_actors():
    """Get list of actors with pagination"""
    session = get_db_session()
    try:
        page, error = _api_positive_int_arg("page", 1)
        if error:
            return error
        per_page, error = _api_positive_int_arg("per_page", 20, max_value=100)
        if error:
            return error

        def compute():
            # Same counting rule as /top-actors; one query returns the page
            # and the total (window count), and the result is cached
            movie_count = func.count(func.distinct(Cast.movie_id)).label("movie_count")
            actors_query = (
                session.query(
                    Person.id,
                    Person.name,
                    Person.profile_path,
                    movie_count,
                    func.count().over().label("total"),
                )
                .join(Cast, Person.id == Cast.person_id)
                .join(Movie, Cast.movie_id == Movie.id)
                .filter(Movie.vote_count > 20)
                .group_by(Person.id, Person.name, Person.profile_path)
                .having(func.count(func.distinct(Cast.movie_id)) >= 2)
                .order_by(desc("movie_count"), Person.id)
            )
            rows = actors_query.limit(per_page).offset((page - 1) * per_page).all()
            total = rows[0].total if rows else actors_query.order_by(None).count()
            return total, [
                {
                    "id": r.id,
                    "name": r.name,
                    "profile_path": r.profile_path,
                    "movie_count": r.movie_count,
                }
                for r in rows
            ]

        total, actors_data = _cached(f"api_actors:{page}:{per_page}", compute)

        return jsonify(
            {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": (total + per_page - 1) // per_page,
                "actors": actors_data,
            }
        )
    finally:
        session.close()


ACTOR_FILMOGRAPHY_LIMIT = 200


@app.route("/api/v1/actors/<int:actor_id>", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def api_get_actor(actor_id):
    """Get detailed information about an actor"""
    session = get_db_session()
    try:
        actor = session.query(Person).filter_by(id=actor_id).first()

        if not actor:
            return jsonify({"error": "Actor not found"}), 404

        # Filmography, one entry per movie (multiple roles joined), newest first
        filmography = []
        by_movie = {}
        for movie, cast in (
            session.query(Movie, Cast)
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id)
            .order_by(desc(Movie.release_date).nulls_last(), Movie.id, Cast.cast_order)
            .all()
        ):
            if movie.id in by_movie:
                entry = by_movie[movie.id]
                entry["character"] = f"{entry['character'] or 'Unknown'} / {cast.character_name}"
                continue
            entry = {
                "movie_id": movie.id,
                "title": movie.title,
                "character": cast.character_name,
                "release_date": movie.release_date.isoformat() if movie.release_date else None,
                "vote_average": _num(movie.vote_average),
            }
            by_movie[movie.id] = entry
            filmography.append(entry)

        # Calculate stats
        total_movies = len(filmography)
        avg_rating = (
            session.query(func.avg(Movie.vote_average))
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id, Movie.vote_count > 20)
            .scalar()
        )

        actor_data = {
            "id": actor.id,
            "name": actor.name,
            "profile_path": actor.profile_path,
            "total_movies": total_movies,
            "average_rating": _num(avg_rating),
            # Capped so a prolific actor can't produce a huge response
            "filmography": filmography[:ACTOR_FILMOGRAPHY_LIMIT],
            "filmography_truncated": total_movies > ACTOR_FILMOGRAPHY_LIMIT,
        }

        return jsonify(actor_data)
    finally:
        session.close()


@app.route("/api/v1/health", methods=["GET"])
@limiter.exempt
def api_health():
    """Health check endpoint"""
    session = get_db_session()
    try:
        # Test database connection
        movie_count = session.query(func.count(Movie.id)).scalar()

        return jsonify({"status": "healthy", "database": "connected", "movie_count": movie_count})
    except Exception as e:
        logger.error(f"Health check database failure: {e}", exc_info=True)
        return jsonify({"status": "unhealthy", "error": "database unavailable"}), 500
    finally:
        session.close()


@app.route("/api/v1/docs", methods=["GET"])
def api_docs():
    """API documentation"""
    docs = {
        "version": "1.0",
        "notes": {
            "numbers": "Decimal values are JSON numbers; a value of 0 is 0, missing is null.",
            "rate_limits": "Per IP. Exceeding a limit returns HTTP 429 with a JSON error.",
        },
        "endpoints": {
            "movies": {
                "GET /api/v1/movies": {
                    "description": "Get list of movies with filtering and pagination",
                    "parameters": {
                        "page": "Page number (default: 1, max: 10000)",
                        "per_page": "Results per page (default: 20, max: 100)",
                        "genre": "Filter by genre ID",
                        "sort": "popularity (default), rating (50+ votes), release_date, "
                        "upcoming (from today, soonest first), title. Unknown values use popularity.",
                        "year": "Filter by release year",
                        "decade": "Filter by decade start, e.g. 1990 (takes precedence over year)",
                        "min_rating": "Minimum TMDB rating",
                        "max_rating": "Maximum TMDB rating",
                        "runtime_min": "Minimum runtime in minutes",
                        "runtime_max": "Maximum runtime in minutes",
                        "min_vote_count": "Minimum TMDB vote count",
                        "status": "TMDB status, e.g. Released",
                        "exclude_mature": "1 to leave out movies flagged mature",
                    },
                },
                "GET /api/v1/movies/<id>": {
                    "description": "Get detailed information about a specific movie"
                },
                "GET /api/v1/movies/search": {
                    "description": "Search movie titles and overviews (title matches first)",
                    "parameters": {
                        "q": "Search text (required; % and _ match literally)",
                        "page": "Page number",
                        "per_page": "Results per page (default: 20, max: 100)",
                    },
                },
            },
            "genres": {"GET /api/v1/genres": {"description": "Get all genres"}},
            "analytics": {
                "GET /api/v1/analytics/overview": {"description": "Get overview analytics"},
                "GET /api/v1/analytics/genres": {"description": "Get genre analytics"},
                "GET /api/v1/analytics/top-movies": {
                    "description": "Get top movies by metric",
                    "parameters": {
                        "metric": "rating, revenue, or popularity",
                        "limit": "Number of results (default: 10, max: 100)",
                    },
                },
            },
            "actors": {
                "GET /api/v1/actors": {
                    "description": "Actors in 2+ movies (20+ votes each), most movies first",
                    "parameters": {
                        "page": "Page number (default: 1)",
                        "per_page": "Results per page (default: 20, max: 100)",
                    },
                },
                "GET /api/v1/actors/search": {
                    "description": "Search actors by name (used by Common Films)",
                    "parameters": {
                        "q": "Name text, at least 2 characters (required)",
                        "per_page": "Results (default: 8, max: 20)",
                        "with": "Repeatable actor ID: only return actors who share a movie "
                        "with every listed actor",
                    },
                },
                "GET /api/v1/actors/<id>": {
                    "description": "Actor details and filmography (up to 200 movies)"
                },
            },
            "collections": {
                "GET /api/v1/collections": {
                    "description": "The logged-in user's collections (session cookie "
                    "required; 401 JSON otherwise)"
                }
            },
            "system": {
                "GET /api/v1/health": {"description": "Health check endpoint"},
                "GET /api/v1/docs": {"description": "API documentation"},
            },
        },
    }

    return jsonify(docs)


# ==========================================
# DECADE OVERVIEW ROUTES
# ==========================================

# Decade flavor text for the index cards
_DECADE_DESCRIPTIONS = {
    1920: "The silent era gives way to sound. Hollywood establishes its golden foundation.",
    1930: "Depression-era escapism drives the studio system to its peak creative output.",
    1940: "War shapes storytelling. Film noir emerges from the shadows.",
    1950: "Widescreen spectacle, sci-fi anxieties, and the birth of teen culture.",
    1960: "The old studio system collapses. Counterculture rewrites cinema's rules.",
    1970: "The Movie Brats arrive. Auteur filmmaking at its most daring and raw.",
    1980: "Blockbuster culture takes hold. Practical effects reach their pinnacle.",
    1990: "Independent cinema explodes. Genre boundaries blur and shatter.",
    2000: "Digital filmmaking democratizes the art. Franchise era begins.",
    2010: "Streaming disrupts everything. Prestige TV and cinema converge.",
    2020: "A pandemic reshapes release windows. Streaming becomes the new normal.",
}


# A movie counts on decade pages once it has at least one vote (TMDB stores
# 0.0 for unrated movies, which would drag averages down)
DECADE_MIN_VOTES = 1


def _decade_movie_filters(decade_start):
    return (
        _year_range_filter(Movie.release_date, decade_start, decade_start + 9),
        Movie.vote_count >= DECADE_MIN_VOTES,
    )


def _decades_index(session_db):
    """Per-decade totals and a backdrop for each card, as plain data."""
    # Get per-year stats then bucket into decades in Python
    # (SQLite integer division inside func.cast is unreliable for grouping)
    year_raw = (
        session_db.query(
            extract("year", Movie.release_date).label("year"),
            func.count(Movie.id).label("movie_count"),
            func.avg(Movie.vote_average).label("avg_rating"),
            func.sum(Movie.revenue).label("total_revenue"),
        )
        .filter(Movie.release_date.isnot(None))
        .filter(Movie.vote_count >= DECADE_MIN_VOTES)
        .group_by("year")
        .all()
    )

    decade_buckets = {}
    for row in year_raw:
        if not row.year:
            continue
        ds = (int(row.year) // 10) * 10
        bucket = decade_buckets.setdefault(
            ds, {"movie_count": 0, "ratings": [], "total_revenue": 0}
        )
        bucket["movie_count"] += row.movie_count
        if row.avg_rating is not None:
            bucket["ratings"].append((float(row.avg_rating), row.movie_count))
        bucket["total_revenue"] += int(row.total_revenue or 0)

    decades_list = []
    for decade_start in sorted(decade_buckets.keys()):
        bucket = decade_buckets[decade_start]
        total_weighted = sum(r * c for r, c in bucket["ratings"])
        total_count = sum(c for _, c in bucket["ratings"])
        avg_rating = total_weighted / total_count if total_count else 0

        # Most popular movie with a backdrop for the card image
        hero_backdrop = (
            _content_filtered(session_db.query(Movie.backdrop_path))
            .filter(
                _year_range_filter(Movie.release_date, decade_start, decade_start + 9),
                Movie.backdrop_path.isnot(None),
                Movie.vote_count > 50,
                *_featured_filters(),
            )
            .order_by(desc(Movie.popularity), Movie.id)
            .limit(1)
            .scalar()
        )

        decades_list.append(
            {
                "decade_start": decade_start,
                "decade_end": decade_start + 9,
                "label": f"{decade_start}s",
                "movie_count": bucket["movie_count"],
                "avg_rating": round(avg_rating, 1),
                "total_revenue": bucket["total_revenue"],
                "description": _DECADE_DESCRIPTIONS.get(decade_start, ""),
                "hero_backdrop": hero_backdrop,
            }
        )
    return decades_list


@app.route("/decades")
def decades():
    """Decade overview index page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)

        decades_list = _cached("decades:index", lambda: _decades_index(session_db))

        return render_template(
            "decades.html",
            decades=decades_list,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/decade/<int:decade_start>")
def decade_detail(decade_start):
    """Individual decade detail page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        decade_end = decade_start + 9

        # Validate decade: a decade starts on a year ending in 0
        if decade_start % 10 or decade_start < 1900 or decade_start > utcnow().year:
            abort(404)

        decade_filters = _decade_movie_filters(decade_start)
        base_query = _content_filtered(session_db.query(Movie)).filter(*decade_filters)

        total_movies = base_query.order_by(None).count()
        if total_movies == 0:
            abort(404)

        # Top rated (min 20 votes for reliability)
        top_rated = (
            base_query.filter(Movie.vote_count >= 20)
            .order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
            .limit(12)
            .all()
        )

        # Most popular
        most_popular = base_query.order_by(desc(Movie.popularity), Movie.id).limit(12).all()

        # Defining films: high rating AND high popularity — the cultural touchstones
        defining_films = (
            base_query.filter(Movie.vote_count >= 50)
            .order_by(desc(Movie.popularity * Movie.vote_average), Movie.id)
            .limit(6)
            .all()
        )

        # Genre breakdown, counted over the same movies as total_movies, with
        # ids so the badges can link to /movies?genre=<id>
        genre_stats = (
            session_db.query(Genre.id, Genre.name, func.count(Movie.id).label("count"))
            .join(Movie.genres)
            .filter(*decade_filters)
            .group_by(Genre.id, Genre.name)
            .order_by(desc("count"), Genre.name)
            .all()
        )

        # Stats
        avg_rating = (
            session_db.query(func.avg(Movie.vote_average))
            .filter(*decade_filters, Movie.vote_count >= 20)
            .scalar()
        )
        total_revenue = (
            session_db.query(func.sum(Movie.revenue))
            .filter(*decade_filters, Movie.revenue > 0)
            .scalar()
        )

        # Movies by year (for chart), over the same movies
        by_year = (
            session_db.query(
                extract("year", Movie.release_date).label("year"),
                func.count(Movie.id).label("count"),
                func.avg(Movie.vote_average).label("avg_rating"),
            )
            .filter(*decade_filters)
            .group_by("year")
            .order_by("year")
            .all()
        )

        stats = {
            "total_movies": total_movies,
            "avg_rating": round(float(avg_rating), 2) if avg_rating else 0,
            "total_revenue": int(total_revenue or 0),
            "top_genre": genre_stats[0].name if genre_stats else "N/A",
        }

        chart_data = {
            "years": [int(r.year) for r in by_year],
            "counts": [r.count for r in by_year],
            "ratings": [
                round(float(r.avg_rating), 2) if r.avg_rating is not None else None for r in by_year
            ],
        }

        return render_template(
            "decade_detail.html",
            decade_start=decade_start,
            decade_end=decade_end,
            label=f"{decade_start}s",
            description=_DECADE_DESCRIPTIONS.get(decade_start, ""),
            stats=stats,
            defining_films=defining_films,
            top_rated=top_rated,
            most_popular=most_popular,
            genre_stats=genre_stats,
            chart_data=chart_data,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


# ==========================================
# PRODUCTION COMPANIES ROUTES
# ==========================================


# Studios list and detail pages count movies with at least one vote, so the
# two agree; unrated movies (TMDB 0.0) would otherwise drag averages down
COMPANY_MIN_VOTES = 1

_COMPANY_SORTS = {
    "movies": (desc("movie_count"), ProductionCompany.id),
    "avg_rating": (desc("avg_rating"), desc("movie_count"), ProductionCompany.id),
    "total_revenue": (desc("total_revenue"), ProductionCompany.id),
    "name": (ProductionCompany.name, ProductionCompany.id),
}


@app.route("/companies")
def companies():
    """Production companies listing page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        page = _html_page_arg()
        per_page = 24

        search = request.args.get("q", "").strip()
        sort_by = request.args.get("sort", "movies")
        if sort_by not in _COMPANY_SORTS:
            sort_by = "movies"

        companies_query = (
            session_db.query(
                ProductionCompany.id,
                ProductionCompany.name,
                ProductionCompany.logo_path,
                ProductionCompany.origin_country,
                func.count(Movie.id).label("movie_count"),
                func.avg(Movie.vote_average).label("avg_rating"),
                func.sum(Movie.revenue).label("total_revenue"),
            )
            .join(ProductionCompany.movies)
            .filter(Movie.vote_count >= COMPANY_MIN_VOTES)
        )
        if search:
            companies_query = companies_query.filter(
                ProductionCompany.name.ilike(_contains_pattern(search), escape="\\")
            )
        companies_query = (
            companies_query.group_by(
                ProductionCompany.id,
                ProductionCompany.name,
                ProductionCompany.logo_path,
                ProductionCompany.origin_country,
            )
            .having(func.count(Movie.id) >= 3)
            .order_by(*_COMPANY_SORTS[sort_by])
        )

        total = companies_query.order_by(None).count()
        total_pages = (total + per_page - 1) // per_page if total else 1
        page = max(1, min(page, total_pages))
        companies_data = companies_query.limit(per_page).offset((page - 1) * per_page).all()

        # Top 3 rated movies for every studio on the page, in one query
        company_ids = [row.id for row in companies_data]
        top_by_company = {company_id: [] for company_id in company_ids}
        if company_ids:
            rank = (
                func.row_number()
                .over(
                    partition_by=movie_companies_table.c.company_id,
                    order_by=(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id),
                )
                .label("rank")
            )
            ranked = (
                select(
                    movie_companies_table.c.company_id,
                    Movie.id,
                    Movie.title,
                    Movie.release_date,
                    Movie.vote_average,
                    rank,
                )
                .join(Movie, movie_companies_table.c.movie_id == Movie.id)
                .where(
                    movie_companies_table.c.company_id.in_(company_ids),
                    Movie.vote_count >= COMPANY_MIN_VOTES,
                )
                .subquery()
            )
            for row in session_db.execute(
                select(ranked)
                .where(ranked.c.rank <= 3)
                .order_by(ranked.c.company_id, ranked.c.rank)
            ):
                top_by_company[row.company_id].append(
                    {
                        "id": row.id,
                        "title": row.title,
                        "year": row.release_date.year if row.release_date else None,
                        "vote_average": _num(row.vote_average) or 0,
                    }
                )

        companies_list = [
            {
                "id": row.id,
                "name": row.name,
                "logo_path": row.logo_path,
                "origin_country": row.origin_country,
                "movie_count": row.movie_count,
                "avg_rating": _num(row.avg_rating) or 0,
                "total_revenue": int(row.total_revenue or 0),
                "top_movies": top_by_company[row.id],
            }
            for row in companies_data
        ]

        return render_template(
            "companies.html",
            companies=companies_list,
            page=page,
            total_pages=total_pages,
            total=total,
            search=search,
            sort_by=sort_by,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


COMPANY_MOVIES_PER_PAGE = 48


@app.route("/company/<int:company_id>")
def company_detail(company_id):
    """Individual production company detail page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)

        company = session_db.query(ProductionCompany).filter_by(id=company_id).first()
        if not company:
            abort(404)

        company_movies = (
            session_db.query(Movie)
            .join(Movie.companies)
            .filter(ProductionCompany.id == company_id)
            .filter(Movie.vote_count >= COMPANY_MIN_VOTES)
        )

        # Totals in SQL, so a studio with thousands of movies stays one query
        (
            total_movies,
            avg_rating,
            total_revenue,
            first_date,
            last_date,
        ) = company_movies.with_entities(
            func.count(Movie.id),
            func.avg(Movie.vote_average),
            func.sum(Movie.revenue),
            func.min(Movie.release_date),
            func.max(Movie.release_date),
        ).one()
        first_year = first_date.year if first_date else None
        last_year = last_date.year if last_date else None
        years_active = (last_year - first_year + 1) if first_year and last_year else 0

        movie_ids = company_movies.with_entities(Movie.id).subquery()
        genres = [
            {"name": name, "count": count}
            for name, count in session_db.query(Genre.name, func.count().label("count"))
            .join(movie_genres_table, Genre.id == movie_genres_table.c.genre_id)
            .filter(movie_genres_table.c.movie_id.in_(select(movie_ids.c.id)))
            .group_by(Genre.name)
            .order_by(desc("count"), Genre.name)
            .all()
        ]

        by_year = (
            company_movies.with_entities(
                extract("year", Movie.release_date).label("year"),
                func.avg(Movie.vote_average).label("avg_rating"),
                func.sum(Movie.revenue).label("revenue"),
            )
            .filter(Movie.release_date.isnot(None))
            .group_by("year")
            .order_by("year")
            .all()
        )
        chart_data = {
            "years": [int(r.year) for r in by_year],
            "ratings": [
                round(float(r.avg_rating), 2) if r.avg_rating is not None else None for r in by_year
            ],
            "revenues": [round(float(r.revenue or 0) / 1_000_000, 1) for r in by_year],
        }

        stats = {
            "total_movies": total_movies,
            "avg_rating": _num(avg_rating),
            "total_revenue": int(total_revenue or 0),
            "years_active": years_active,
            "first_year": first_year,
            "last_year": last_year,
            "genres": genres,
        }

        # The movie list is paginated, newest first (undated last)
        page = _html_page_arg()
        per_page = COMPANY_MOVIES_PER_PAGE
        total_pages = (total_movies + per_page - 1) // per_page if total_movies else 1
        page = max(1, min(page, total_pages))
        movies = (
            company_movies.options(selectinload(Movie.genres))
            .order_by(desc(Movie.release_date).nulls_last(), Movie.id)
            .limit(per_page)
            .offset((page - 1) * per_page)
            .all()
        )
        movies_list = [
            {
                "id": m.id,
                "title": m.title,
                "year": m.release_date.year if m.release_date else None,
                "poster_path": m.poster_path,
                "vote_average": _num(m.vote_average) or 0,
                "revenue": m.revenue,
                "runtime": m.runtime,
                "genres": [g.name for g in m.genres],
            }
            for m in movies
        ]

        return render_template(
            "company_detail.html",
            company=company,
            movies=movies_list,
            stats=stats,
            chart_data=chart_data,
            page=page,
            total_pages=total_pages,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


# ==========================================
# COLLECTIONS ROUTES
# ==========================================


@app.route("/collections")
def collections():
    """User's collections listing page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your collections", "warning")
            return redirect(url_for("login", next=_current_relative_url()))

        user_collections = (
            session_db.query(Collection)
            .filter_by(user_id=user.id)
            .order_by(desc(Collection.updated_at), Collection.id)
            .all()
        )

        # Counts and the first four posters, without loading every movie
        collection_ids = [c.id for c in user_collections]
        counts = dict(
            session_db.query(
                collection_movies_table.c.collection_id,
                func.count(collection_movies_table.c.movie_id),
            )
            .filter(collection_movies_table.c.collection_id.in_(collection_ids))
            .group_by(collection_movies_table.c.collection_id)
            .all()
        )
        previews = {
            c.id: _collection_movies_page(session_db, c.id, 0, 4)
            for c in user_collections
            if counts.get(c.id)
        }

        return render_template(
            "collections.html",
            collections=user_collections,
            counts=counts,
            previews=previews,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/collections/create", methods=["POST"])
def create_collection():
    """Create a new collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to manage collections", "warning")
            return redirect(url_for("login", next=url_for("collections")))

        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("Collection name is required", "danger")
            return redirect(url_for("collections"))

        if len(name) > 255:
            flash("Collection name must be 255 characters or fewer", "danger")
            return redirect(url_for("collections"))

        if len(description) > MAX_COLLECTION_DESCRIPTION_LENGTH:
            flash(
                f"Description must be {MAX_COLLECTION_DESCRIPTION_LENGTH} characters or fewer",
                "danger",
            )
            return redirect(url_for("collections"))

        collection = Collection(
            user_id=user.id,
            name=name,
            description=description or None,
        )
        session_db.add(collection)
        session_db.commit()

        flash(f'Collection "{name}" created', "success")
        return redirect(url_for("collection_detail", collection_id=collection.id))
    finally:
        session_db.close()


@app.route("/collection/<int:collection_id>")
def collection_detail(collection_id):
    """Individual collection detail page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view collections", "warning")
            return redirect(url_for("login", next=_current_relative_url()))

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            flash("Collection not found", "danger")
            return redirect(url_for("collections"))

        # Paginate the movies in this collection
        page = _html_page_arg()
        per_page = 24
        total = _association_count(session_db, collection_movies_table, collection_id=collection.id)
        total_pages = (total + per_page - 1) // per_page if total else 1
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page
        paged_movies = _collection_movies_page(session_db, collection.id, offset, per_page)

        return render_template(
            "collection_detail.html",
            collection=collection,
            movies=paged_movies,
            total=total,
            page=page,
            total_pages=total_pages,
            per_page=per_page,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/collection/<int:collection_id>/delete", methods=["POST"])
def delete_collection(collection_id):
    """Delete a collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to manage collections", "warning")
            return redirect(url_for("login", next=url_for("collections")))

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            flash("Collection not found", "danger")
            return redirect(url_for("collections")), 404

        name = collection.name
        session_db.delete(collection)
        session_db.commit()

        flash(f'Collection "{name}" deleted', "success")
        return redirect(url_for("collections"))
    finally:
        session_db.close()


@app.route("/collection/<int:collection_id>/add/<int:movie_id>", methods=["POST"])
def add_to_collection(collection_id, movie_id):
    """Add a movie to a collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            return jsonify({"error": "Collection not found"}), 404

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        status = "already_added"
        if not _association_exists(
            session_db, collection_movies_table, collection_id=collection.id, movie_id=movie.id
        ):
            collection.updated_at = utcnow()
            if _insert_association(
                session_db, collection_movies_table, collection_id=collection.id, movie_id=movie.id
            ):
                status = "added"

        count = _association_count(session_db, collection_movies_table, collection_id=collection.id)
        return jsonify({"status": status, "count": count})
    finally:
        session_db.close()


@app.route("/collection/<int:collection_id>/remove/<int:movie_id>", methods=["POST"])
def remove_from_collection(collection_id, movie_id):
    """Remove a movie from a collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            return jsonify({"error": "Collection not found"}), 404

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        if _association_exists(
            session_db, collection_movies_table, collection_id=collection.id, movie_id=movie.id
        ):
            session_db.execute(
                collection_movies_table.delete().where(
                    collection_movies_table.c.collection_id == collection.id,
                    collection_movies_table.c.movie_id == movie.id,
                )
            )
            collection.updated_at = utcnow()
            count = _association_count(
                session_db, collection_movies_table, collection_id=collection.id
            )
            session_db.commit()
            return jsonify({"status": "removed", "count": count})

        count = _association_count(session_db, collection_movies_table, collection_id=collection.id)
        return jsonify({"status": "not_found", "count": count}), 404
    finally:
        session_db.close()


@app.route("/api/v1/collections", methods=["GET"])
@limiter.limit("100 per hour")
def api_get_collections():
    """Get current user's collections"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        user_collections = (
            session_db.query(
                Collection.id,
                Collection.name,
                Collection.description,
                Collection.updated_at,
                func.count(collection_movies_table.c.movie_id).label("movie_count"),
            )
            .outerjoin(
                collection_movies_table,
                Collection.id == collection_movies_table.c.collection_id,
            )
            .filter(Collection.user_id == user.id)
            .group_by(
                Collection.id,
                Collection.name,
                Collection.description,
                Collection.updated_at,
            )
            .order_by(desc(Collection.updated_at))
            .all()
        )

        return jsonify(
            {
                "collections": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "description": c.description,
                        "movie_count": c.movie_count,
                        "updated_at": (c.updated_at.isoformat() if c.updated_at else None),
                    }
                    for c in user_collections
                ]
            }
        )
    finally:
        session_db.close()


# ==========================================
# USER PROFILE ROUTE
# ==========================================


@app.route("/profile")
def profile():
    """User profile page showing stats, ratings, reviews, favorites and watchlist"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your profile", "warning")
            return redirect(url_for("login", next=_current_relative_url()))

        # Favorites and watchlist
        favorites = _user_list_movies(session_db, user_favorites_table, user.id)
        watchlist = _user_list_movies(session_db, user_watchlist_table, user.id)

        # Ratings with associated movie (moderated rows stay hidden)
        ratings = (
            session_db.query(Rating, Movie)
            .join(Movie, Rating.movie_id == Movie.id)
            .filter(Rating.user_id == user.id, Rating.is_deleted.is_(False))
            .order_by(desc(Rating.updated_at))
            .all()
        )

        # Reviews with associated movie (moderated rows stay hidden)
        reviews = (
            session_db.query(Review, Movie)
            .join(Movie, Review.movie_id == Movie.id)
            .filter(Review.user_id == user.id, Review.is_deleted.is_(False))
            .order_by(desc(Review.created_at))
            .all()
        )

        # Summary stats
        avg_user_rating = (
            session_db.query(func.avg(Rating.rating))
            .filter(Rating.user_id == user.id, Rating.is_deleted.is_(False))
            .scalar()
        )

        stats = {
            "favorites_count": len(favorites),
            "watchlist_count": len(watchlist),
            "ratings_count": len(ratings),
            "reviews_count": len(reviews),
            "avg_rating": round(float(avg_user_rating), 1) if avg_user_rating else None,
        }

        return render_template(
            "profile.html",
            current_user=user,
            favorites=favorites,
            watchlist=watchlist,
            ratings=ratings,
            reviews=reviews,
            stats=stats,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/compare")
def compare():
    """Movie comparison page"""
    session = get_db_session()
    try:
        user = get_current_user(session)
        # Unique ids, in the order given, capped at 4
        ids = list(dict.fromkeys(request.args.getlist("id", type=int)))[:4]

        movies_list = []
        if ids:
            movies_list = session.query(Movie).filter(Movie.id.in_(ids)).all()
            # Preserve request order
            id_order = {mid: i for i, mid in enumerate(ids)}
            movies_list = sorted(movies_list, key=lambda m: id_order.get(m.id, 999))

        # First-listed director for each movie, in one query
        directors = {movie.id: None for movie in movies_list}
        if movies_list:
            for movie_id, person in (
                session.query(Crew.movie_id, Person)
                .join(Person, Person.id == Crew.person_id)
                .filter(Crew.movie_id.in_(directors.keys()), Crew.job == "Director")
                .order_by(Crew.movie_id, Crew.id)
                .all()
            ):
                if directors[movie_id] is None:
                    directors[movie_id] = person

        return render_template(
            "compare.html",
            movies=movies_list,
            directors=directors,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


# ==========================================
# COMMON FILMS ROUTE
# ==========================================


@app.route("/common-films")
def common_films():
    """Find movies shared by a set of selected actors."""
    session = get_db_session()
    try:
        user = get_current_user(session)
        # Unique ids in selection order, capped at 5 to keep the query sane
        actor_ids = list(dict.fromkeys(request.args.getlist("actor", type=int)))[:5]

        actors = []
        movies = []

        if actor_ids:
            actors = session.query(Person).filter(Person.id.in_(actor_ids)).all()
            # Preserve selection order
            actor_map = {a.id: a for a in actors}
            actors = [actor_map[aid] for aid in actor_ids if aid in actor_map]

            if actors:
                # Movies where ALL selected actors appear, found in SQL
                shared_movie_ids = (
                    select(Cast.movie_id)
                    .where(Cast.person_id.in_([a.id for a in actors]))
                    .group_by(Cast.movie_id)
                    .having(func.count(func.distinct(Cast.person_id)) == len(actors))
                )
                movies = (
                    _content_filtered(session.query(Movie))
                    .filter(Movie.id.in_(shared_movie_ids))
                    .filter(Movie.vote_count > 0)
                    .order_by(desc(Movie.popularity), Movie.id)
                    .all()
                )

        return render_template(
            "common_films.html",
            actors=actors,
            movies=movies,
            actor_ids=actor_ids,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


# ==========================================
# ACTOR COLLABORATION NETWORK ROUTE
# ==========================================


NETWORK_MAX_COLLABORATORS = 30


@app.route("/actor/<int:actor_id>/network")
def actor_network(actor_id):
    """Collaboration network for a given actor.

    Nodes  = the focal actor + everyone who has shared at least one movie with them.
    Edges  = (actor_a, actor_b, shared_movie_count) for every collaborating pair,
             including edges between collaborators themselves (second-ring links).
    Capped at 30 collaborators so the graph stays readable.
    """
    session = get_db_session()
    try:
        user = get_current_user(session)

        actor = session.query(Person).filter_by(id=actor_id).first()
        if not actor:
            abort(404)

        # ── Step 1: movies the focal actor appeared in ──────────────────────
        focal_movie_ids = [
            row.movie_id
            for row in session.query(Cast.movie_id).filter(Cast.person_id == actor_id).all()
        ]

        if not focal_movie_ids:
            return render_template(
                "actor_network.html",
                actor=actor,
                graph_data={"nodes": [], "links": []},
                collaborator_count=0,
                current_user=user,
                config=Config,
            )

        # ── Step 2: direct collaborators (other actors in the same movies) ──
        collaborators_raw = (
            session.query(
                Person.id,
                Person.name,
                Person.profile_path,
                func.count(func.distinct(Cast.movie_id)).label("shared_movies"),
            )
            .join(Cast, Person.id == Cast.person_id)
            .filter(
                Cast.movie_id.in_(focal_movie_ids),
                Person.id != actor_id,
            )
            .group_by(Person.id, Person.name, Person.profile_path)
            .order_by(desc("shared_movies"), Person.id)
            .limit(NETWORK_MAX_COLLABORATORS)
            .all()
        )

        if not collaborators_raw:
            return render_template(
                "actor_network.html",
                actor=actor,
                graph_data={"nodes": [], "links": []},
                collaborator_count=0,
                current_user=user,
                config=Config,
            )

        collab_ids = [r.id for r in collaborators_raw]

        # ── Step 3: edges between collaborators (second-ring links) ─────────
        # Find movies shared between any two collaborators (excluding focal actor)
        c1 = aliased(Cast)
        c2 = aliased(Cast)
        collab_edges_raw = (
            session.query(
                c1.person_id.label("actor_a"),
                c2.person_id.label("actor_b"),
                func.count(func.distinct(c1.movie_id)).label("shared"),
            )
            .join(c2, c1.movie_id == c2.movie_id)
            .filter(
                c1.person_id.in_(collab_ids),
                c2.person_id.in_(collab_ids),
                c1.person_id < c2.person_id,  # avoid duplicates
            )
            .group_by(c1.person_id, c2.person_id)
            .all()
        )

        # ── Step 4: build D3-ready graph data ────────────────────────────────
        focal_movie_set = set(focal_movie_ids)

        # Per-person movie sets, built once and reused for every edge
        person_movie_sets = {}
        for row in (
            session.query(Cast.person_id, Cast.movie_id)
            .filter(Cast.person_id.in_(collab_ids + [actor_id]))
            .all()
        ):
            person_movie_sets.setdefault(row.person_id, set()).add(row.movie_id)

        # Titles are only needed for movies an edge actually shows
        edge_movie_ids = set()
        for r in collaborators_raw:
            edge_movie_ids |= focal_movie_set & person_movie_sets.get(r.id, set())
        for edge in collab_edges_raw:
            edge_movie_ids |= person_movie_sets.get(edge.actor_a, set()) & person_movie_sets.get(
                edge.actor_b, set()
            )
        movies_lookup = {
            m.id: m.title
            for m in session.query(Movie.id, Movie.title).filter(Movie.id.in_(edge_movie_ids)).all()
        }

        nodes = [
            {
                "id": actor.id,
                "name": actor.name,
                "profile_path": actor.profile_path,
                "shared_movies": 0,
                "focal": True,
            }
        ]
        for r in collaborators_raw:
            nodes.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "profile_path": r.profile_path,
                    "shared_movies": r.shared_movies,
                    "focal": False,
                }
            )

        # Focal-actor → collaborator edges with movie titles
        links = []
        for r in collaborators_raw:
            shared_ids = focal_movie_set & person_movie_sets.get(r.id, set())
            links.append(
                {
                    "source": actor.id,
                    "target": r.id,
                    "value": r.shared_movies,
                    "movies": sorted(
                        movies_lookup[mid] for mid in shared_ids if mid in movies_lookup
                    ),
                }
            )

        # Collaborator → collaborator edges with movie titles
        for edge in collab_edges_raw:
            shared_ids = person_movie_sets.get(edge.actor_a, set()) & person_movie_sets.get(
                edge.actor_b, set()
            )
            links.append(
                {
                    "source": edge.actor_a,
                    "target": edge.actor_b,
                    "value": edge.shared,
                    "movies": sorted(
                        movies_lookup[mid] for mid in shared_ids if mid in movies_lookup
                    ),
                }
            )

        graph_data = {"nodes": nodes, "links": links}

        return render_template(
            "actor_network.html",
            actor=actor,
            graph_data=graph_data,
            collaborator_count=len(collaborators_raw),
            # The graph shows at most NETWORK_MAX_COLLABORATORS; say so when capped
            collaborators_capped=len(collaborators_raw) >= NETWORK_MAX_COLLABORATORS,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


# ==========================================
# ADVANCED SEARCH ROUTE
# ==========================================


@app.route("/advanced-search")
def advanced_search():
    """Advanced multi-filter search — combines text query with genre, year,
    decade, rating range, and runtime range in a single unified UI."""
    session = get_db_session()
    try:
        user = get_current_user(session)

        # Pull every filter param
        q = request.args.get("q", "").strip()
        genre_id = request.args.get("genre", type=int)
        decade = request.args.get("decade", type=int)
        year = request.args.get("year", type=int)
        rating_min = request.args.get("rating_min", type=float)
        rating_max = request.args.get("rating_max", type=float)
        runtime_min = request.args.get("runtime_min", type=int)
        runtime_max = request.args.get("runtime_max", type=int)
        min_votes = request.args.get("min_votes", type=int)
        sort_by = request.args.get("sort", default="relevance")
        page = _html_page_arg()
        per_page = 24

        # Only run the query when at least one filter is present
        has_filters = any(
            [
                q,
                genre_id,
                decade,
                year,
                rating_min is not None,
                rating_max is not None,
                runtime_min is not None,
                runtime_max is not None,
                min_votes is not None,
            ]
        )

        movies_list = []
        total = 0
        total_pages = 0

        if has_filters:
            if q:
                # Text search across title and overview, title matches first
                query = _movie_search_query(session, q).order_by(None)
            else:
                query = session.query(Movie)
            query = _apply_movie_filters(
                _content_filtered(query),
                genre_id=genre_id,
                year=year,
                decade=decade,
                rating_min=rating_min,
                rating_max=rating_max,
                runtime_min=runtime_min,
                runtime_max=runtime_max,
                min_vote_count=min_votes,
            )

            # Sorting (Movie.id last keeps pages stable)
            if sort_by == "rating":
                # Same rule as /movies: a rating needs 50+ votes to rank
                query = query.filter(Movie.vote_count > 50).order_by(
                    desc(Movie.vote_average), desc(Movie.vote_count), Movie.id
                )
            elif sort_by == "release_date":
                query = query.filter(Movie.release_date.isnot(None)).order_by(
                    desc(Movie.release_date), Movie.id
                )
            elif sort_by == "title":
                query = query.order_by(Movie.title, Movie.id)
            elif sort_by == "runtime":
                query = query.filter(Movie.runtime.isnot(None)).order_by(Movie.runtime, Movie.id)
            elif q:
                # relevance: title matches first, then popularity
                pattern = _contains_pattern(q)
                query = query.order_by(
                    case((Movie.title.ilike(pattern, escape="\\"), 0), else_=1),
                    desc(Movie.popularity).nulls_last(),
                    Movie.id,
                )
            else:  # relevance without text: popularity
                query = query.order_by(desc(Movie.popularity).nulls_last(), Movie.id)

            total = query.order_by(None).count()
            total_pages = (total + per_page - 1) // per_page
            movies_list = query.limit(per_page).offset((page - 1) * per_page).all()

        # Sidebar data
        all_genres = _genre_options(session)
        available_decades = _decade_options()

        return render_template(
            "advanced_search.html",
            movies=movies_list,
            total=total,
            total_pages=total_pages,
            page=page,
            per_page=per_page,
            has_filters=has_filters,
            genres=all_genres,
            available_decades=available_decades,
            # echo back every param so the form re-populates
            q=q,
            selected_genre=genre_id,
            selected_decade=decade,
            selected_year=year,
            selected_rating_min=rating_min,
            selected_rating_max=rating_max,
            selected_runtime_min=runtime_min,
            selected_runtime_max=runtime_max,
            selected_min_votes=min_votes,
            selected_sort=sort_by,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


# ==========================================
# FAMILY-FRIENDLY TOGGLE
# ==========================================


@app.context_processor
def _inject_display_preferences():
    return {"family_friendly": family_friendly_enabled()}


@app.route("/preferences/family-friendly", methods=["POST"])
def set_family_friendly():
    """Turn family-friendly mode on or off for this browser (session cookie)."""
    requested = request.form.get("enabled", "").strip().lower()
    if requested in ("true", "false"):
        flask_session["family_friendly"] = requested == "true"
        if requested == "true":
            flash("Family-friendly mode is on: movies flagged mature are hidden.", "info")
        else:
            flash("Family-friendly mode is off.", "info")
    return redirect(_safe_next_url() or url_for("index"))


# ==========================================
# ACTIVITY FEED
# ==========================================

ACTIVITY_PER_PAGE = 30
ACTIVITY_REVIEW_PREVIEW_CHARS = 200


def _activity_page(session_db, page, per_page):
    """Recent public ratings and reviews, newest first, as (total, items).

    Leaves out moderated content, banned users, users who opted out, and
    movies flagged mature when the family-friendly toggle is on.
    """
    shared_filters = [User.is_banned.is_(False), User.hide_activity.is_(False)]
    if family_friendly_enabled():
        shared_filters.append(Movie.is_mature.is_(False))

    ratings = (
        select(
            literal("rating").label("kind"),
            Rating.id.label("item_id"),
            Rating.created_at.label("at"),
        )
        .join(User, Rating.user_id == User.id)
        .join(Movie, Rating.movie_id == Movie.id)
        .where(Rating.is_deleted.is_(False), *shared_filters)
    )
    reviews = (
        select(
            literal("review").label("kind"),
            Review.id.label("item_id"),
            Review.created_at.label("at"),
        )
        .join(User, Review.user_id == User.id)
        .join(Movie, Review.movie_id == Movie.id)
        .where(Review.is_deleted.is_(False), *shared_filters)
    )
    feed = union_all(ratings, reviews).subquery()

    total = session_db.execute(select(func.count()).select_from(feed)).scalar() or 0
    rows = session_db.execute(
        select(feed.c.kind, feed.c.item_id, feed.c.at)
        .order_by(desc(feed.c.at), feed.c.kind, desc(feed.c.item_id))
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()

    rating_ids = [r.item_id for r in rows if r.kind == "rating"]
    review_ids = [r.item_id for r in rows if r.kind == "review"]
    loaded = {}
    if rating_ids:
        for rating, user, movie in (
            session_db.query(Rating, User, Movie)
            .join(User, Rating.user_id == User.id)
            .join(Movie, Rating.movie_id == Movie.id)
            .filter(Rating.id.in_(rating_ids))
        ):
            loaded[("rating", rating.id)] = {
                "kind": "rating",
                "username": user.username,
                "movie": movie,
                "stars": rating.rating,
                "at": rating.created_at,
            }
    if review_ids:
        for review, user, movie in (
            session_db.query(Review, User, Movie)
            .join(User, Review.user_id == User.id)
            .join(Movie, Review.movie_id == Movie.id)
            .filter(Review.id.in_(review_ids))
        ):
            loaded[("review", review.id)] = {
                "kind": "review",
                "username": user.username,
                "movie": movie,
                "text": review.content,
                "at": review.created_at,
            }

    items = [loaded[(r.kind, r.item_id)] for r in rows if (r.kind, r.item_id) in loaded]
    return total, items


@app.route("/activity")
def activity_feed():
    """Public feed of recent ratings and reviews across all users"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        page = _html_page_arg()
        total, items = _activity_page(session_db, page, ACTIVITY_PER_PAGE)
        total_pages = (total + ACTIVITY_PER_PAGE - 1) // ACTIVITY_PER_PAGE if total else 1

        return render_template(
            "activity_feed.html",
            items=items,
            page=min(page, total_pages),
            total_pages=total_pages,
            total=total,
            preview_chars=ACTIVITY_REVIEW_PREVIEW_CHARS,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/profile/activity-visibility", methods=["POST"])
def set_activity_visibility():
    """Show or hide the logged-in user's ratings and reviews in the public feed"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to change this setting", "warning")
            return redirect(url_for("login", next=url_for("profile")))

        requested = request.form.get("hidden", "").strip().lower()
        if requested in ("true", "false"):
            user.hide_activity = requested == "true"
            session_db.commit()
            if user.hide_activity:
                flash("Your ratings and reviews are now hidden from the activity feed.", "success")
            else:
                flash("Your ratings and reviews now appear in the activity feed.", "success")
        return redirect(url_for("profile"))
    finally:
        session_db.close()


# ==========================================
# BLIND PICK
# ==========================================


@app.route("/watchlist/blind-pick")
def blind_pick():
    """Jump to a random movie from the user's watchlist"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to use Blind Pick", "warning")
            return redirect(url_for("login", next=url_for("watchlist")))

        movie_id = (
            session_db.query(user_watchlist_table.c.movie_id)
            .filter(user_watchlist_table.c.user_id == user.id)
            .order_by(func.random())
            .limit(1)
            .scalar()
        )
        if movie_id is None:
            flash("Your watchlist is empty. Add a few movies first, then try Blind Pick.", "info")
            return redirect(url_for("watchlist"))

        flash("Blind pick from your watchlist. Enjoy the movie!", "success")
        return redirect(url_for("movie_detail", movie_id=movie_id))
    finally:
        session_db.close()


# ==========================================
# YEAR IN REVIEW
# ==========================================


def _year_bounds(year):
    return datetime(year, 1, 1), datetime(year + 1, 1, 1)


def _activity_years(session_db, user_id):
    """Years (newest first) in which the user rated, reviewed or saved anything."""
    years = set()
    for column, owner in (
        (Rating.created_at, Rating.user_id),
        (Review.created_at, Review.user_id),
        (user_favorites_table.c.added_at, user_favorites_table.c.user_id),
        (user_watchlist_table.c.added_at, user_watchlist_table.c.user_id),
    ):
        for (year,) in (
            session_db.query(extract("year", column))
            .filter(owner == user_id, column.isnot(None))
            .distinct()
            .all()
        ):
            if year:
                years.add(int(year))
    return sorted(years, reverse=True)


def _year_in_review_stats(session_db, user, year):
    start, end = _year_bounds(year)

    ratings = (
        session_db.query(Rating, Movie)
        .join(Movie, Rating.movie_id == Movie.id)
        .filter(
            Rating.user_id == user.id,
            Rating.is_deleted.is_(False),
            Rating.created_at >= start,
            Rating.created_at < end,
        )
        .options(selectinload(Movie.genres))
        .order_by(desc(Rating.rating), desc(Movie.vote_average), Movie.id)
        .all()
    )
    reviews_count = (
        session_db.query(func.count(Review.id))
        .filter(
            Review.user_id == user.id,
            Review.is_deleted.is_(False),
            Review.created_at >= start,
            Review.created_at < end,
        )
        .scalar()
        or 0
    )
    favorites = (
        session_db.query(Movie)
        .join(user_favorites_table, user_favorites_table.c.movie_id == Movie.id)
        .filter(
            user_favorites_table.c.user_id == user.id,
            user_favorites_table.c.added_at >= start,
            user_favorites_table.c.added_at < end,
        )
        .options(selectinload(Movie.genres))
        .all()
    )
    watchlist_added = (
        session_db.query(func.count())
        .select_from(user_watchlist_table)
        .filter(
            user_watchlist_table.c.user_id == user.id,
            user_watchlist_table.c.added_at >= start,
            user_watchlist_table.c.added_at < end,
        )
        .scalar()
        or 0
    )

    # Genres and decades across everything rated or favorited this year,
    # counting a movie once even if it was both
    unique_movies = {movie.id: movie for movie in [m for _, m in ratings] + favorites}
    genre_counts = {}
    decade_counts = {}
    for movie in unique_movies.values():
        for genre in movie.genres:
            genre_counts[genre.name] = genre_counts.get(genre.name, 0) + 1
        if movie.release_date:
            decade = (movie.release_date.year // 10) * 10
            decade_counts[decade] = decade_counts.get(decade, 0) + 1
    top_genres = sorted(genre_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    favorite_decade = (
        max(decade_counts.items(), key=lambda item: (item[1], item[0]))[0]
        if decade_counts
        else None
    )

    rating_values = [rating.rating for rating, _ in ratings]
    distribution = [rating_values.count(stars) for stars in range(1, 6)]
    months = [0] * 12
    for rating, _ in ratings:
        months[rating.created_at.month - 1] += 1

    return {
        "ratings_count": len(ratings),
        "reviews_count": reviews_count,
        "favorites_count": len(favorites),
        "watchlist_added": watchlist_added,
        "avg_given": round(sum(rating_values) / len(rating_values), 1) if rating_values else None,
        "rating_distribution": distribution,
        "monthly_ratings": months,
        "top_genres": top_genres,
        "favorite_decade": favorite_decade,
        "runtime_minutes": sum(movie.runtime or 0 for _, movie in ratings),
        "top_rated": [movie for rating, movie in ratings if rating.rating >= 4][:6],
        "has_activity": bool(ratings or reviews_count or favorites or watchlist_added),
    }


@app.route("/year-in-review")
def year_in_review():
    """Personal stats for one calendar year: ratings, reviews, favorites, genres"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to see your Year in Review", "warning")
            return redirect(url_for("login", next=_current_relative_url()))

        years = _activity_years(session_db, user.id)
        current_year = utcnow().year
        year = request.args.get("year", type=int) or (years[0] if years else current_year)
        if year < 1900 or year > current_year:
            abort(404)

        return render_template(
            "year_in_review.html",
            year=year,
            years=sorted(set(years) | {current_year}, reverse=True),
            stats=_year_in_review_stats(session_db, user, year),
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


# ==========================================
# ROBOTS.TXT AND FAVICON
# ==========================================


@app.route("/robots.txt")
@limiter.exempt
def robots_txt():
    lines = [
        "User-agent: *",
        "Disallow: /admin",
        "Disallow: /api/",
        "Disallow: /login",
        "Disallow: /register",
        "Disallow: /preferences/",
        "Disallow: /analytics/export/",
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@app.route("/favicon.ico")
@limiter.exempt
def favicon():
    return redirect(url_for("static", filename="images/jaime_builds_logo.png"), code=301)


# ==========================================
# ADMIN DASHBOARD ROUTES
# ==========================================

# Only these levels are surfaced in the dashboard log snippet
_LOG_SNIPPET_LEVELS = ("WARNING", "ERROR")


def _recent_log_entries(limit: int = 20, tail_bytes: int = 256_000):
    """Return the most recent WARNING/ERROR entries from the app log file.

    Only the tail of the file is read, so the dashboard stays fast no matter
    how large the log has grown.
    """
    log_path = get_log_file_path()

    try:
        with open(log_path, "rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            file_size = log_file.tell()
            log_file.seek(max(0, file_size - tail_bytes))
            raw_tail = log_file.read()
    except OSError as exc:
        logger.warning(f"Unable to read log file {log_path}: {exc}")
        return []

    lines = raw_tail.decode("utf-8", errors="replace").splitlines()
    if file_size > tail_bytes and lines:
        # The first line is probably cut in half by the tail seek
        lines = lines[1:]

    entries = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("level") not in _LOG_SNIPPET_LEVELS:
            continue
        entries.append(entry)
        if len(entries) >= limit:
            break

    return entries


def _last_twelve_months(today):
    """Return the (year, month) pairs for the last 12 months, oldest first."""
    year, month = today.year, today.month
    months = []
    for _ in range(12):
        months.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    months.reverse()
    return months


def _admin_page(query, page, per_page):
    """Paginate an admin listing query, returning (rows, page, total, pages)."""
    total = query.order_by(None).count()
    total_pages = (total + per_page - 1) // per_page if total else 1
    page = max(1, min(page, total_pages))
    rows = query.limit(per_page).offset((page - 1) * per_page).all()
    return rows, page, total, total_pages


def _admin_log_extra(admin_user, **fields):
    """Log fields identifying which admin performed an action."""
    return {
        "admin_id": admin_user.id if admin_user else None,
        "admin_username": admin_user.username if admin_user else None,
        "path": request.path,
        "ip": request.remote_addr,
        **fields,
    }


def _apply_moderation(model, item_id, action, list_endpoint, label):
    """Soft-delete, restore, or hard-delete a rating or review as an admin."""
    session_db = get_db_session()
    try:
        admin_user = get_current_user(session_db)
        item = session_db.query(model).filter_by(id=item_id).first()
        if not item:
            flash(f"{label} not found", "danger")
            return redirect(_safe_next_url() or url_for(list_endpoint))

        if action == "soft-delete":
            item.is_deleted = True
            item.deleted_at = utcnow()
            message = f"{label} hidden from public view."
        elif action == "restore":
            item.is_deleted = False
            item.deleted_at = None
            message = f"{label} restored."
        else:  # hard-delete
            session_db.delete(item)
            message = f"{label} permanently deleted."

        session_db.commit()
        logger.info(
            f"Admin moderation: {action} on {label.lower()} id={item_id}",
            extra=_admin_log_extra(admin_user, target_id=item_id),
        )
        flash(message, "success")
        return redirect(_safe_next_url() or url_for(list_endpoint))
    finally:
        session_db.close()


@app.route("/admin")
@admin_required
def admin_dashboard():
    """Admin home -- top-line site stats plus a recent warning/error log snippet"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        month_start = local_today().replace(day=1)

        stats = {
            "total_users": session_db.query(func.count(User.id)).scalar() or 0,
            "total_movies": session_db.query(func.count(Movie.id)).scalar() or 0,
            "total_ratings": session_db.query(func.count(Rating.id)).scalar() or 0,
            "total_reviews": session_db.query(func.count(Review.id)).scalar() or 0,
            "total_page_views": session_db.query(func.sum(PageView.count)).scalar() or 0,
            "page_views_this_month": session_db.query(func.sum(PageView.count))
            .filter(PageView.view_date >= month_start)
            .scalar()
            or 0,
            "banned_users": session_db.query(func.count(User.id))
            .filter(User.is_banned.is_(True))
            .scalar()
            or 0,
        }

        return render_template(
            "admin_dashboard.html",
            stats=stats,
            log_entries=_recent_log_entries(),
            registration_enabled=_registration_enabled(session_db),
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/admin/analytics")
@admin_required
def admin_analytics():
    """Site analytics -- daily page views and monthly account growth"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        today = local_today()

        # --- Page views per day, last 30 days ---
        window_start = today - timedelta(days=29)
        daily_totals = dict(
            session_db.query(PageView.view_date, func.sum(PageView.count))
            .filter(PageView.view_date >= window_start)
            .group_by(PageView.view_date)
            .all()
        )
        page_view_labels = []
        page_view_counts = []
        for offset in range(30):
            day = window_start + timedelta(days=offset)
            page_view_labels.append(day.isoformat())
            page_view_counts.append(int(daily_totals.get(day, 0) or 0))

        # --- New accounts per month, last 12 months ---
        months = _last_twelve_months(today)
        signups_start = datetime(months[0][0], months[0][1], 1)
        signup_totals = {
            (int(row.year), int(row.month)): int(row.signups)
            for row in session_db.query(
                extract("year", User.created_at).label("year"),
                extract("month", User.created_at).label("month"),
                func.count(User.id).label("signups"),
            )
            .filter(User.created_at >= signups_start)
            .group_by("year", "month")
            .all()
        }
        signup_labels = [f"{year:04d}-{month:02d}" for year, month in months]
        signup_counts = [signup_totals.get(key, 0) for key in months]

        return render_template(
            "admin_analytics.html",
            page_view_labels=page_view_labels,
            page_view_counts=page_view_counts,
            signup_labels=signup_labels,
            signup_counts=signup_counts,
            total_page_views=sum(page_view_counts),
            total_signups=sum(signup_counts),
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/admin/users")
@admin_required
def admin_users():
    """Paginated, searchable user list with ban controls"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        search = request.args.get("q", "").strip()
        page = _html_page_arg()
        per_page = 25

        ratings_count = (
            select(func.count(Rating.id))
            .where(Rating.user_id == User.id)
            .scalar_subquery()
            .label("ratings_count")
        )
        reviews_count = (
            select(func.count(Review.id))
            .where(Review.user_id == User.id)
            .scalar_subquery()
            .label("reviews_count")
        )
        favorites_count = (
            select(func.count())
            .select_from(user_favorites_table)
            .where(user_favorites_table.c.user_id == User.id)
            .scalar_subquery()
            .label("favorites_count")
        )

        query = session_db.query(User, ratings_count, reviews_count, favorites_count)
        if search:
            query = query.filter(User.username.ilike(_contains_pattern(search), escape="\\"))

        rows, page, total, total_pages = _admin_page(
            query.order_by(desc(User.created_at), User.id), page, per_page
        )

        return render_template(
            "admin_users.html",
            users=rows,
            search=search,
            page=page,
            total=total,
            total_pages=total_pages,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/admin/users/<int:user_id>/ban", methods=["POST"])
@admin_required
def admin_ban_user(user_id):
    """Ban a user, hiding their content and locking them out"""
    session_db = get_db_session()
    try:
        admin_user = get_current_user(session_db)
        target = session_db.query(User).filter_by(id=user_id).first()

        if not target:
            flash("User not found", "danger")
        elif admin_user and target.id == admin_user.id:
            # Guard against an admin locking themselves out of the dashboard
            flash("You cannot ban your own account.", "warning")
        elif target.is_banned:
            flash(f"{target.username} is already banned.", "info")
        else:
            target.is_banned = True
            target.banned_at = utcnow()
            # Ends every session the user has open
            target.session_version = (target.session_version or 0) + 1
            session_db.commit()
            logger.warning(
                f"User banned: {target.username}",
                extra=_admin_log_extra(admin_user, user_id=target.id, username=target.username),
            )
            flash(f"{target.username} has been banned.", "success")

        return redirect(_safe_next_url() or url_for("admin_users"))
    finally:
        session_db.close()


@app.route("/admin/users/<int:user_id>/unban", methods=["POST"])
@admin_required
def admin_unban_user(user_id):
    """Lift a ban, restoring the account and its content"""
    session_db = get_db_session()
    try:
        admin_user = get_current_user(session_db)
        target = session_db.query(User).filter_by(id=user_id).first()

        if not target:
            flash("User not found", "danger")
        elif not target.is_banned:
            flash(f"{target.username} is not banned.", "info")
        else:
            target.is_banned = False
            target.banned_at = None
            session_db.commit()
            logger.info(
                f"User unbanned: {target.username}",
                extra=_admin_log_extra(admin_user, user_id=target.id, username=target.username),
            )
            flash(f"{target.username} has been unbanned.", "success")

        return redirect(_safe_next_url() or url_for("admin_users"))
    finally:
        session_db.close()


@app.route("/admin/reviews")
@admin_required
def admin_reviews():
    """All reviews, including soft-deleted ones, with moderation controls"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        page = _html_page_arg()
        per_page = 25

        query = (
            session_db.query(Review, User, Movie)
            .join(User, Review.user_id == User.id)
            .join(Movie, Review.movie_id == Movie.id)
            .order_by(desc(Review.created_at), Review.id)
        )
        rows, page, total, total_pages = _admin_page(query, page, per_page)

        return render_template(
            "admin_reviews.html",
            reviews=rows,
            page=page,
            total=total,
            total_pages=total_pages,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/admin/reviews/<int:review_id>/soft-delete", methods=["POST"])
@admin_required
def admin_soft_delete_review(review_id):
    """Hide a review from public view without deleting it"""
    return _apply_moderation(Review, review_id, "soft-delete", "admin_reviews", "Review")


@app.route("/admin/reviews/<int:review_id>/restore", methods=["POST"])
@admin_required
def admin_restore_review(review_id):
    """Make a soft-deleted review public again"""
    return _apply_moderation(Review, review_id, "restore", "admin_reviews", "Review")


@app.route("/admin/reviews/<int:review_id>/hard-delete", methods=["POST"])
@admin_required
def admin_hard_delete_review(review_id):
    """Permanently remove a review row"""
    return _apply_moderation(Review, review_id, "hard-delete", "admin_reviews", "Review")


@app.route("/admin/ratings")
@admin_required
def admin_ratings():
    """All ratings, including soft-deleted ones, with moderation controls"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        page = _html_page_arg()
        per_page = 25

        query = (
            session_db.query(Rating, User, Movie)
            .join(User, Rating.user_id == User.id)
            .join(Movie, Rating.movie_id == Movie.id)
            .order_by(desc(Rating.created_at), Rating.id)
        )
        rows, page, total, total_pages = _admin_page(query, page, per_page)

        return render_template(
            "admin_ratings.html",
            ratings=rows,
            page=page,
            total=total,
            total_pages=total_pages,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/admin/ratings/<int:rating_id>/soft-delete", methods=["POST"])
@admin_required
def admin_soft_delete_rating(rating_id):
    """Hide a rating from public view and from rating averages"""
    return _apply_moderation(Rating, rating_id, "soft-delete", "admin_ratings", "Rating")


@app.route("/admin/ratings/<int:rating_id>/restore", methods=["POST"])
@admin_required
def admin_restore_rating(rating_id):
    """Make a soft-deleted rating count again"""
    return _apply_moderation(Rating, rating_id, "restore", "admin_ratings", "Rating")


@app.route("/admin/ratings/<int:rating_id>/hard-delete", methods=["POST"])
@admin_required
def admin_hard_delete_rating(rating_id):
    """Permanently remove a rating row"""
    return _apply_moderation(Rating, rating_id, "hard-delete", "admin_ratings", "Rating")


@app.route("/admin/settings/registration", methods=["POST"])
@admin_required
def admin_toggle_registration():
    """Turn new account registration on or off site-wide"""
    session_db = get_db_session()
    try:
        admin_user = get_current_user(session_db)
        requested = request.form.get("enabled", "").strip().lower()
        if requested not in ("true", "false"):
            flash("Invalid registration setting.", "danger")
            return redirect(_safe_next_url() or url_for("admin_dashboard"))

        enable = requested == "true"
        state = "enabled" if enable else "disabled"
        if _registration_enabled(session_db) == enable:
            flash(f"Registration is already {state}.", "info")
        else:
            _set_site_setting(session_db, "registration_enabled", requested)
            logger.info(f"Registration {state} by admin", extra=_admin_log_extra(admin_user))
            flash(f"Registration is now {state}.", "success")
        return redirect(_safe_next_url() or url_for("admin_dashboard"))
    finally:
        session_db.close()


@app.route("/admin/movies/<int:movie_id>/featured", methods=["POST"])
@admin_required
def admin_set_featured(movie_id):
    """Keep a movie off the home page and Movie of the Day, or allow it again"""
    session_db = get_db_session()
    try:
        admin_user = get_current_user(session_db)
        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if movie is None:
            abort(404)

        requested = request.form.get("hidden", "").strip().lower()
        if requested not in ("true", "false"):
            flash("Invalid featured setting.", "danger")
        else:
            movie.hide_from_featured = requested == "true"
            session_db.commit()
            state = "hidden from" if movie.hide_from_featured else "allowed on"
            logger.info(
                f"Movie {state} the home page: {movie.title}",
                extra=_admin_log_extra(admin_user, movie_id=movie.id),
            )
            flash(f"{movie.title} is now {state} the home page.", "success")
        return redirect(url_for("movie_detail", movie_id=movie_id))
    finally:
        session_db.close()


# ==========================================
# ADMIN COMMAND LINE
# ==========================================


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
