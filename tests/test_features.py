"""
Features added 2026-11-02: family-friendly toggle, box office by genre (see
test_route_fixes.py), blind pick, activity feed, year in review. Plus robots.txt,
favicon and page-level checks from the front-end batch.
"""

from datetime import datetime

import pytest

from src.models import (
    Cast,
    Movie,
    Person,
    Rating,
    Review,
    User,
    user_favorites_table,
    user_watchlist_table,
    utcnow,
)


def _movie(tmdb_id, title, **fields):
    defaults = {"vote_average": 7.0, "vote_count": 500, "popularity": 10.0}
    defaults.update(fields)
    return Movie(tmdb_id=tmdb_id, title=title, **defaults)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


@pytest.fixture
def mixed_movies(db_session):
    db_session.add_all(
        [_movie(1, "Family Film", popularity=50.0), _movie(2, "Softcore Film", is_mature=True)]
    )
    db_session.commit()


# ============================================
# Family-friendly toggle
# ============================================


class TestFamilyFriendly:
    def test_off_by_default(self, client, mixed_movies):
        html = client.get("/movies").get_data(as_text=True)

        assert "Softcore Film" in html
        assert 'aria-pressed="false"' in html

    def test_on_hides_mature_movies_from_lists_and_search(self, client, mixed_movies):
        response = client.post(
            "/preferences/family-friendly", data={"enabled": "true", "next": "/movies"}
        )
        assert response.status_code == 302
        assert response.headers["Location"] == "/movies"

        movies_html = client.get("/movies").get_data(as_text=True)
        search_html = client.get("/search?q=Film").get_data(as_text=True)

        assert "Family Film" in movies_html
        assert "Softcore Film" not in movies_html
        assert "Softcore Film" not in search_html

    def test_api_stays_unfiltered_unless_asked(self, client, mixed_movies):
        client.post("/preferences/family-friendly", data={"enabled": "true"})

        titles = {m["title"] for m in client.get("/api/v1/movies").get_json()["movies"]}

        assert titles == {"Family Film", "Softcore Film"}

    def test_movies_page_tells_infinite_scroll_to_exclude(self, client, mixed_movies):
        client.post("/preferences/family-friendly", data={"enabled": "true"})

        assert 'data-exclude-mature="1"' in client.get("/movies").get_data(as_text=True)

    def test_turning_it_off(self, client, mixed_movies):
        client.post("/preferences/family-friendly", data={"enabled": "true"})
        client.post("/preferences/family-friendly", data={"enabled": "false"})

        assert "Softcore Film" in client.get("/movies").get_data(as_text=True)

    def test_survives_login_and_logout(self, client, mixed_movies, sample_user):
        client.post("/preferences/family-friendly", data={"enabled": "true"})
        client.post("/login", data={"username": "testuser", "password": "testpassword"})
        client.post("/logout")

        with client.session_transaction() as sess:
            assert sess.get("family_friendly") is True
            assert "user_id" not in sess

    def test_movie_pages_stay_reachable(self, client, db_session, mixed_movies):
        client.post("/preferences/family-friendly", data={"enabled": "true"})
        movie_id = db_session.query(Movie).filter_by(title="Softcore Film").one().id

        assert client.get(f"/movie/{movie_id}").status_code == 200


# ============================================
# Blind pick
# ============================================


class TestBlindPick:
    def test_requires_login(self, client):
        response = client.get("/watchlist/blind-pick")

        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login")

    def test_empty_watchlist_goes_back_with_a_message(self, client, logged_in_user):
        response = client.get("/watchlist/blind-pick", follow_redirects=True)

        assert b"Your watchlist is empty" in response.data

    def test_picks_a_movie_from_the_watchlist(self, client, db_session, user_with_watchlist):
        user_id = user_with_watchlist.id
        watchlist_ids = {
            row.movie_id
            for row in db_session.query(user_watchlist_table.c.movie_id).filter(
                user_watchlist_table.c.user_id == user_id
            )
        }
        _login(client, user_id)

        for _ in range(5):
            location = client.get("/watchlist/blind-pick").headers["Location"]
            assert int(location.rsplit("/", 1)[1]) in watchlist_ids

    def test_watchlist_page_offers_the_button(self, client, user_with_watchlist):
        _login(client, user_with_watchlist.id)

        assert b"Blind Pick" in client.get("/watchlist").data


# ============================================
# Activity feed
# ============================================


@pytest.fixture
def feed_data(db_session, sample_movie):
    alice = User(username="alice")
    banned = User(username="banned_bob", is_banned=True)
    shy = User(username="shy_sam", hide_activity=True)
    for user in (alice, banned, shy):
        user.set_password("password")
    db_session.add_all([alice, banned, shy])
    db_session.commit()
    long_text = "Great film. " * 40
    db_session.add_all(
        [
            Rating(user_id=alice.id, movie_id=sample_movie.id, rating=5),
            Review(user_id=alice.id, movie_id=sample_movie.id, content=long_text),
            Rating(user_id=banned.id, movie_id=sample_movie.id, rating=1),
            Rating(user_id=shy.id, movie_id=sample_movie.id, rating=3),
        ]
    )
    db_session.commit()
    return {"alice_id": alice.id, "shy_id": shy.id, "long_text": long_text}


