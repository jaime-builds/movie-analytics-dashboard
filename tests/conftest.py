"""
Pytest configuration and shared fixtures for movie analytics dashboard tests
"""
import pytest
import os
import sys
from datetime import datetime

# Add parent directory to path so we can import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.app import app as flask_app
from src.models import Base, Session, engine, Movie, Genre, Person, Cast, Crew, ProductionCompany


@pytest.fixture
def app():
    """Create and configure a test Flask application"""
    flask_app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',  # Use in-memory database
        'WTF_CSRF_ENABLED': False  # Disable CSRF for testing
    })
    
    # Create tables
    Base.metadata.create_all(engine)
    
    yield flask_app
    
    # Cleanup
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(app):
    """Create a test client for the Flask application"""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create a test CLI runner"""
    return app.test_cli_runner()


@pytest.fixture
def db_session():
    """Create a test database session with rollback"""
    # Create all tables
    Base.metadata.create_all(engine)
    
    session = Session()
    
    yield session
    
    # Rollback and cleanup
    session.rollback()
    session.close()
    Base.metadata.drop_all(engine)

@pytest.fixture
def sample_genre(db_session):
    """Create a sample genre"""
    genre = Genre(
        tmdb_id=28,
        name="Action"
    )
    db_session.add(genre)
    db_session.commit()
    return genre


@pytest.fixture
def sample_movie(db_session, sample_genre):
    """Create a sample movie with genre"""
    movie = Movie(
        tmdb_id=550,
        title="Fight Club",
        overview="An insomniac office worker and a devil-may-care soap maker form an underground fight club.",
        release_date=datetime.strptime("1999-10-15", "%Y-%m-%d").date(),
        vote_average=8.4,
        vote_count=25000,
        popularity=50.5,
        poster_path="/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
        backdrop_path="/fCayJrkfRaCRCTh8GqN30f8oyQF.jpg",
        budget=63000000,
        revenue=100853753,
        runtime=139
        # Removed: original_language and status (not in your model)
    )
    movie.genres.append(sample_genre)
    db_session.add(movie)
    db_session.commit()
    return movie


@pytest.fixture
def sample_movie(db_session, sample_genre):
    """Create a sample movie with genre"""
    movie = Movie(
        tmdb_id=550,
        title="Fight Club",
        overview="An insomniac office worker and a devil-may-care soap maker form an underground fight club.",
        release_date=datetime.strptime("1999-10-15", "%Y-%m-%d").date(),
        vote_average=8.4,
        vote_count=25000,
        popularity=50.5,
        poster_path="/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
        backdrop_path="/fCayJrkfRaCRCTh8GqN30f8oyQF.jpg",
        budget=63000000,
        revenue=100853753,
        runtime=139,
        #original_language="en",
        #status="Released"
    )
    movie.genres.append(sample_genre)
    db_session.add(movie)
    db_session.commit()
    return movie


@pytest.fixture
def sample_movies(db_session, sample_genre):
    """Create multiple sample movies for testing pagination and filtering"""
    movies = []
    
    # Create 25 movies
    for i in range(25):
        movie = Movie(
            tmdb_id=1000 + i,
            title=f"Test Movie {i+1}",
            overview=f"Overview for test movie {i+1}",
            release_date=datetime.strptime(f"202{i%4}-0{(i%9)+1}-15", "%Y-%m-%d").date(),
            vote_average=5.0 + (i % 5),
            vote_count=100 + (i * 10),
            popularity=10.0 + i,
            poster_path=f"/poster{i}.jpg",
            runtime=90 + (i * 2)
        )
        movie.genres.append(sample_genre)
        movies.append(movie)
        db_session.add(movie)
    
    db_session.commit()
    return movies


@pytest.fixture
def sample_person(db_session):
    """Create a sample person (actor/director)"""
    person = Person(
        tmdb_id=287,
        name="Brad Pitt",
        profile_path="/kU3B75TyRiCgE270EyZnHjfivoq.jpg"
        # Removed: known_for_department (not in your model)
    )
    db_session.add(person)
    db_session.commit()
    return person


@pytest.fixture
def sample_cast(db_session, sample_movie, sample_person):
    """Create a sample cast member"""
    cast = Cast(
        movie_id=sample_movie.id,
        person_id=sample_person.id,
        character="Tyler Durden",
        cast_order=0
    )
    db_session.add(cast)
    db_session.commit()
    return cast


@pytest.fixture
def sample_crew(db_session, sample_movie):
    """Create a sample crew member (director)"""
    director = Person(
        tmdb_id=7467,
        name="David Fincher",
        known_for_department="Directing"
    )
    db_session.add(director)
    db_session.commit()
    
    crew = Crew(
        movie_id=sample_movie.id,
        person_id=director.id,
        job="Director",
        department="Directing"
    )
    db_session.add(crew)
    db_session.commit()
    return crew


@pytest.fixture
def sample_production_company(db_session, sample_movie):
    """Create a sample production company"""
    company = ProductionCompany(
        tmdb_id=508,
        name="Regency Enterprises",
        logo_path="/7PzJdsLGlR7oW4J0J5Xcd0pHGRg.png",
        origin_country="US"
    )
    company.movies.append(sample_movie)
    db_session.add(company)
    db_session.commit()
    return company
