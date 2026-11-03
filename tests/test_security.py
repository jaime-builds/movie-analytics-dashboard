"""
Security fixes from the 2026-11 review (RR and FS findings):
- admin Ban confirm can't run a username as script (FS-01)
- username rules and case-insensitive uniqueness (RR-08, FS-33)
- login and register rate limits (RR-01)
- revocable sessions (RR-09)
- review deletion rules (RR-23, FS-34, FS-16)
- security headers, HTTPS redirect, error pages (RR-07, RR-20, RR-18)
- TMDB key never logged (FS-02)
"""

import logging
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest
import requests

import src.app as app_module
from src.app import limiter
from src.models import Review, User
from src.tmdb_api import TMDBClient, TMDBError


@contextmanager
def rate_limits_on(app):
    previous_enabled = getattr(limiter, "enabled", True)
    app.config["RATELIMIT_ENABLED"] = True
    limiter.enabled = True
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = previous_enabled
        app.config["RATELIMIT_ENABLED"] = False


def _register(client, username, password="secret123", confirm=None):
    return client.post(
        "/register",
        data={
            "username": username,
            "password": password,
            "password_confirm": confirm or password,
        },
    )


# ============================================
# FS-01: admin Ban confirm
# ============================================


class TestAdminBanConfirm:
    def test_username_goes_in_a_data_attribute_not_script(self, client, db_session):
        admin = User(username="boss", is_admin=True)
        admin.set_password("password")
        attacker = User(username="x');alert(1);('")
        attacker.set_password("password")
        db_session.add_all([admin, attacker])
        db_session.commit()
        with client.session_transaction() as sess:
            sess["user_id"] = admin.id

        html = client.get("/admin/users").get_data(as_text=True)

        assert "onsubmit" not in html
        assert 'data-confirm="Ban x&#39;);alert(1);(&#39;?' in html


# ============================================
# RR-08 / FS-33: username rules
# ============================================


class TestUsernameRules:
    def test_rejects_usernames_over_30_characters(self, client, db_session):
        response = _register(client, "a" * 31)

        assert response.status_code == 200
        assert b"30 characters or fewer" in response.data
        assert db_session.query(User).count() == 0

    @pytest.mark.parametrize("username", ["has space", "semi;colon", "quote'd", "<script>"])
    def test_rejects_disallowed_characters(self, client, db_session, username):
        response = _register(client, username)

        assert b"can only use letters" in response.data
        assert db_session.query(User).count() == 0

    def test_accepts_allowed_characters(self, client, db_session):
        response = _register(client, "film_fan-01.x")

        assert response.status_code == 302
        assert db_session.query(User).filter_by(username="film_fan-01.x").count() == 1

    def test_duplicate_check_ignores_case(self, client, db_session, sample_user):
        response = _register(client, sample_user.username.upper())

        assert b"Username already exists" in response.data
        assert db_session.query(User).count() == 1

    def test_failed_signup_keeps_the_typed_username(self, client):
        response = _register(client, "keepme", confirm="different1")

        assert b'value="keepme"' in response.data


# ============================================
# RR-01: rate limits
# ============================================


class TestRateLimits:
    def test_login_is_limited_per_ip(self, app, db_session):
        with rate_limits_on(app), app.test_client() as c:
            statuses = [
                c.post(
                    "/login",
                    data={"username": f"nobody{i}", "password": "wrong"},
                    environ_base={"REMOTE_ADDR": "203.0.113.10"},
                ).status_code
                for i in range(11)
            ]

        assert statuses[:10] == [200] * 10
        assert statuses[10] == 429

    def test_failed_logins_are_limited_per_username(self, app, db_session, sample_user):
        with rate_limits_on(app), app.test_client() as c:
            # Different IPs, same target account: the per-username cap still applies
            statuses = [
                c.post(
                    "/login",
                    data={"username": sample_user.username, "password": "wrong"},
                    environ_base={"REMOTE_ADDR": f"203.0.113.{i}"},
                ).status_code
                for i in range(11)
            ]

        assert statuses[10] == 429

    def test_successful_logins_do_not_use_up_the_username_limit(self, app, db_session):
        user = User(username="regular")
        user.set_password("rightpass")
        db_session.add(user)
        db_session.commit()

        with rate_limits_on(app), app.test_client() as c:
            statuses = [
                c.post(
                    "/login",
                    data={"username": "regular", "password": "rightpass"},
                    environ_base={"REMOTE_ADDR": f"198.51.100.{i}"},
                ).status_code
                for i in range(12)
            ]

        assert set(statuses) == {302}

    def test_register_is_limited_per_ip(self, app, db_session):
        with rate_limits_on(app), app.test_client() as c:
            statuses = [
                c.post(
                    "/register",
                    data={"username": "x", "password": "p", "password_confirm": "p"},
                    environ_base={"REMOTE_ADDR": "203.0.113.50"},
                ).status_code
                for _ in range(11)
            ]

        assert statuses[10] == 429

    def test_rate_limited_page_is_friendly_html(self, app, db_session):
        with rate_limits_on(app), app.test_client() as c:
            for _ in range(11):
                response = c.post(
                    "/login",
                    data={"username": "u", "password": "p"},
                    environ_base={"REMOTE_ADDR": "203.0.113.77"},
                )

        assert response.status_code == 429
        assert b"Slow down" in response.data

    def test_admin_pages_skip_the_default_limit(self, app):
        with app.test_request_context("/admin/users"):
            assert app_module._is_admin_endpoint() is True
        with app.test_request_context("/movies"):
            assert app_module._is_admin_endpoint() is False