class TestActivityFeed:
    def test_public_and_lists_visible_activity(self, client, feed_data):
        html = client.get("/activity").get_data(as_text=True)

        assert "alice" in html
        assert "rated" in html and "reviewed" in html
        assert "banned_bob" not in html
        assert "shy_sam" not in html

    def test_review_text_is_shortened(self, client, feed_data):
        html = client.get("/activity").get_data(as_text=True)

        assert feed_data["long_text"].strip() not in html
        assert "Great film." in html

    def test_moderated_items_are_left_out(self, client, db_session, feed_data):
        db_session.query(Review).update({"is_deleted": True})
        db_session.commit()

        assert "reviewed" not in client.get("/activity").get_data(as_text=True)

    def test_mature_movies_are_hidden_when_family_friendly(self, client, db_session, feed_data):
        db_session.query(Movie).update({"is_mature": True})
        db_session.commit()
        client.post("/preferences/family-friendly", data={"enabled": "true"})

        assert "alice" not in client.get("/activity").get_data(as_text=True)

    def test_users_can_opt_out_and_back_in(self, client, db_session, feed_data):
        _login(client, feed_data["alice_id"])

        client.post("/profile/activity-visibility", data={"hidden": "true"})
        assert (
            db_session.query(User).filter_by(id=feed_data["alice_id"]).one().hide_activity is True
        )
        # Alice is logged in, so her name is in the navbar; check the feed entries
        assert "<strong>alice</strong>" not in client.get("/activity").get_data(as_text=True)

        client.post("/profile/activity-visibility", data={"hidden": "false"})
        assert "<strong>alice</strong>" in client.get("/activity").get_data(as_text=True)

    def test_profile_shows_the_setting(self, client, feed_data):
        _login(client, feed_data["alice_id"])

        assert b"Hide my activity" in client.get("/profile").data


# ============================================
# Year in review
# ============================================


class TestYearInReview:
    def test_requires_login(self, client):
        assert client.get("/year-in-review").status_code == 302

    def test_counts_this_years_activity(self, client, db_session, sample_user, sample_movies):
        year = utcnow().year
        user_id = sample_user.id
        db_session.add_all(
            [
                Rating(user_id=user_id, movie_id=sample_movies[0].id, rating=5),
                Rating(user_id=user_id, movie_id=sample_movies[1].id, rating=3),
                Rating(
                    user_id=user_id,
                    movie_id=sample_movies[2].id,
                    rating=4,
                    created_at=datetime(year - 1, 6, 1),
                ),
                Review(
                    user_id=user_id, movie_id=sample_movies[0].id, content="Loved every minute."
                ),
            ]
        )
        db_session.commit()
        _login(client, user_id)
        client.post(f"/movie/{sample_movies[3].id}/favorite")

        html = client.get(f"/year-in-review?year={year}").get_data(as_text=True)

        assert f"{year} in Review" in html
        assert '<p class="display-6 mb-0">2</p>' in html  # two ratings this year
        assert "4.0 / 5" in html  # average of 5 and 3
        assert "Favorites added" in html

    def test_favorites_record_when_they_were_added(
        self, client, db_session, logged_in_user, sample_movie
    ):
        client.post(f"/movie/{sample_movie.id}/favorite")

        added_at = db_session.query(user_favorites_table.c.added_at).scalar()

        assert added_at is not None
        assert added_at.year == utcnow().year

    def test_empty_year_explains_itself(self, client, logged_in_user):
        html = client.get("/year-in-review?year=2001").get_data(as_text=True)

        assert "No activity recorded for 2001" in html

    def test_future_year_is_404(self, client, logged_in_user):
        assert client.get(f"/year-in-review?year={utcnow().year + 1}").status_code == 404


# ============================================
# Site basics and front-end checks
# ============================================


class TestSiteBasics:
    def test_robots_txt(self, client):
        response = client.get("/robots.txt")

        assert response.status_code == 200
        assert response.mimetype == "text/plain"
        assert "Disallow: /admin" in response.get_data(as_text=True)

    def test_favicon_redirects_to_the_logo(self, client):
        response = client.get("/favicon.ico")

        assert response.status_code == 301
        assert response.headers["Location"].endswith("jaime_builds_logo.png")

    def test_pages_carry_description_and_open_graph_tags(self, client):
        html = client.get("/").get_data(as_text=True)

        assert '<meta name="description"' in html
        assert 'property="og:title"' in html
        assert 'rel="icon"' in html

    def test_cdn_assets_are_integrity_checked(self, client):
        html = client.get("/").get_data(as_text=True)

        assert html.count('integrity="sha384-') >= 3
        assert "ui-avatars.com" not in html

    def test_chart_library_only_on_chart_pages(self, client):
        assert b"chart.umd.min.js" not in client.get("/movies").data
        assert b"chart.umd.min.js" in client.get("/analytics").data

    def test_common_films_remove_buttons_work_without_the_search_box(self, client, db_session):
        actors = [Person(tmdb_id=9000 + i, name=f"Actor {i}") for i in range(5)]
        movie = _movie(9100, "Ensemble")
        db_session.add_all(actors + [movie])
        db_session.commit()
        for actor in actors:
            db_session.add(Cast(movie_id=movie.id, person_id=actor.id, character_name="Role"))
        db_session.commit()
        query = "&".join(f"actor={a.id}" for a in actors)

        html = client.get(f"/common-films?{query}").get_data(as_text=True)

        assert 'id="cf-actor-input"' not in html  # 5 actors: no search box
        assert html.count('class="cf-chip-remove"') == 5
        # removeActor is wired before the script's early return
        script = html[html.index("const selectedIds") :]
        assert script.index("cf-chip-remove") < script.index("if (!input) return;")

    def test_admin_ban_form_uses_data_confirm(self, client, db_session):
        admin = User(username="boss", is_admin=True)
        admin.set_password("password")
        target = User(username="someone")
        target.set_password("password")
        db_session.add_all([admin, target])
        db_session.commit()
        _login(client, admin.id)

        html = client.get("/admin/users").get_data(as_text=True)

        assert 'data-confirm="Ban someone?' in html
