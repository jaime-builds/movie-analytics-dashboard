"""
Tests for the admin dashboard:
- @admin_required access control
- ban enforcement and banned-user content filtering
- registration toggle
- soft delete / restore / hard delete moderation
- page view tracking
"""

from datetime import datetime

import pytest

from src.models import PageView, Rating, Review, SiteSetting, User

ADMIN_PAGES = [
    "/admin",
    "/admin/analytics",
    "/admin/users",
    "/admin/reviews",
    "/admin/ratings",
]


# ============================================
# Fixtures
# ============================================


def _registration_setting(db_session):
    """Read the registration_enabled value straight from site_settings."""
    setting = db_session.query(SiteSetting).filter_by(key="registration_enabled").first()
    return setting.value if setting else None


def _ban(db_session, user_id):
    """Ban a user by id, re-querying so the row is attached to the session."""
    user = db_session.query(User).filter_by(id=user_id).first()
    user.is_banned = True
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session):
    """Create an administrator account"""
    user = User(username="adminuser", is_admin=True)
    user.set_password("adminpassword")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def logged_in_admin(client, admin_user):
    """Log in as an administrator"""
    with client.session_transaction() as sess:
        sess["user_id"] = admin_user.id
    return admin_user


@pytest.fixture
def other_user(db_session):
    """A second regular account, used as the moderation target"""
    user = User(username="troublemaker")
    user.set_password("password")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def rating_and_review(db_session, sample_movie, other_user):
    """A rating and a review on sample_movie, authored by other_user.

    Returns plain ids/values rather than ORM instances: routes close the
    shared test session, which detaches anything loaded before the request.
    """
    content = "This review should disappear when moderated."
    rating = Rating(user_id=other_user.id, movie_id=sample_movie.id, rating=5)
    review = Review(user_id=other_user.id, movie_id=sample_movie.id, content=content)
    db_session.add_all([rating, review])
    db_session.commit()
    return {
        "rating_id": rating.id,
        "review_id": review.id,
        "content": content,
        "movie_id": sample_movie.id,
        "author_id": other_user.id,
    }


# ============================================
# Admin access control
# ============================================


class TestAdminRequired:
    """The @admin_required decorator gates every /admin route"""

    @pytest.mark.parametrize("path", ADMIN_PAGES)
    def test_anonymous_users_are_sent_to_login(self, client, path):
        response = client.get(path)

        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login?next=")
        assert path in response.headers["Location"]

    @pytest.mark.parametrize(
        "path",
        [
            "/admin/users/1/ban",
            "/admin/users/1/unban",
            "/admin/reviews/1/soft-delete",
            "/admin/reviews/1/restore",
            "/admin/reviews/1/hard-delete",
            "/admin/ratings/1/soft-delete",
            "/admin/ratings/1/restore",
            "/admin/ratings/1/hard-delete",
            "/admin/settings/registration",
        ],
    )
    def test_post_routes_reject_anonymous_and_regular_users(
        self, client, db_session, sample_user, path
    ):
        user_id = sample_user.id
        assert client.post(path).status_code == 403

        with client.session_transaction() as sess:
            sess["user_id"] = user_id
        assert client.post(path).status_code == 403

    @pytest.mark.parametrize("path", ADMIN_PAGES)
    def test_regular_users_get_403(self, client, logged_in_user, path):
        assert client.get(path).status_code == 403

    @pytest.mark.parametrize("path", ADMIN_PAGES)
    def test_admins_get_200(self, client, logged_in_admin, path):
        assert client.get(path).status_code == 200

    def test_post_routes_reject_non_admins(self, client, logged_in_user, other_user):
        response = client.post(f"/admin/users/{other_user.id}/ban")

        assert response.status_code == 403

    def test_banned_admin_loses_access(self, client, db_session, logged_in_admin):
        admin = db_session.query(User).filter_by(id=logged_in_admin.id).first()
        admin.is_banned = True
        db_session.commit()

        response = client.get("/admin")
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login")

    def test_dashboard_shows_site_totals(self, client, logged_in_admin, sample_movies):
        response = client.get("/admin")

        assert response.status_code == 200
        assert b"Page Views" in response.data
        assert b"Movies" in response.data


# ============================================
# Ban / unban
# ============================================


