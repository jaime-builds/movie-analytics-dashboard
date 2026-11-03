"""
Route and query fixes from the 2026-11 full scan (FS-06 to FS-12, FS-26 to FS-32,
FS-54 to FS-59, RR-03, RR-04, RR-16) and the Box Office by Genre chart.
"""

from datetime import date, timedelta

import pytest

import src.app as app_module
from src.models import (
    Cast,
    Crew,
    Genre,
    Movie,
    PageView,
    Person,
    ProductionCompany,
    local_today,
)


def _movie(tmdb_id, title, **fields):
    defaults = {"vote_average": 7.0, "vote_count": 500, "popularity": 10.0}
    defaults.update(fields)
    return Movie(tmdb_id=tmdb_id, title=title, **defaults)


@pytest.fixture
def director_with_films(db_session):
    director = Person(tmdb_id=5000, name="Ava Director")
    actor = Person(tmdb_id=5001, name="Only Acts")
    dated = _movie(5100, "Dated Film", release_date=date(2010, 1, 1))
    undated = _movie(5101, "Undated Film", release_date=None)
    db_session.add_all([director, actor, dated, undated])
    db_session.commit()
    db_session.add_all(
        [
            Crew(movie_id=dated.id, person_id=director.id, job="Director"),
            Crew(movie_id=undated.id, person_id=director.id, job="Director"),
            Cast(movie_id=dated.id, person_id=actor.id, character_name="Role", cast_order=0),
        ]
    )
    db_session.commit()
    return {"director_id": director.id, "actor_id": actor.id}


class TestMoviesList:
    def test_decade_wins_over_year(self, client, db_session):
        db_session.add_all(
            [
                _movie(1, "Nineties", release_date=date(1995, 6, 1)),
                _movie(2, "Two Thousand Five", release_date=date(2005, 6, 1)),
            ]
        )
        db_session.commit()

        html = client.get("/movies?year=2005&decade=1990").get_data(as_text=True)

        assert "Nineties" in html
        assert "Two Thousand Five" not in html

    def test_upcoming_sort_shows_future_movies_soonest_first(self, client, db_session):
        today = local_today()
        db_session.add_all(
            [
                _movie(3, "Already Out", release_date=today - timedelta(days=10)),
                _movie(4, "Next Month", release_date=today + timedelta(days=30)),
                _movie(5, "Next Week", release_date=today + timedelta(days=7)),
            ]
        )
        db_session.commit()

        html = client.get("/movies?sort=upcoming").get_data(as_text=True)

        assert "Already Out" not in html
        assert html.index("Next Week") < html.index("Next Month")

    def test_equal_ratings_page_without_repeats(self, client, db_session):
        db_session.add_all(
            [_movie(100 + i, f"Tie {i:02d}", vote_average=8.0, vote_count=1000) for i in range(30)]
        )
        db_session.commit()

        first = client.get("/api/v1/movies?sort=rating&per_page=10&page=1").get_json()["movies"]
        second = client.get("/api/v1/movies?sort=rating&per_page=10&page=2").get_json()["movies"]
        third = client.get("/api/v1/movies?sort=rating&per_page=10&page=3").get_json()["movies"]

        ids = [m["id"] for m in first + second + third]
        assert len(ids) == 30
        assert len(set(ids)) == 30


