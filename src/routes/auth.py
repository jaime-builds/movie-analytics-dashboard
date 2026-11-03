"""Registration, login and logout."""

import re

from flask import Blueprint, flash, redirect, render_template, request
from flask import session as flask_session
from flask import url_for
from sqlalchemy import exists, func
from sqlalchemy.exc import IntegrityError

from src.extensions import limiter
from src.helpers import (
    _registration_enabled,
    _safe_next_url,
    _start_user_session,
    get_current_user,
    get_db_session,
)
from src.logger import get_logger
from src.models import User

logger = get_logger(__name__)

bp = Blueprint("auth", __name__)


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")


def _username_taken(session_db, username):
    """Usernames are unique regardless of case, so "Admin" can't shadow "admin"."""
    return session_db.query(exists().where(func.lower(User.username) == username.lower())).scalar()


@bp.route("/register", methods=["GET", "POST"])
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
            return redirect(url_for("main.index"))

        return render_template("register.html", registration_enabled=True)
    finally:
        session_db.close()


def _login_username_key():
    return "login-user:" + request.form.get("username", "").strip().lower()


def _login_failed(response):
    # A successful login redirects; a failed one re-renders the form
    return response.status_code != 302


@bp.route("/login", methods=["GET", "POST"])
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
                return redirect(next_page if next_page else url_for("main.index"))

            logger.warning(
                f"Failed login attempt: {username}",
                extra={"username": username, "ip": request.remote_addr},
            )
            flash("Invalid username or password", "danger")
            return render_template("login.html", next_url=_safe_next_url(), username=username)

        return render_template("login.html", next_url=_safe_next_url())
    finally:
        session_db.close()


@bp.route("/logout", methods=["POST"])
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
    return redirect(url_for("main.index"))
