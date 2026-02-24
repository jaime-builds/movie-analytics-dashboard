"""
Tests for routes not previously covered:
- /hidden-gems
- /top-actors
- /actor/<id>
- /directors
- /director/<id>
- /recommendations
- /profile
"""

import pytest

from src.models import Cast, Crew, Movie, Person, Rating, Review, User


# ============================================
# Additional fixtures needed for these tests
# ============================================


@pytest.fixture
def sample_director(db_session, sample_movie):
    """Create a director with at least 3 movies so they appear on the directors page"""
    director = Person(tmdb_id=9999, name="Test Director")
    db_session.add(director)
    db_session.commit()

    # Directors page requires >= 3 movies
    for i in range(3):
        movie = Movie(
            tmdb_id=88800 + i,
            title=f"Director Movie {i}",
            overview="A test movie",
            release_date=None,
            vote_average=7.5,
            vote_count=50,
            popularity=30.0,
        )
        db_session.add(movie)
        db_session.flush()
        crew = Crew(movie_id=movie.id, person_id=director.id, job="Director", department="Directing")
        db_session.add(crew)

    db_session.commit()
    return director


@pytest.fixture
def sample_actor_with_movies(db_session):
    """Create an actor with 2 movies so they appear on the top actors page"""
    actor = Person(tmdb_id=77777, name="Popular Actor")
    db_session.add(actor)
    db_session.commit()

    for i in range(2):
        movie = Movie(
            tmdb_id=77700 + i,
            title=f"Actor Movie {i}",
            overview="A test movie",
            release_date=None,
            vote_average=7.0,
            vote_count=50,
            popularity=40.0,
        )
        db_session.add(movie)
        db_session.flush()
        cast = Cast(movie_id=movie.id, person_id=actor.id, character_name="Hero", cast_order=0)
        db_session.add(cast)

    db_session.commit()
    return actor


@pytest.fixture
def user_with_ratings_and_reviews(db_session, sample_user, sample_movie):
    """Create a user with ratings and reviews for profile tests"""
    rating = Rating(user_id=sample_user.id, movie_id=sample_movie.id, rating=4)
    review = Review(
        user_id=sample_user.id,
        movie_id=sample_movie.id,
        content="This is a great test movie with excellent acting.",
    )
    db_session.add_all([rating, review])
    db_session.commit()
    return sample_user


# ============================================
# Hidden Gems
# ============================================


class TestHiddenGemsRoute:
    """Tests for /hidden-gems"""

    def test_hidden_gems_page_loads(self, client):
        response = client.get("/hidden-gems")
        assert response.status_code == 200

    def test_hidden_gems_has_title(self, client):
        response = client.get("/hidden-gems")
        assert b"Hidden Gems" in response.data or b"hidden-gems" in response.data.lower()

    def test_hidden_gems_with_matching_movies(self, client, db_session):
        # Create a movie that qualifies as a hidden gem
        movie = Movie(
            tmdb_id=55501,
            title="Obscure Masterpiece",
            overview="A hidden gem film",
            release_date=None,
            vote_average=8.0,
            popularity=5.0,
            vote_count=100,
        )
        db_session.add(movie)
        db_session.commit()

        response = client.get("/hidden-gems")
        assert response.status_code == 200
        assert b"Obscure Masterpiece" in response.data

    def test_hidden_gems_filter_by_genre(self, client, sample_genre):
        response = client.get(f"/hidden-gems?genre={sample_genre.id}")
        assert response.status_code == 200

    def test_hidden_gems_filter_by_decade(self, client):
        response = client.get("/hidden-gems?decade=2000")
        assert response.status_code == 200

    def test_hidden_gems_sort_by_rating(self, client):
        response = client.get("/hidden-gems?sort=rating")
        assert response.status_code == 200

    def test_hidden_gems_sort_by_most_hidden(self, client):
        response = client.get("/hidden-gems?sort=most_hidden")
        assert response.status_code == 200

    def test_hidden_gems_custom_min_rating(self, client):
        response = client.get("/hidden-gems?min_rating=8.0")
        assert response.status_code == 200

    def test_hidden_gems_pagination(self, client):
        response = client.get("/hidden-gems?page=1")
        assert response.status_code == 200

    def test_hidden_gems_shows_genre_filter(self, client, sample_genre):
        response = client.get("/hidden-gems")
        assert response.status_code == 200
        assert b"Action" in response.data


