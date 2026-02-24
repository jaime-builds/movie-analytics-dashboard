"""
Pytest configuration and fixtures for testing
"""

from datetime import datetime

import pytest

from config.config import Config
from src.app import app as flask_app
from src.models import (
    Base,
    Cast,
    Crew,
    Genre,
    Movie,
    Person,
    ProductionCompany,
    Session,
    User,
    engine,
)


@pytest.fixture(scope="function")
def app():
    """Create application for testing"""
    flask_app.config.update(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,  # Disable CSRF for testing
            "SECRET_KEY": "test-secret-key",
        }
    )

    yield flask_app


@pytest.fixture(scope="function")
def db_session(app):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    import src.app

    original_get_db_session = src.app.get_db_session
    src.app.get_db_session = lambda: session

    yield session

    src.app.get_db_session = original_get_db_session
    session.close()
    transaction.rollback()
    connection.close()
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(app, db_session):
    """Create test client - depends on db_session to ensure proper setup"""
    return app.test_client()


@pytest.fixture(scope="function")
def sample_genre(db_session):
    """Create a sample genre"""
    genre = Genre(tmdb_id=28, name="Action")
    db_session.add(genre)
    db_session.commit()
    return genre


@pytest.fixture(scope="function")
def sample_person(db_session):
    """Create a sample person (actor)"""
    person = Person(tmdb_id=287, name="Brad Pitt", profile_path="/kU3B75TyRiCgE270EyZnHjfivoq.jpg")
    db_session.add(person)
    db_session.commit()
    return person


@pytest.fixture(scope="function")
def sample_movie(db_session, sample_genre):
    """Create a sample movie"""
    movie = Movie(
        tmdb_id=550,
        title="Fight Club",
        original_title="Fight Club",
        overview="An insomniac office worker and a devil-may-care soapmaker form an underground fight club.",
        release_date=datetime.strptime("1999-10-15", "%Y-%m-%d").date(),
        runtime=139,
        budget=63000000,
        revenue=100853753,
        popularity=61.416,
        vote_average=8.4,
        vote_count=25000,
        poster_path="/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
        backdrop_path="/fCayJrkfRaCRCTh8GqN30f8oyQF.jpg",
        imdb_id="tt0137523",
        status="Released",
        tagline="Mischief. Mayhem. Soap.",
    )
    movie.genres.append(sample_genre)
    db_session.add(movie)
    db_session.commit()
    return movie


@pytest.fixture(scope="function")
def sample_movies(db_session, sample_genre):
    """Create multiple sample movies"""
    movies = []
    for i in range(25):
        movie = Movie(
            tmdb_id=1000 + i,
            title=f"Test Movie {i}",
            overview=f"Test overview {i}",
            release_date=datetime.strptime("2024-01-01", "%Y-%m-%d").date(),
            vote_average=7.0 + (i % 3),
            vote_count=100 + i * 10,
            popularity=50.0 + i,
        )
        movie.genres.append(sample_genre)
        movies.append(movie)

    db_session.add_all(movies)
    db_session.commit()
    return movies


@pytest.fixture(scope="function")
def sample_cast(db_session, sample_movie, sample_person):
    """Create a sample cast member"""
    cast = Cast(
        movie_id=sample_movie.id,
        person_id=sample_person.id,
        character_name="Tyler Durden",
        cast_order=0,
    )
    db_session.add(cast)
    db_session.commit()
    return cast


@pytest.fixture(scope="function")
def sample_crew(db_session, sample_movie):
    """Create a sample crew member (director)"""
    director = Person(
        tmdb_id=7467, name="David Fincher", profile_path="/tpEczFclQZeKAiCeKZZ0adRvtfz.jpg"
    )
    db_session.add(director)
    db_session.commit()

    crew = Crew(
        movie_id=sample_movie.id, person_id=director.id, job="Director", department="Directing"
    )
    db_session.add(crew)
    db_session.commit()
    return crew


@pytest.fixture(scope="function")
def sample_production_company(db_session):
    """Create a sample production company"""
    company = ProductionCompany(
        tmdb_id=508,
        name="Regency Enterprises",
        logo_path="/7PzJdsLGlR7oW4J0J5Xcd0pHGRg.png",
        origin_country="US",
    )
    db_session.add(company)
    db_session.commit()
    return company


# ============================================
# NEW FIXTURES FOR AUTHENTICATION TESTING
# ============================================


@pytest.fixture(scope="function")
def sample_user(db_session):
    """Create a sample user for testing"""
    user = User(username="testuser")
    user.set_password("testpassword")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope="function")
def logged_in_user(client, sample_user):
    """Create a logged-in user session"""
    # Login the user using the client
    with client.session_transaction() as sess:
        sess["user_id"] = sample_user.id
    return sample_user


@pytest.fixture(scope="function")
def user_with_favorites(db_session, sample_user, sample_movies):
    """Create a user with some favorited movies"""
    sample_user.favorites.append(sample_movies[0])
    sample_user.favorites.append(sample_movies[1])
    sample_user.favorites.append(sample_movies[2])
    db_session.commit()
    return sample_user


@pytest.fixture(scope="function")
def user_with_watchlist(db_session, sample_user, sample_movies):
    """Create a user with movies in watchlist"""
    sample_user.watchlist.append(sample_movies[3])
    sample_user.watchlist.append(sample_movies[4])
    db_session.commit()
    return sample_user


@pytest.fixture(scope="function")
def multiple_users(db_session):
    """Create multiple users for testing"""
    users = []
    for i in range(3):
        user = User(username=f"user{i}")
        user.set_password(f"password{i}")
        users.append(user)

    db_session.add_all(users)
    db_session.commit()
    return users
