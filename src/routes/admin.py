"""Admin dashboard: analytics, users, moderation and site settings."""

import json
import os
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import desc, extract, func, select

from config.config import Config
from src.helpers import (
    _contains_pattern,
    _html_page_arg,
    _registration_enabled,
    _safe_next_url,
    _set_site_setting,
    admin_required,
    get_current_user,
    get_db_session,
)
from src.logger import get_log_file_path, get_logger
from src.models import (
    Movie,
    PageView,
    Rating,
    Review,
    User,
    local_today,
    user_favorites_table,
    utcnow,
)

logger = get_logger(__name__)

bp = Blueprint("admin", __name__)


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


@bp.route("/admin")
@admin_required
def dashboard():
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


@bp.route("/admin/analytics")
@admin_required
def analytics():
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


@bp.route("/admin/users")
@admin_required
def users():
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


@bp.route("/admin/users/<int:user_id>/ban", methods=["POST"])
@admin_required
def ban_user(user_id):
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

        return redirect(_safe_next_url() or url_for("admin.users"))
    finally:
        session_db.close()


@bp.route("/admin/users/<int:user_id>/unban", methods=["POST"])
@admin_required
def unban_user(user_id):
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

        return redirect(_safe_next_url() or url_for("admin.users"))
    finally:
        session_db.close()


@bp.route("/admin/reviews")
@admin_required
def reviews():
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


@bp.route("/admin/reviews/<int:review_id>/soft-delete", methods=["POST"])
@admin_required
def soft_delete_review(review_id):
    """Hide a review from public view without deleting it"""
    return _apply_moderation(Review, review_id, "soft-delete", "admin.reviews", "Review")


@bp.route("/admin/reviews/<int:review_id>/restore", methods=["POST"])
@admin_required
def restore_review(review_id):
    """Make a soft-deleted review public again"""
    return _apply_moderation(Review, review_id, "restore", "admin.reviews", "Review")


@bp.route("/admin/reviews/<int:review_id>/hard-delete", methods=["POST"])
@admin_required
def hard_delete_review(review_id):
    """Permanently remove a review row"""
    return _apply_moderation(Review, review_id, "hard-delete", "admin.reviews", "Review")


@bp.route("/admin/ratings")
@admin_required
def ratings():
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


@bp.route("/admin/ratings/<int:rating_id>/soft-delete", methods=["POST"])
@admin_required
def soft_delete_rating(rating_id):
    """Hide a rating from public view and from rating averages"""
    return _apply_moderation(Rating, rating_id, "soft-delete", "admin.ratings", "Rating")


@bp.route("/admin/ratings/<int:rating_id>/restore", methods=["POST"])
@admin_required
def restore_rating(rating_id):
    """Make a soft-deleted rating count again"""
    return _apply_moderation(Rating, rating_id, "restore", "admin.ratings", "Rating")


@bp.route("/admin/ratings/<int:rating_id>/hard-delete", methods=["POST"])
@admin_required
def hard_delete_rating(rating_id):
    """Permanently remove a rating row"""
    return _apply_moderation(Rating, rating_id, "hard-delete", "admin.ratings", "Rating")


@bp.route("/admin/settings/registration", methods=["POST"])
@admin_required
def toggle_registration():
    """Turn new account registration on or off site-wide"""
    session_db = get_db_session()
    try:
        admin_user = get_current_user(session_db)
        requested = request.form.get("enabled", "").strip().lower()
        if requested not in ("true", "false"):
            flash("Invalid registration setting.", "danger")
            return redirect(_safe_next_url() or url_for("admin.dashboard"))

        enable = requested == "true"
        state = "enabled" if enable else "disabled"
        if _registration_enabled(session_db) == enable:
            flash(f"Registration is already {state}.", "info")
        else:
            _set_site_setting(session_db, "registration_enabled", requested)
            logger.info(f"Registration {state} by admin", extra=_admin_log_extra(admin_user))
            flash(f"Registration is now {state}.", "success")
        return redirect(_safe_next_url() or url_for("admin.dashboard"))
    finally:
        session_db.close()


@bp.route("/admin/movies/<int:movie_id>/featured", methods=["POST"])
@admin_required
def set_featured(movie_id):
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
        return redirect(url_for("main.movie_detail", movie_id=movie_id))
    finally:
        session_db.close()