class TestBanFlow:
    """Banning locks the account out and hides its content"""

    def test_ban_sets_flag_and_timestamp(self, client, db_session, logged_in_admin, other_user):
        response = client.post(f"/admin/users/{other_user.id}/ban")

        assert response.status_code == 302
        banned = db_session.query(User).filter_by(id=other_user.id).first()
        assert banned.is_banned is True
        assert banned.banned_at is not None

    def test_unban_clears_flag_and_timestamp(self, client, db_session, logged_in_admin, other_user):
        other_user.is_banned = True
        other_user.banned_at = datetime.utcnow()
        db_session.commit()

        response = client.post(f"/admin/users/{other_user.id}/unban")

        assert response.status_code == 302
        restored = db_session.query(User).filter_by(id=other_user.id).first()
        assert restored.is_banned is False
        assert restored.banned_at is None

    def test_admin_cannot_ban_themselves(self, client, db_session, logged_in_admin):
        response = client.post(f"/admin/users/{logged_in_admin.id}/ban")

        assert response.status_code == 302
        admin = db_session.query(User).filter_by(id=logged_in_admin.id).first()
        assert admin.is_banned is False

    def test_ban_clears_session_on_next_request(self, client, db_session, sample_user):
        with client.session_transaction() as sess:
            sess["user_id"] = sample_user.id

        sample_user.is_banned = True
        db_session.commit()

        response = client.get("/")

        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_banned_user_is_treated_as_logged_out(self, client, db_session, sample_user):
        with client.session_transaction() as sess:
            sess["user_id"] = sample_user.id

        sample_user.is_banned = True
        db_session.commit()

        response = client.get("/favorites")

        # Logged-out visitors are redirected to the login page
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


# ============================================
# Banned-user content filtering
# ============================================


class TestBannedContentIsHidden:
    """A ban hides the account's ratings and reviews everywhere public"""

    def test_review_hidden_from_movie_detail(self, client, db_session, rating_and_review):
        movie_id = rating_and_review["movie_id"]
        content = rating_and_review["content"].encode()

        before = client.get(f"/movie/{movie_id}")
        assert content in before.data

        _ban(db_session, rating_and_review["author_id"])

        after = client.get(f"/movie/{movie_id}")
        assert after.status_code == 200
        assert content not in after.data

    def test_rating_excluded_from_public_average(self, client, db_session, rating_and_review):
        movie_id = rating_and_review["movie_id"]

        before = client.get(f"/api/v1/movies/{movie_id}").get_json()
        assert before["user_rating"]["count"] == 1
        assert before["user_rating"]["average"] == 5.0

        _ban(db_session, rating_and_review["author_id"])

        after = client.get(f"/api/v1/movies/{movie_id}").get_json()
        assert after["user_rating"]["count"] == 0
        assert after["user_rating"]["average"] is None

    def test_banned_content_still_visible_to_admins(
        self, client, db_session, logged_in_admin, rating_and_review
    ):
        _ban(db_session, rating_and_review["author_id"])

        response = client.get("/admin/reviews")

        assert response.status_code == 200
        assert rating_and_review["content"].encode() in response.data


# ============================================
# Registration toggle
# ============================================


class TestRegistrationToggle:
    """site_settings.registration_enabled gates the register route"""

    def test_registration_is_enabled_by_default(self, client):
        response = client.get("/register")

        assert response.status_code == 200
        assert b"Create Account" in response.data
        assert b"registration is currently closed" not in response.data.lower()

    def test_toggle_sets_the_posted_state(self, client, db_session, logged_in_admin):
        response = client.post("/admin/settings/registration", data={"enabled": "false"})

        assert response.status_code == 302
        assert _registration_setting(db_session) == "false"

        client.post("/admin/settings/registration", data={"enabled": "true"})
        assert _registration_setting(db_session) == "true"

    def test_stale_disable_click_does_not_reenable(self, client, db_session, logged_in_admin):
        # Two tabs both showing "Disable": the second click must not flip it back on
        client.post("/admin/settings/registration", data={"enabled": "false"})
        client.post("/admin/settings/registration", data={"enabled": "false"})

        assert _registration_setting(db_session) == "false"

    def test_toggle_rejects_missing_value(self, client, db_session, logged_in_admin):
        client.post("/admin/settings/registration")

        assert _registration_setting(db_session) in (None, "true")

    def test_disabled_registration_shows_closed_message(self, client, db_session):
        db_session.add(SiteSetting(key="registration_enabled", value="false"))
        db_session.commit()

        response = client.get("/register")

        assert response.status_code == 200
        assert b"registration is currently closed" in response.data.lower()

    def test_disabled_registration_blocks_signup(self, client, db_session):
        db_session.add(SiteSetting(key="registration_enabled", value="false"))
        db_session.commit()

        response = client.post(
            "/register",
            data={
                "username": "sneakyuser",
                "password": "password123",
                "password_confirm": "password123",
            },
        )

        assert response.status_code == 200
        assert db_session.query(User).filter_by(username="sneakyuser").first() is None


