"""Request, query and listing helpers shared by the route modules."""

from datetime import date
from functools import wraps
from typing import Optional
from urllib.parse import unquote, urlsplit

from flask import (
    abort,
    current_app,
    flash,
    has_request_context,
    jsonify,
    redirect,
    request,
)
from flask import session as flask_session
from flask import url_for
from sqlalchemy import and_, case, desc, exists, func
from sqlalchemy.exc import IntegrityError

from src.extensions import cache
from src.logger import get_logger
from src.models import Genre, Movie, Rating, Session, SiteSetting, User, local_today

logger = get_logger(__name__)


def get_db_session():
    """A new database session.

    Tests point ``session_factory`` at a session bound to their own
    transaction, which every route and hook then shares.
    """
    return session_factory()


session_factory = Session


# Input limits shared by routes and templates
MAX_REVIEW_LENGTH = 5000

# Deepest page any paginated listing will serve; keeps OFFSET far from the
# bigint limit Postgres enforces (an out-of-range OFFSET is a 500, not a 404)
MAX_PAGE = 10_000

# Hidden Gems defaults, shared with Movie of the Day
GEM_MIN_RATING = 7.0
GEM_MAX_POPULARITY = 20.0
GEM_MIN_VOTES = 50


def _association_filters(table, **column_values):
    return [table.c[column] == value for column, value in column_values.items()]


def _association_exists(session_db, table, **column_values):
    return bool(
        session_db.query(exists().where(*_association_filters(table, **column_values))).scalar()
    )


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
                return redirect(url_for("auth.login", next=_current_relative_url()))
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


# Data that only changes at the weekly sync is cached for this long
AGGREGATE_CACHE_SECONDS = 3600


def _cached(key, compute, timeout=AGGREGATE_CACHE_SECONDS):
    """Return compute() through the app cache under `key`.

    compute must return plain, picklable data (no ORM objects). The suite runs
    with caching off and calls compute() directly with the request's session.
    """
    if current_app.config.get("TESTING"):
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