class TestMoviesApi:
    def test_api_supports_every_movies_page_filter(self, client, db_session):
        db_session.add_all(
            [
                _movie(200, "Short Nineties", release_date=date(1994, 1, 1), runtime=80),
                _movie(201, "Long Nineties", release_date=date(1996, 1, 1), runtime=200),
                _movie(202, "Short Eighties", release_date=date(1985, 1, 1), runtime=80),
            ]
        )
        db_session.commit()

        data = client.get("/api/v1/movies?decade=1990&runtime_max=120").get_json()

        assert [m["title"] for m in data["movies"]] == ["Short Nineties"]

    def test_exclude_mature_is_opt_in(self, client, db_session):
        db_session.add_all([_movie(210, "Clean"), _movie(211, "Flagged", is_mature=True)])
        db_session.commit()

        everything = {m["title"] for m in client.get("/api/v1/movies").get_json()["movies"]}
        filtered = {
            m["title"] for m in client.get("/api/v1/movies?exclude_mature=1").get_json()["movies"]
        }

        assert everything == {"Clean", "Flagged"}
        assert filtered == {"Clean"}

    def test_zero_values_stay_zero(self, client, db_session):
        db_session.add(_movie(220, "Unrated", vote_average=0, vote_count=0, popularity=0))
        db_session.commit()

        movie = client.get("/api/v1/movies").get_json()["movies"][0]

        assert movie["vote_average"] == 0.0
        assert movie["popularity"] == 0.0

    def test_total_revenue_is_a_number(self, client, db_session):
        db_session.add(_movie(230, "Earner", revenue=123_456_789))
        db_session.commit()

        data = client.get("/api/v1/analytics/overview").get_json()

        assert data["total_revenue"] == 123_456_789
        assert isinstance(data["total_revenue"], int)


class TestSearch:
    def test_percent_and_underscore_are_literal(self, client, db_session):
        db_session.add_all([_movie(300, "100% Wolf"), _movie(301, "Plain Title")])
        db_session.commit()

        html = client.get("/search?q=%25").get_data(as_text=True)

        assert "100% Wolf" in html
        assert "Plain Title" not in html

    def test_blank_query_shows_no_results(self, client, db_session):
        db_session.add(_movie(302, "Anything"))
        db_session.commit()

        assert b"Anything" not in client.get("/search?q=%20%20").data

    def test_title_matches_rank_above_overview_matches(self, client, db_session):
        db_session.add_all(
            [
                _movie(303, "Some Other Film", overview="A batman parody", popularity=99.0),
                _movie(304, "Batman Begins", overview="Origins", popularity=1.0),
            ]
        )
        db_session.commit()

        movies = client.get("/api/v1/movies/search?q=batman").get_json()["movies"]

        assert [m["title"] for m in movies] == ["Batman Begins", "Some Other Film"]


class TestPeoplePages:
    def test_director_page_lists_undated_films_last(self, client, director_with_films):
        html = client.get(f"/director/{director_with_films['director_id']}").get_data(as_text=True)

        assert html.index("Dated Film") < html.index("Undated Film")

    def test_actor_id_on_director_page_is_404(self, client, director_with_films):
        assert client.get(f"/director/{director_with_films['actor_id']}").status_code == 404

    def test_director_id_on_actor_page_is_404(self, client, director_with_films):
        assert client.get(f"/actor/{director_with_films['director_id']}").status_code == 404

    def test_directors_search_runs_on_the_server(self, client, db_session):
        people = []
        for i in range(30):
            person = Person(tmdb_id=6000 + i, name=f"Director {i:02d}")
            people.append(person)
        db_session.add_all(people)
        movies = [_movie(6100 + i, f"Film {i}") for i in range(30)]
        db_session.add_all(movies)
        db_session.commit()
        for person, movie in zip(people, movies):
            db_session.add(Crew(movie_id=movie.id, person_id=person.id, job="Director"))
        db_session.commit()

        # Page 1 holds 24; "Director 29" is beyond it, and has 1 movie
        html = client.get("/directors?q=Director 29&min_movies=1").get_data(as_text=True)

        assert "Director 29" in html
        assert "Director 03" not in html

    def test_api_actor_lists_each_movie_once(self, client, db_session):
        actor = Person(tmdb_id=7000, name="Two Roles")
        movie = _movie(7100, "Double Act")
        db_session.add_all([actor, movie])
        db_session.commit()
        db_session.add_all(
            [
                Cast(movie_id=movie.id, person_id=actor.id, character_name="Twin A", cast_order=0),
                Cast(movie_id=movie.id, person_id=actor.id, character_name="Twin B", cast_order=1),
            ]
        )
        db_session.commit()

        data = client.get(f"/api/v1/actors/{actor.id}").get_json()

        assert data["total_movies"] == 1
        assert data["filmography"][0]["character"] == "Twin A / Twin B"