# ============================================
# Content moderation
# ============================================


class TestReviewModeration:
    """Soft delete hides a review; hard delete removes it"""

    def test_soft_delete_hides_review_from_public_view(
        self, client, db_session, logged_in_admin, rating_and_review
    ):
        review_id = rating_and_review["review_id"]

        response = client.post(f"/admin/reviews/{review_id}/soft-delete")

        assert response.status_code == 302
        moderated = db_session.query(Review).filter_by(id=review_id).first()
        assert moderated.is_deleted is True
        assert moderated.deleted_at is not None

        public = client.get(f"/movie/{rating_and_review['movie_id']}")
        assert rating_and_review["content"].encode() not in public.data

    def test_soft_deleted_review_still_listed_for_admins(
        self, client, logged_in_admin, rating_and_review
    ):
        client.post(f"/admin/reviews/{rating_and_review['review_id']}/soft-delete")

        response = client.get("/admin/reviews")

        assert response.status_code == 200
        assert rating_and_review["content"].encode() in response.data
        assert b"Restore" in response.data

    def test_restore_makes_review_public_again(
        self, client, db_session, logged_in_admin, rating_and_review
    ):
        review_id = rating_and_review["review_id"]
        client.post(f"/admin/reviews/{review_id}/soft-delete")

        response = client.post(f"/admin/reviews/{review_id}/restore")

        assert response.status_code == 302
        restored = db_session.query(Review).filter_by(id=review_id).first()
        assert restored.is_deleted is False
        assert restored.deleted_at is None

        public = client.get(f"/movie/{rating_and_review['movie_id']}")
        assert rating_and_review["content"].encode() in public.data

    def test_hard_delete_removes_the_row(
        self, client, db_session, logged_in_admin, rating_and_review
    ):
        review_id = rating_and_review["review_id"]

        response = client.post(f"/admin/reviews/{review_id}/hard-delete")

        assert response.status_code == 302
        assert db_session.query(Review).filter_by(id=review_id).first() is None


class TestRatingModeration:
    """Soft-deleted ratings drop out of the public average"""

    def test_soft_delete_excludes_rating_from_average(
        self, client, db_session, logged_in_admin, rating_and_review
    ):
        rating_id = rating_and_review["rating_id"]

        response = client.post(f"/admin/ratings/{rating_id}/soft-delete")

        assert response.status_code == 302
        moderated = db_session.query(Rating).filter_by(id=rating_id).first()
        assert moderated.is_deleted is True
        assert moderated.deleted_at is not None

        payload = client.get(f"/api/v1/movies/{rating_and_review['movie_id']}").get_json()
        assert payload["user_rating"]["count"] == 0

    def test_restore_puts_rating_back_in_the_average(
        self, client, logged_in_admin, rating_and_review
    ):
        rating_id = rating_and_review["rating_id"]
        client.post(f"/admin/ratings/{rating_id}/soft-delete")

        response = client.post(f"/admin/ratings/{rating_id}/restore")

        assert response.status_code == 302
        payload = client.get(f"/api/v1/movies/{rating_and_review['movie_id']}").get_json()
        assert payload["user_rating"]["count"] == 1
        assert payload["user_rating"]["average"] == 5.0

    def test_hard_delete_removes_the_row(
        self, client, db_session, logged_in_admin, rating_and_review
    ):
        rating_id = rating_and_review["rating_id"]

        response = client.post(f"/admin/ratings/{rating_id}/hard-delete")

        assert response.status_code == 302
        assert db_session.query(Rating).filter_by(id=rating_id).first() is None


