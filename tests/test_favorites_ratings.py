"""
Tests for authentication, favorites, watchlist, ratings, and reviews.

Previously run as a separate unittest suite. Refactored to standard pytest
style using shared conftest fixtures so the full test suite runs in one pass
with a single isolated in-memory database.
"""

from datetime import datetime

import pytest

from src.models import Movie, Rating, Review, User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(db_session, username="testuser", password="password123"):
    """Create and persist a user, return the instance."""
    user = User(username=username)
    user.set_password(password)
    db_session.add(user)
    db_session.commit()
    return user


def _make_movie(db_session, tmdb_id=888800001, title="Test Movie"):
    """Create and persist a movie, return the instance."""
    movie = Movie(
        tmdb_id=tmdb_id,
        title=title,
        overview="A test movie.",
        release_date=datetime(2020, 1, 1).date(),
        vote_average=7.5,
        vote_count=100,
        popularity=50.0,
    )
    db_session.add(movie)
    db_session.commit()
    return movie


def _login(client, username="testuser", password="password123"):
    """Post login credentials and return the response."""
    return client.post("/login", data={"username": username, "password": password})


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestAuthentication:
    """User registration, login, logout, and session handling."""

    def test_register_success(self, client, db_session):
        response = client.post(
            "/register",
            data={
                "username": "newuser",
                "password": "password123",
                "password_confirm": "password123",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        user = db_session.query(User).filter_by(username="newuser").first()
        assert user is not None

    def test_register_duplicate_username(self, client, db_session):
        _make_user(db_session, username="testuser")
        response = client.post(
            "/register",
            data={
                "username": "testuser",
                "password": "password123",
                "password_confirm": "password123",
            },
        )
        assert response.status_code == 200
        assert b"Username already exists" in response.data

    def test_register_password_mismatch(self, client, db_session):
        response = client.post(
            "/register",
            data={
                "username": "newuser",
                "password": "password123",
                "password_confirm": "different",
            },
        )
        assert response.status_code == 200
        assert b"Passwords do not match" in response.data

    def test_register_short_username(self, client, db_session):
        response = client.post(
            "/register",
            data={"username": "ab", "password": "password123", "password_confirm": "password123"},
        )
        assert response.status_code == 200
        assert b"Username must be at least 3 characters" in response.data

    def test_register_short_password(self, client, db_session):
        response = client.post(
            "/register",
            data={"username": "newuser", "password": "12345", "password_confirm": "12345"},
        )
        assert response.status_code == 200
        assert b"Password must be at least 6 characters" in response.data

    def test_login_success(self, client, db_session):
        _make_user(db_session)
        response = client.post(
            "/login",
            data={"username": "testuser", "password": "password123"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert "user_id" in sess

    def test_login_wrong_password(self, client, db_session):
        _make_user(db_session)
        response = client.post("/login", data={"username": "testuser", "password": "wrongpassword"})
        assert response.status_code == 200
        assert b"Invalid username or password" in response.data

    def test_login_nonexistent_user(self, client, db_session):
        response = client.post(
            "/login", data={"username": "nonexistent", "password": "password123"}
        )
        assert response.status_code == 200
        assert b"Invalid username or password" in response.data

    def test_logout(self, client, db_session):
        _make_user(db_session)
        _login(client)
        response = client.get("/logout", follow_redirects=True)
        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_login_redirect_next(self, client, db_session):
        _make_user(db_session)
        response = client.post(
            "/login?next=/favorites",
            data={"username": "testuser", "password": "password123"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/favorites" in response.location


# ---------------------------------------------------------------------------
# Favorites
# ---------------------------------------------------------------------------


class TestFavorites:
    """Adding, removing, and viewing favorited movies."""

    def test_add_favorite_success(self, client, db_session):
        user = _make_user(db_session, username="fav_user")
        movie = _make_movie(db_session, tmdb_id=888810001)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        response = client.post(f"/movie/{movie.id}/favorite")
        assert response.status_code == 200
        assert response.get_json()["status"] in ("added", "already_added")

    def test_add_favorite_already_exists(self, client, db_session):
        user = _make_user(db_session, username="fav_user2")
        movie = _make_movie(db_session, tmdb_id=888810002)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        client.post(f"/movie/{movie.id}/favorite")
        response = client.post(f"/movie/{movie.id}/favorite")
        assert response.status_code == 200
        assert response.get_json()["status"] == "already_added"

    def test_add_favorite_unauthorized(self, client, db_session):
        movie = _make_movie(db_session, tmdb_id=888810003)
        response = client.post(f"/movie/{movie.id}/favorite")
        assert response.status_code == 401

    def test_add_favorite_nonexistent_movie(self, client, db_session):
        user = _make_user(db_session, username="fav_user4")
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        response = client.post("/movie/99999999/favorite")
        assert response.status_code == 404

    def test_remove_favorite_success(self, client, db_session):
        user = _make_user(db_session, username="fav_user5")
        movie = _make_movie(db_session, tmdb_id=888810005)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        client.post(f"/movie/{movie.id}/favorite")
        response = client.post(f"/movie/{movie.id}/unfavorite")
        assert response.status_code == 200
        assert response.get_json()["status"] == "removed"

    def test_remove_favorite_not_in_list(self, client, db_session):
        user = _make_user(db_session, username="fav_user6")
        movie = _make_movie(db_session, tmdb_id=888810006)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        response = client.post(f"/movie/{movie.id}/unfavorite")
        assert response.status_code == 200
        assert response.get_json()["status"] == "not_found"

    def test_view_favorites_page(self, client, db_session):
        user = _make_user(db_session, username="fav_user7")
        movie = _make_movie(db_session, tmdb_id=888810007)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        client.post(f"/movie/{movie.id}/favorite")
        response = client.get("/favorites")
        assert response.status_code == 200

    def test_view_favorites_unauthorized(self, client, db_session):
        response = client.get("/favorites", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


class TestWatchlist:
    """Adding, removing, and viewing watchlisted movies."""

    def test_add_watchlist_success(self, client, db_session):
        user = _make_user(db_session, username="watch_user1")
        movie = _make_movie(db_session, tmdb_id=888820001)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        response = client.post(f"/movie/{movie.id}/watchlist")
        assert response.status_code == 200
        assert response.get_json()["status"] in ("added", "already_added")

    def test_add_watchlist_already_exists(self, client, db_session):
        user = _make_user(db_session, username="watch_user2")
        movie = _make_movie(db_session, tmdb_id=888820002)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        client.post(f"/movie/{movie.id}/watchlist")
        response = client.post(f"/movie/{movie.id}/watchlist")
        assert response.status_code == 200
        assert response.get_json()["status"] == "already_added"

    def test_remove_watchlist_success(self, client, db_session):
        user = _make_user(db_session, username="watch_user3")
        movie = _make_movie(db_session, tmdb_id=888820003)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        client.post(f"/movie/{movie.id}/watchlist")
        response = client.post(f"/movie/{movie.id}/unwatchlist")
        assert response.status_code == 200
        assert response.get_json()["status"] == "removed"

    def test_view_watchlist_page(self, client, db_session):
        user = _make_user(db_session, username="watch_user4")
        movie = _make_movie(db_session, tmdb_id=888820004)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        client.post(f"/movie/{movie.id}/watchlist")
        response = client.get("/watchlist")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Ratings and Reviews
# ---------------------------------------------------------------------------


class TestRatingsAndReviews:
    """Submitting, updating, and validating ratings and reviews."""

    def test_submit_rating_success(self, client, db_session):
        user = _make_user(db_session, username="rate_user1")
        movie = _make_movie(db_session, tmdb_id=888830001)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        response = client.post(f"/movie/{movie.id}/rate", data={"rating": 4})
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["rating"] == 4

    def test_submit_rating_invalid_value(self, client, db_session):
        user = _make_user(db_session, username="rate_user2")
        movie = _make_movie(db_session, tmdb_id=888830002)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        response = client.post(f"/movie/{movie.id}/rate", data={"rating": 6})
        assert response.status_code == 400

    def test_update_rating(self, client, db_session):
        user = _make_user(db_session, username="rate_user3")
        movie = _make_movie(db_session, tmdb_id=888830003)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        client.post(f"/movie/{movie.id}/rate", data={"rating": 3})
        response = client.post(f"/movie/{movie.id}/rate", data={"rating": 5})
        assert response.status_code == 200
        assert response.get_json()["rating"] == 5

    def test_submit_review_success(self, client, db_session):
        user = _make_user(db_session, username="rate_user4")
        movie = _make_movie(db_session, tmdb_id=888830004)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        response = client.post(
            f"/movie/{movie.id}/review",
            data={"review_content": "This is a great test movie with excellent testing."},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"review has been submitted" in response.data

    def test_submit_review_too_short(self, client, db_session):
        user = _make_user(db_session, username="rate_user5")
        movie = _make_movie(db_session, tmdb_id=888830005)
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
        response = client.post(
            f"/movie/{movie.id}/review",
            data={"review_content": "Short"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"at least 10 characters" in response.data
