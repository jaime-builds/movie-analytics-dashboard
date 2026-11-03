"""
FS-60: suggestive low-vote movies kept off the home page and Movie of the Day.

A. Top Rated needs TOP_RATED_MIN_VOTES votes.
B. Movies flagged mature (TMDB keywords) never appear on the home page.
C. Admins can hide a movie from the home page.
"""

from datetime import timedelta

import pytest

import src.featured as featured
from src.models import Movie, MovieOfTheDay, User, local_today


def _movie(tmdb_id, title, **fields):
    defaults = {"vote_average": 8.0, "vote_count": 5000, "popularity": 50.0}
    defaults.update(fields)
    return Movie(tmdb_id=tmdb_id, title=title, **defaults)


@pytest.fixture
def admin(db_session):
    user = User(username="siteadmin", is_admin=True)
    user.set_password("password")
    db_session.add(user)
    db_session.commit()
    return user


class TestHomePage:
    def test_top_rated_needs_enough_votes(self, client, db_session):
        db_session.add_all(
            [
                _movie(1, "Niche Nine Four", vote_average=9.4, vote_count=167),
                _movie(2, "Shawshank", vote_average=8.7, vote_count=30000),
            ]
        )
        db_session.commit()

        html = client.get("/").get_data(as_text=True)
        top_rated = html.split("Top Rated Movies")[1].split("Upcoming Releases")[0]

        assert "Shawshank" in top_rated
        assert "Niche Nine Four" not in top_rated

    def test_mature_and_hidden_movies_are_left_out_of_every_section(self, client, db_session):
        future = local_today() + timedelta(days=30)
        db_session.add_all(
            [
                _movie(10, "Flagged Softcore", is_mature=True, release_date=future),
                _movie(11, "Admin Hidden", hide_from_featured=True, release_date=future),
                _movie(12, "Family Film", release_date=future),
            ]
        )
        db_session.commit()

        html = client.get("/").get_data(as_text=True)

        assert "Family Film" in html
        assert "Flagged Softcore" not in html
        assert "Admin Hidden" not in html

    def test_upcoming_see_all_link_uses_a_real_sort(self, client, db_session):
        html = client.get("/").get_data(as_text=True)

        assert "sort=upcoming" in html
        assert 'sort=release"' not in html


class TestMovieOfTheDay:
    def _gem(self, tmdb_id, title, **fields):
        return _movie(tmdb_id, title, vote_average=7.5, vote_count=200, popularity=5.0, **fields)

    def test_pool_skips_mature_and_hidden_movies(self, db_session):
        db_session.add_all(
            [
                self._gem(20, "Softcore Gem", is_mature=True),
                self._gem(21, "Hidden Gem", hide_from_featured=True),
                self._gem(22, "Clean Gem"),
            ]
        )
        db_session.commit()

        pick = featured.get_movie_of_the_day(db_session)

        assert pick.title == "Clean Gem"

    def test_a_pick_flagged_later_is_replaced(self, db_session):
        flagged = self._gem(30, "Flagged After Pick")
        clean = self._gem(31, "Replacement")
        db_session.add_all([flagged, clean])
        db_session.commit()
        db_session.add(MovieOfTheDay(movie_id=flagged.id, shown_date=local_today()))
        flagged.is_mature = True
        db_session.commit()

        pick = featured.get_movie_of_the_day(db_session)

        assert pick.title == "Replacement"
        row = db_session.query(MovieOfTheDay).filter_by(shown_date=local_today()).one()
        assert row.movie_id == clean.id


class TestAdminHideFromFeatured:
    def test_admin_can_hide_and_allow(self, client, db_session, admin):
        movie = _movie(40, "Hide Me")
        db_session.add(movie)
        db_session.commit()
        movie_id = movie.id
        with client.session_transaction() as sess:
            sess["user_id"] = admin.id

        response = client.post(f"/admin/movies/{movie_id}/featured", data={"hidden": "true"})
        assert response.status_code == 302
        assert db_session.query(Movie).filter_by(id=movie_id).one().hide_from_featured is True

        client.post(f"/admin/movies/{movie_id}/featured", data={"hidden": "false"})
        assert db_session.query(Movie).filter_by(id=movie_id).one().hide_from_featured is False

    def test_regular_users_cannot(self, client, db_session, logged_in_user):
        movie = _movie(41, "Stay Visible")
        db_session.add(movie)
        db_session.commit()
        movie_id = movie.id

        response = client.post(f"/admin/movies/{movie_id}/featured", data={"hidden": "true"})

        assert response.status_code == 403
        assert db_session.query(Movie).filter_by(id=movie_id).one().hide_from_featured is False

    def test_movie_page_shows_the_control_to_admins_only(self, client, db_session, admin):
        movie = _movie(42, "Some Film")
        db_session.add(movie)
        db_session.commit()
        movie_id = movie.id
        admin_id = admin.id

        assert b"Hide from home page" not in client.get(f"/movie/{movie_id}").data

        with client.session_transaction() as sess:
            sess["user_id"] = admin_id
        assert b"Hide from home page" in client.get(f"/movie/{movie_id}").data


class TestMovieOfTheDayBoundaries:
    """The gem pool's thresholds are inclusive (GEM_MIN_RATING, GEM_MAX_POPULARITY, GEM_MIN_VOTES)."""

    @pytest.mark.parametrize(
        "fields, eligible",
        [
            ({"vote_average": 7.0, "popularity": 20.0, "vote_count": 50}, True),
            ({"vote_average": 6.9, "popularity": 5.0, "vote_count": 500}, False),
            ({"vote_average": 8.0, "popularity": 20.5, "vote_count": 500}, False),
            ({"vote_average": 8.0, "popularity": 5.0, "vote_count": 49}, False),
        ],
    )
    def test_pool_edges(self, db_session, fields, eligible):
        db_session.add(Movie(tmdb_id=50, title="Edge Case", **fields))
        db_session.commit()

        pick = featured.get_movie_of_the_day(db_session)

        assert (pick is not None) is eligible

    def test_a_pick_from_31_days_ago_can_return(self, db_session):
        gem = Movie(tmdb_id=60, title="Only Gem", vote_average=8.0, vote_count=100, popularity=3.0)
        db_session.add(gem)
        db_session.commit()
        today = local_today()
        # 30 other days of history, then the only gem 31 days ago: it is outside
        # the 30-pick window, so it is a fresh candidate again
        filler = Movie(tmdb_id=61, title="Old Filler", vote_count=1)
        db_session.add(filler)
        db_session.commit()
        for days_ago in range(1, 31):
            db_session.add(
                MovieOfTheDay(movie_id=filler.id, shown_date=today - timedelta(days=days_ago))
            )
        db_session.add(MovieOfTheDay(movie_id=gem.id, shown_date=today - timedelta(days=31)))
        db_session.commit()

        assert featured.get_movie_of_the_day(db_session).title == "Only Gem"
