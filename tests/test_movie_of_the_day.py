"""
Tests for the Movie of the Day feature:
- get_movie_of_the_day() selection helper (insert, idempotency, exclusion,
  race-condition conflict handling, empty-pool fallback)
- Homepage section rendering
"""

import hashlib
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from src.app import get_movie_of_the_day
from src.models import Movie, MovieOfTheDay

# ============================================
# Helpers / extra fixtures
# ============================================


@pytest.fixture
def gem_movies(db_session):
    """Create 35 movies matching the Hidden Gems criteria."""
    movies = []
    for i in range(35):
        movie = Movie(
            tmdb_id=70000 + i,
            title=f"Hidden Gem {i}",
            overview="An underseen classic",
            release_date=date(2000 + (i % 20), 1, 1),
            vote_average=7.5,
            vote_count=120,
            popularity=10.0,
        )
        movies.append(movie)
    db_session.add_all(movies)
    db_session.commit()
    return movies


def _expected_pick(candidates):
    """Mirror the deterministic selection: sha256 of today's ISO date mod pool size."""
    ordered = sorted(candidates, key=lambda m: m.id)
    digest = hashlib.sha256(date.today().isoformat().encode("utf-8")).hexdigest()
    return ordered[int(digest, 16) % len(ordered)]


def _insert_history(db_session, movies, days_back_start=1):
    """Insert one movie_of_the_day row per movie on consecutive past days."""
    today = datetime.now().date()
    for offset, movie in enumerate(movies, start=days_back_start):
        db_session.add(MovieOfTheDay(movie_id=movie.id, shown_date=today - timedelta(days=offset)))
    db_session.commit()


# ============================================
# Selection helper
# ============================================


class TestMovieOfTheDaySelection:
    def test_first_request_inserts_row(self, db_session, gem_movies):
        pick = get_movie_of_the_day(db_session)

        assert pick is not None
        assert pick.id in {m.id for m in gem_movies}

        rows = db_session.query(MovieOfTheDay).all()
        assert len(rows) == 1
        assert rows[0].movie_id == pick.id
        assert rows[0].shown_date == datetime.now().date()

    def test_pick_is_deterministic(self, db_session, gem_movies):
        pick = get_movie_of_the_day(db_session)
        assert pick.id == _expected_pick(gem_movies).id

    def test_same_day_idempotent(self, db_session, gem_movies):
        first = get_movie_of_the_day(db_session)
        second = get_movie_of_the_day(db_session)

        assert first.id == second.id
        assert db_session.query(MovieOfTheDay).count() == 1

    def test_excludes_last_30_picks(self, db_session, gem_movies):
        shown = gem_movies[:30]
        _insert_history(db_session, shown)

        pick = get_movie_of_the_day(db_session)

        assert pick is not None
        assert pick.id not in {m.id for m in shown}
        assert pick.id in {m.id for m in gem_movies[30:]}

    def test_fallback_when_pool_exhausted(self, db_session, gem_movies):
        # Shrink the gem pool to 5 by disqualifying the rest, then exhaust it
        pool = gem_movies[:5]
        for movie in gem_movies[5:]:
            movie.vote_average = 5.0
        db_session.commit()
        _insert_history(db_session, pool)

        pick = get_movie_of_the_day(db_session)

        assert pick is not None
        assert pick.id in {m.id for m in pool}
        today_row = (
            db_session.query(MovieOfTheDay)
            .filter(MovieOfTheDay.shown_date == datetime.now().date())
            .one()
        )
        assert today_row.movie_id == pick.id

    def test_no_gems_returns_none(self, db_session, sample_movies):
        # sample_movies all have popularity >= 50, so the gem pool is empty
        assert get_movie_of_the_day(db_session) is None
        assert db_session.query(MovieOfTheDay).count() == 0

    def test_race_conflict_uses_other_workers_pick(self, db_session, gem_movies, monkeypatch):
        today = datetime.now().date()
        expected = _expected_pick(gem_movies)
        other_pick_id = next(m.id for m in gem_movies if m.id != expected.id)

        real_begin_nested = db_session.begin_nested
        state = {"raced": False}

        def racing_begin_nested():
            # Just before this worker's insert savepoint starts, land the
            # competing worker's row so the flush hits a genuine UNIQUE
            # violation (and the row survives the savepoint rollback).
            if not state["raced"]:
                state["raced"] = True
                db_session.execute(
                    MovieOfTheDay.__table__.insert().values(
                        movie_id=other_pick_id, shown_date=today
                    )
                )
            return real_begin_nested()

        monkeypatch.setattr(db_session, "begin_nested", racing_begin_nested)

        result = get_movie_of_the_day(db_session)

        assert result is not None
        assert result.id == other_pick_id
        rows = db_session.query(MovieOfTheDay).filter(MovieOfTheDay.shown_date == today).all()
        assert len(rows) == 1
        assert rows[0].movie_id == other_pick_id

    def test_integrity_error_without_row_returns_none(self, db_session, gem_movies, monkeypatch):
        # Pathological case: the insert fails but no competing row exists
        # (e.g. a transient constraint error) — helper degrades to None.
        def failing_begin_nested():
            raise IntegrityError("stub failure", None, Exception("stub"))

        monkeypatch.setattr(db_session, "begin_nested", failing_begin_nested)

        assert get_movie_of_the_day(db_session) is None


# ============================================
# Homepage rendering
# ============================================


class TestMovieOfTheDayHomepage:
    def test_homepage_shows_section(self, client, gem_movies):
        response = client.get("/")

        assert response.status_code == 200
        assert b"Movie of the Day" in response.data

    def test_homepage_links_to_movie_detail(self, client, db_session, gem_movies):
        response = client.get("/")
        today_row = db_session.query(MovieOfTheDay).one()

        assert f"/movie/{today_row.movie_id}".encode() in response.data

    def test_homepage_hides_section_without_gems(self, client, sample_movies):
        response = client.get("/")

        assert response.status_code == 200
        assert b"Movie of the Day" not in response.data