class TestModeratedContentCannotBeRewritten:
    """Authors cannot quietly overwrite content a moderator has hidden"""

    def _soft_delete_as_admin(self, client, db_session, admin_id, url, author_id):
        with client.session_transaction() as sess:
            sess["user_id"] = admin_id
        client.post(url)
        with client.session_transaction() as sess:
            sess["user_id"] = author_id

    def test_rating_rewrite_is_rejected(self, client, db_session, admin_user, rating_and_review):
        movie_id = rating_and_review["movie_id"]
        self._soft_delete_as_admin(
            client,
            db_session,
            admin_user.id,
            f"/admin/ratings/{rating_and_review['rating_id']}/soft-delete",
            rating_and_review["author_id"],
        )

        response = client.post(f"/movie/{movie_id}/rate", data={"rating": 1})

        assert response.status_code == 403
        moderated = db_session.query(Rating).filter_by(id=rating_and_review["rating_id"]).first()
        assert moderated.is_deleted is True
        assert moderated.rating == 5

    def test_review_rewrite_is_rejected(self, client, db_session, admin_user, rating_and_review):
        movie_id = rating_and_review["movie_id"]
        self._soft_delete_as_admin(
            client,
            db_session,
            admin_user.id,
            f"/admin/reviews/{rating_and_review['review_id']}/soft-delete",
            rating_and_review["author_id"],
        )

        response = client.post(
            f"/movie/{movie_id}/review",
            data={"review_content": "Trying to sneak this back in."},
        )

        assert response.status_code == 302
        moderated = db_session.query(Review).filter_by(id=rating_and_review["review_id"]).first()
        assert moderated.is_deleted is True
        assert moderated.content == rating_and_review["content"]


# ============================================
# Page view tracking
# ============================================


def _page_view_count(db_session, path):
    row = (
        db_session.query(PageView)
        .filter_by(path=path, view_date=datetime.now().date())
        .one_or_none()
    )
    return row.count if row else 0


class TestPageViewTracking:
    """GET requests to page routes are counted once per path per day"""

    def test_first_visit_creates_a_row(self, client, db_session):
        client.get("/movies")

        assert _page_view_count(db_session, "/movies") == 1

    def test_repeat_visits_increment_the_same_row(self, client, db_session):
        for _ in range(3):
            client.get("/movies")

        rows = db_session.query(PageView).filter_by(path="/movies").all()
        assert len(rows) == 1
        assert rows[0].count == 3

    def test_separate_paths_get_separate_rows(self, client, db_session):
        client.get("/movies")
        client.get("/analytics")

        assert _page_view_count(db_session, "/movies") == 1
        assert _page_view_count(db_session, "/analytics") == 1

    def test_api_routes_are_not_tracked(self, client, db_session, sample_movie):
        client.get(f"/api/v1/movies/{sample_movie.id}")

        assert db_session.query(PageView).filter(PageView.path.like("/api/%")).count() == 0

    def test_post_requests_are_not_tracked(self, client, db_session, sample_movie):
        client.post(f"/movie/{sample_movie.id}/favorite")

        assert _page_view_count(db_session, f"/movie/{sample_movie.id}/favorite") == 0

    def test_admin_analytics_reports_tracked_views(self, client, logged_in_admin):
        client.get("/movies")
        client.get("/movies")

        response = client.get("/admin/analytics")

        assert response.status_code == 200
        assert b"Page Views per Day" in response.data


# ============================================
# set-admin CLI command
# ============================================


class TestSetAdminCommand:
    def test_grants_and_revokes_admin(self, app, db_session, sample_user):
        user_id = sample_user.id
        runner = app.test_cli_runner()

        result = runner.invoke(args=["set-admin", "testuser"])
        assert result.exit_code == 0, result.output
        assert db_session.query(User).filter_by(id=user_id).one().is_admin is True

        result = runner.invoke(args=["set-admin", "testuser", "--revoke"])
        assert result.exit_code == 0, result.output
        assert db_session.query(User).filter_by(id=user_id).one().is_admin is False

    def test_unknown_user_fails(self, app, db_session):
        result = app.test_cli_runner().invoke(args=["set-admin", "nobody"])

        assert result.exit_code != 0
        assert "No user named" in result.output
