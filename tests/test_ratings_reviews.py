"""
Tests for ratings and reviews.

Replaces tests/test_favorites_ratings.py. Its authentication, favorites and
watchlist classes repeated cases already in tests/test_auth.py, so only the
ratings and reviews tests moved here, now checking the database as well as
the response.
"""

from datetime import datetime

import pytest

from src.models import Movie, Rating, Review, User


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


@pytest.fixture
def rater(client, db_session):
    """A logged-in user and a movie, as plain ids."""
    user = _make_user(db_session, username="rate_user")
    movie = _make_movie(db_session, tmdb_id=888830001)
    with client.session_transaction() as sess:
        sess["user_id"] = user.id
    return {"user_id": user.id, "movie_id": movie.id}


class TestRatings:
    def test_submit_rating_success(self, client, db_session, rater):
        response = client.post(f"/movie/{rater['movie_id']}/rate", data={"rating": 4})

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["rating"] == 4
        assert data["num_ratings"] == 1
        stored = db_session.query(Rating).filter_by(user_id=rater["user_id"]).one()
        assert stored.rating == 4

    @pytest.mark.parametrize("value", [0, 6, "", "abc"])
    def test_submit_rating_invalid_value(self, client, db_session, rater, value):
        response = client.post(f"/movie/{rater['movie_id']}/rate", data={"rating": value})

        assert response.status_code == 400
        assert db_session.query(Rating).count() == 0

    def test_update_rating_keeps_one_row(self, client, db_session, rater):
        client.post(f"/movie/{rater['movie_id']}/rate", data={"rating": 3})
        response = client.post(f"/movie/{rater['movie_id']}/rate", data={"rating": 5})

        assert response.status_code == 200
        assert response.get_json()["rating"] == 5
        rows = db_session.query(Rating).filter_by(user_id=rater["user_id"]).all()
        assert [r.rating for r in rows] == [5]

    def test_rating_requires_login(self, client, db_session):
        movie = _make_movie(db_session, tmdb_id=888830002)

        response = client.post(f"/movie/{movie.id}/rate", data={"rating": 4})

        assert response.status_code == 401
        assert db_session.query(Rating).count() == 0

    def test_rating_missing_movie_is_404(self, client, rater):
        assert client.post("/movie/999999/rate", data={"rating": 4}).status_code == 404

    def test_moderated_rating_cannot_be_changed(self, client, db_session, rater):
        client.post(f"/movie/{rater['movie_id']}/rate", data={"rating": 2})
        db_session.query(Rating).update({"is_deleted": True})
        db_session.commit()

        response = client.post(f"/movie/{rater['movie_id']}/rate", data={"rating": 5})

        assert response.status_code == 403
        assert db_session.query(Rating).one().rating == 2


class TestReviews:
    def test_submit_review_success(self, client, db_session, rater):
        text = "This is a great test movie with excellent testing."

        response = client.post(
            f"/movie/{rater['movie_id']}/review",
            data={"review_content": text},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"review has been submitted" in response.data
        assert db_session.query(Review).one().content == text

    def test_submit_review_too_short(self, client, db_session, rater):
        response = client.post(
            f"/movie/{rater['movie_id']}/review",
            data={"review_content": "Short"},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"at least 10 characters" in response.data
        assert db_session.query(Review).count() == 0

    def test_second_review_updates_the_first(self, client, db_session, rater):
        url = f"/movie/{rater['movie_id']}/review"
        client.post(url, data={"review_content": "First thoughts on this movie."})
        client.post(url, data={"review_content": "Second, better thoughts."})

        reviews = db_session.query(Review).all()
        assert [r.content for r in reviews] == ["Second, better thoughts."]

    def test_review_form_shows_your_existing_review(self, client, rater):
        client.post(
            f"/movie/{rater['movie_id']}/review",
            data={"review_content": "Already said my piece here."},
        )

        html = client.get(f"/movie/{rater['movie_id']}").get_data(as_text=True)

        assert "Edit Your Review" in html
        assert "Already said my piece here.</textarea>" in html

    def test_review_requires_login(self, client, db_session):
        movie = _make_movie(db_session, tmdb_id=888830003)

        response = client.post(
            f"/movie/{movie.id}/review", data={"review_content": "Ten characters at least."}
        )

        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login")
        assert db_session.query(Review).count() == 0