# ============================================
# RR-09: revocable sessions
# ============================================


class TestSessionRevocation:
    def test_copied_cookie_stops_working_after_logout(self, client, db_session, sample_user):
        client.post("/login", data={"username": "testuser", "password": "testpassword"})
        stolen = client.get_cookie("session").value

        client.post("/logout")

        thief = client.application.test_client()
        thief.set_cookie("session", stolen)
        response = thief.get("/profile")

        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login")

    def test_ban_ends_existing_sessions(self, client, db_session, sample_user):
        client.post("/login", data={"username": "testuser", "password": "testpassword"})
        assert client.get("/profile").status_code == 200

        user = db_session.query(User).filter_by(id=sample_user.id).first()
        user.session_version += 1
        db_session.commit()

        assert client.get("/profile").status_code == 302

    def test_login_starts_a_fresh_session(self, client, db_session, sample_user):
        with client.session_transaction() as sess:
            sess["planted"] = "value"

        client.post("/login", data={"username": "testuser", "password": "testpassword"})

        with client.session_transaction() as sess:
            assert "planted" not in sess
            assert sess["user_id"] == sample_user.id


# ============================================
# RR-23 / FS-34 / FS-16: deleting reviews
# ============================================


@pytest.fixture
def own_review(db_session, sample_user, sample_movie):
    review = Review(user_id=sample_user.id, movie_id=sample_movie.id, content="A fine film indeed.")
    db_session.add(review)
    db_session.commit()
    return {"id": review.id, "movie_id": sample_movie.id}


class TestDeleteReview:
    def test_anonymous_gets_401(self, client, own_review):
        response = client.post(f"/movie/{own_review['movie_id']}/review/{own_review['id']}/delete")

        assert response.status_code == 401

    def test_missing_review_gets_404(self, client, logged_in_user, sample_movie):
        response = client.post(f"/movie/{sample_movie.id}/review/9999/delete")

        assert response.status_code == 404

    def test_review_must_belong_to_the_movie_in_the_url(
        self, client, db_session, logged_in_user, own_review
    ):
        response = client.post(
            f"/movie/{own_review['movie_id'] + 1}/review/{own_review['id']}/delete"
        )

        assert response.status_code == 404
        assert db_session.query(Review).filter_by(id=own_review["id"]).count() == 1

    def test_other_users_review_is_refused(self, client, db_session, own_review, multiple_users):
        with client.session_transaction() as sess:
            sess["user_id"] = multiple_users[0].id

        response = client.post(f"/movie/{own_review['movie_id']}/review/{own_review['id']}/delete")

        assert response.status_code == 403
        assert db_session.query(Review).filter_by(id=own_review["id"]).count() == 1

    def test_owner_can_delete(self, client, db_session, logged_in_user, own_review):
        response = client.post(f"/movie/{own_review['movie_id']}/review/{own_review['id']}/delete")

        assert response.status_code == 200
        assert db_session.query(Review).filter_by(id=own_review["id"]).count() == 0

    def test_moderated_review_cannot_be_deleted_by_its_author(
        self, client, db_session, logged_in_user, own_review
    ):
        review = db_session.query(Review).filter_by(id=own_review["id"]).first()
        review.is_deleted = True
        db_session.commit()

        response = client.post(f"/movie/{own_review['movie_id']}/review/{own_review['id']}/delete")

        assert response.status_code == 403
        assert db_session.query(Review).filter_by(id=own_review["id"]).count() == 1

    def test_overlong_review_is_rejected(self, client, db_session, logged_in_user, sample_movie):
        client.post(
            f"/movie/{sample_movie.id}/review",
            data={"review_content": "x" * (app_module.MAX_REVIEW_LENGTH + 1)},
        )

        assert db_session.query(Review).count() == 0