# ============================================
# Top Actors
# ============================================


class TestTopActorsRoute:
    """Tests for /top-actors"""

    def test_top_actors_page_loads(self, client):
        response = client.get("/top-actors")
        assert response.status_code == 200

    def test_top_actors_has_title(self, client):
        response = client.get("/top-actors")
        assert b"Actor" in response.data or b"actor" in response.data.lower()

    def test_top_actors_shows_actors(self, client, sample_actor_with_movies):
        response = client.get("/top-actors")
        assert response.status_code == 200
        assert b"Popular Actor" in response.data

    def test_top_actors_sort_by_avg_rating(self, client):
        response = client.get("/top-actors?sort=avg_rating")
        assert response.status_code == 200

    def test_top_actors_sort_by_avg_popularity(self, client):
        response = client.get("/top-actors?sort=avg_popularity")
        assert response.status_code == 200

    def test_top_actors_sort_by_name(self, client):
        response = client.get("/top-actors?sort=name")
        assert response.status_code == 200

    def test_top_actors_pagination(self, client):
        response = client.get("/top-actors?page=1")
        assert response.status_code == 200


# ============================================
# Actor Detail
# ============================================


class TestActorDetailRoute:
    """Tests for /actor/<id>"""

    def test_actor_detail_loads(self, client, sample_person, sample_cast):
        response = client.get(f"/actor/{sample_person.id}")
        assert response.status_code == 200

    def test_actor_detail_shows_name(self, client, sample_person, sample_cast):
        response = client.get(f"/actor/{sample_person.id}")
        assert b"Brad Pitt" in response.data

    def test_actor_detail_shows_filmography(self, client, sample_person, sample_cast):
        response = client.get(f"/actor/{sample_person.id}")
        assert response.status_code == 200
        assert b"Fight Club" in response.data

    def test_actor_detail_shows_character_name(self, client, sample_person, sample_cast):
        response = client.get(f"/actor/{sample_person.id}")
        assert b"Tyler Durden" in response.data

    def test_actor_detail_404_for_invalid_id(self, client):
        response = client.get("/actor/999999")
        assert response.status_code == 404

    def test_actor_detail_shows_stats(self, client, sample_person, sample_cast):
        response = client.get(f"/actor/{sample_person.id}")
        assert response.status_code == 200
        # Should show movie count stat
        assert b"1" in response.data


# ============================================
# Directors
# ============================================


class TestDirectorsRoute:
    """Tests for /directors"""

    def test_directors_page_loads(self, client):
        response = client.get("/directors")
        assert response.status_code == 200

    def test_directors_has_title(self, client):
        response = client.get("/directors")
        assert b"Director" in response.data or b"director" in response.data.lower()

    def test_directors_shows_qualifying_directors(self, client, sample_director):
        response = client.get("/directors")
        assert response.status_code == 200
        assert b"Test Director" in response.data

    def test_directors_pagination(self, client):
        response = client.get("/directors?page=1")
        assert response.status_code == 200


# ============================================
# Director Detail
# ============================================


class TestDirectorDetailRoute:
    """Tests for /director/<id>"""

    def test_director_detail_loads(self, client, sample_director):
        response = client.get(f"/director/{sample_director.id}")
        assert response.status_code == 200

    def test_director_detail_shows_name(self, client, sample_director):
        response = client.get(f"/director/{sample_director.id}")
        assert b"Test Director" in response.data

    def test_director_detail_shows_filmography(self, client, sample_director):
        response = client.get(f"/director/{sample_director.id}")
        assert b"Director Movie" in response.data

    def test_director_detail_shows_stats(self, client, sample_director):
        response = client.get(f"/director/{sample_director.id}")
        assert response.status_code == 200
        # Should show 3 movies in stats
        assert b"3" in response.data

    def test_director_detail_404_for_invalid_id(self, client):
        response = client.get("/director/999999")
        assert response.status_code == 404