class TestDecadesAndStudios:
    def test_decade_must_start_on_a_round_year(self, client, db_session):
        db_session.add(_movie(400, "Eighties", release_date=date(1987, 1, 1)))
        db_session.commit()

        assert client.get("/decade/1980").status_code == 200
        assert client.get("/decade/1987").status_code == 404

    def test_decade_genre_badges_link_by_genre_id(self, client, db_session):
        genre = Genre(tmdb_id=18, name="Drama")
        movie = _movie(401, "Eighties Drama", release_date=date(1984, 1, 1))
        movie.genres.append(genre)
        db_session.add(movie)
        db_session.commit()
        genre_id = genre.id

        html = client.get("/decade/1980").get_data(as_text=True)

        assert f"genre={genre_id}" in html
        assert "genre_name" not in html

    def test_studio_page_paginates_its_movies(self, client, db_session):
        studio = ProductionCompany(tmdb_id=8000, name="Big Studio")
        movies = [_movie(8100 + i, f"Studio Film {i:03d}", popularity=float(i)) for i in range(60)]
        for movie in movies:
            movie.companies.append(studio)
        db_session.add_all(movies)
        db_session.commit()

        html = client.get(f"/company/{studio.id}").get_data(as_text=True)

        assert html.count("Studio Film") < 60 * 2
        assert "page 1 of 2" in html
        assert ">60<" in html.replace(" ", "")


class TestRecommendationsAndMoviePage:
    def test_movie_is_not_recommended_on_its_own_page(self, client, db_session, logged_in_user):
        genre = Genre(tmdb_id=28, name="Action")
        favorite = _movie(500, "Favorite Film")
        current = _movie(501, "Current Film", vote_average=9.5)
        for movie in (favorite, current):
            movie.genres.append(genre)
        db_session.add_all([favorite, current])
        db_session.commit()
        logged_in_user.favorites.append(favorite)
        db_session.commit()
        current_id = current.id

        recs = app_module.get_personalized_recommendations(
            db_session, logged_in_user, exclude_ids=[current_id]
        )

        assert current_id not in [m.id for m in recs]

    def test_tmdb_extras_are_cached_per_movie(self, app, monkeypatch):
        calls = []
        store = {}
        monkeypatch.setattr(
            app_module, "get_trailer_for_movie", lambda tmdb_id: calls.append(tmdb_id)
        )
        monkeypatch.setattr(app_module.cache, "get", store.get)
        monkeypatch.setattr(
            app_module.cache, "set", lambda key, value, timeout=None: store.__setitem__(key, value)
        )
        app.config["TESTING"] = False

        app_module._tmdb_movie_extras(42)
        app_module._tmdb_movie_extras(42)

        assert calls == [42]


class TestPageViews:
    def test_unknown_paths_are_not_counted(self, client, db_session):
        client.get("/wp-login.php")

        assert db_session.query(PageView).count() == 0

    def test_movie_pages_share_one_counter_row(self, client, db_session):
        first, second = _movie(600, "One"), _movie(601, "Two")
        db_session.add_all([first, second])
        db_session.commit()

        client.get(f"/movie/{first.id}")
        client.get(f"/movie/{second.id}")

        rows = db_session.query(PageView).all()
        assert [(r.path, r.count) for r in rows] == [("/movie/<int:movie_id>", 2)]


class TestBoxOfficeByGenre:
    def test_analytics_page_totals_revenue_per_genre(self, client, db_session):
        action, drama = Genre(tmdb_id=28, name="Action"), Genre(tmdb_id=18, name="Drama")
        both = _movie(700, "Both Genres", revenue=300)
        action_only = _movie(701, "Action Only", revenue=100)
        no_revenue = _movie(702, "No Box Office", revenue=0)
        both.genres.extend([action, drama])
        action_only.genres.append(action)
        no_revenue.genres.append(drama)
        db_session.add_all([both, action_only, no_revenue])
        db_session.commit()

        data = app_module._analytics_data(db_session)["box_office_by_genre"]

        assert data == [
            {"name": "Action", "total_revenue": 400, "avg_revenue": 200, "count": 2},
            {"name": "Drama", "total_revenue": 300, "avg_revenue": 300, "count": 1},
        ]
        assert b"Box Office by Genre" in client.get("/analytics").data