# ============================================
# RR-07 / RR-20 / RR-18: headers, HTTPS, error pages
# ============================================


class TestHeadersAndErrors:
    def test_security_headers_on_every_page(self, client):
        response = client.get("/")

        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert "Strict-Transport-Security" not in response.headers

    def test_hsts_only_over_https(self, client):
        response = client.get("/", base_url="https://localhost")

        assert response.headers["Strict-Transport-Security"] == "max-age=31536000"

    def test_plain_http_through_the_tunnel_redirects_in_production(self, client, monkeypatch):
        monkeypatch.setattr(app_module.Config, "IS_PRODUCTION", True)

        response = client.get("/movies?page=2", headers={"X-Forwarded-Proto": "http"})

        assert response.status_code == 301
        assert response.headers["Location"] == "https://localhost/movies?page=2"

    def test_direct_lan_http_is_not_redirected(self, client, monkeypatch):
        monkeypatch.setattr(app_module.Config, "IS_PRODUCTION", True)

        assert client.get("/").status_code == 200

    def test_unknown_page_renders_the_404_page(self, client):
        response = client.get("/no-such-page")

        assert response.status_code == 404
        assert b"Page not found" in response.data
        assert b"<html" in response.data

    def test_unknown_api_path_returns_json(self, client):
        response = client.get("/api/v1/no-such-endpoint")

        assert response.status_code == 404
        assert response.get_json() == {"error": "Page not found"}

    def test_huge_page_number_is_capped(self, client, sample_movies):
        assert client.get("/movies?page=99999999999999999999").status_code == 200
        assert client.get("/api/v1/movies?page=99999999999999999999").status_code == 200


# ============================================
# FS-02: the TMDB key never reaches the logs
# ============================================


class TestTMDBKeyRedaction:
    def _failing_get(self, exc):
        return Mock(side_effect=exc)

    def test_http_error_logs_status_only(self, caplog):
        response = Mock(status_code=404)
        error = requests.HTTPError(
            "404 Client Error: Not Found for url: https://api.themoviedb.org/3/movie/1?api_key=test-api-key",
            response=response,
        )
        response.raise_for_status = Mock(side_effect=error)
        with patch("src.tmdb_api.requests.get", return_value=response):
            with caplog.at_level(logging.WARNING, logger="src.tmdb_api"):
                assert TMDBClient().get_movie_details(1) == {}

        assert "test-api-key" not in caplog.text
        assert "HTTP 404" in caplog.text

    def test_connection_error_text_is_redacted(self, caplog):
        error = requests.ConnectionError(
            "Max retries exceeded with url: /3/movie/1?api_key=test-api-key"
        )
        with patch("src.tmdb_api.requests.get", side_effect=error):
            with caplog.at_level(logging.WARNING, logger="src.tmdb_api"):
                TMDBClient().get_movie_details(1)

        assert "test-api-key" not in caplog.text
        assert "api_key=***" in caplog.text

    def test_raise_errors_mode_raises_without_the_key(self):
        error = requests.ConnectionError("url: /3/movie/1?api_key=test-api-key")
        with patch("src.tmdb_api.requests.get", side_effect=error):
            with pytest.raises(TMDBError) as excinfo:
                TMDBClient(raise_errors=True).get_movie_details(1)

        assert "test-api-key" not in str(excinfo.value)

    def test_missing_key_fails_without_a_request(self, monkeypatch):
        monkeypatch.setattr("src.tmdb_api.Config.TMDB_API_KEY", None)
        with patch("src.tmdb_api.requests.get") as mock_get:
            assert TMDBClient().get_genres() == []

        mock_get.assert_not_called()


# ============================================
# FS-33: double-clicks don't 500
# ============================================


class TestDoubleSubmit:
    def test_second_insert_of_the_same_favorite_is_harmless(
        self, db_session, sample_user, sample_movie
    ):
        from src.models import user_favorites_table

        first = app_module._insert_association(
            db_session, user_favorites_table, user_id=sample_user.id, movie_id=sample_movie.id
        )
        second = app_module._insert_association(
            db_session, user_favorites_table, user_id=sample_user.id, movie_id=sample_movie.id
        )

        assert (first, second) == (True, False)