# ============================================
# Recommendations
# ============================================


class TestRecommendationsRoute:
    """Tests for /recommendations"""

    def test_recommendations_requires_login(self, client):
        response = client.get("/recommendations", follow_redirects=True)
        assert response.status_code == 200
        assert b"log in" in response.data.lower()

    def test_recommendations_loads_when_logged_in(self, client, logged_in_user):
        response = client.get("/recommendations")
        assert response.status_code == 200

    def test_recommendations_has_title(self, client, logged_in_user):
        response = client.get("/recommendations")
        assert b"Recommendation" in response.data or b"recommendation" in response.data.lower()

    def test_recommendations_with_no_favorites(self, client, logged_in_user, sample_movies):
        # User with no favorites should still get popular movies as recommendations
        response = client.get("/recommendations")
        assert response.status_code == 200

    def test_recommendations_with_favorites(self, client, db_session, logged_in_user, sample_movies):
        # Add favorites so recommendations are personalized
        user = db_session.query(User).filter_by(id=logged_in_user.id).first()
        user.favorites.append(sample_movies[0])
        db_session.commit()

        response = client.get("/recommendations")
        assert response.status_code == 200


# ============================================
# Profile
# ============================================


class TestProfileRoute:
    """Tests for /profile"""

    def test_profile_requires_login(self, client):
        response = client.get("/profile", follow_redirects=True)
        assert response.status_code == 200
        assert b"log in" in response.data.lower()

    def test_profile_redirects_to_login_without_auth(self, client):
        response = client.get("/profile", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location

    def test_profile_loads_when_logged_in(self, client, logged_in_user):
        response = client.get("/profile")
        assert response.status_code == 200

    def test_profile_shows_username(self, client, logged_in_user):
        response = client.get("/profile")
        assert logged_in_user.username.encode() in response.data

    def test_profile_shows_stats(self, client, logged_in_user):
        response = client.get("/profile")
        assert response.status_code == 200
        # Stats section should be present
        assert b"Favorites" in response.data
        assert b"Watchlist" in response.data
        assert b"Ratings" in response.data
        assert b"Reviews" in response.data

    def test_profile_shows_tabs(self, client, logged_in_user):
        response = client.get("/profile")
        assert b"tab" in response.data.lower()

    def test_profile_shows_favorites(self, client, db_session, logged_in_user, sample_movies):
        user = db_session.query(User).filter_by(id=logged_in_user.id).first()
        user.favorites.append(sample_movies[0])
        db_session.commit()

        response = client.get("/profile")
        assert response.status_code == 200
        assert sample_movies[0].title.encode() in response.data

    def test_profile_shows_watchlist(self, client, db_session, logged_in_user, sample_movies):
        user = db_session.query(User).filter_by(id=logged_in_user.id).first()
        user.watchlist.append(sample_movies[0])
        db_session.commit()

        response = client.get("/profile")
        assert response.status_code == 200

    def test_profile_shows_ratings(self, client, logged_in_user, user_with_ratings_and_reviews):
        response = client.get("/profile")
        assert response.status_code == 200
        # Star rating icons should be present
        assert b"bi-star" in response.data

    def test_profile_shows_reviews(self, client, logged_in_user, user_with_ratings_and_reviews):
        response = client.get("/profile")
        assert response.status_code == 200
        assert b"great test movie" in response.data

    def test_profile_empty_state_no_favorites(self, client, logged_in_user):
        response = client.get("/profile")
        assert response.status_code == 200
        assert b"Browse Movies" in response.data

    def test_profile_avg_rating_shown_when_rated(
        self, client, logged_in_user, user_with_ratings_and_reviews
    ):
        response = client.get("/profile")
        assert response.status_code == 200
        assert b"average rating" in response.data.lower()
