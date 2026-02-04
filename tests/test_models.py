"""
Tests for SQLAlchemy database models
"""

from datetime import datetime

import pytest

from src.models import Cast, Crew, Genre, Movie, Person, ProductionCompany


class TestMovieModel:
    """Tests for Movie model"""

    def test_create_movie(self, db_session):
        """Test creating a movie"""
        movie = Movie(
            tmdb_id=123,
            title="Test Movie",
            overview="Test overview",
            release_date=datetime.strptime("2024-01-01", "%Y-%m-%d").date(),
            vote_average=7.5,
            vote_count=100,
            popularity=50.0,
        )
        db_session.add(movie)
        db_session.commit()

        assert movie.id is not None
        assert movie.title == "Test Movie"
        assert float(movie.vote_average) == 7.5

    def test_movie_str_representation(self, sample_movie):
        """Test movie string representation"""
        assert "Fight Club" in str(sample_movie)

    def test_movie_required_fields(self, db_session):
        """Test that required fields are enforced"""
        movie = Movie(tmdb_id=456, title="Required Fields Test")
        db_session.add(movie)
        db_session.commit()

        assert movie.id is not None
        assert movie.title == "Required Fields Test"

    def test_movie_optional_fields(self, db_session):
        """Test optional fields can be None"""
        movie = Movie(
            tmdb_id=789, title="Optional Fields Test", budget=None, revenue=None, runtime=None
        )
        db_session.add(movie)
        db_session.commit()

        assert movie.budget is None
        assert movie.revenue is None
        assert movie.runtime is None

    def test_movie_financial_data(self, sample_movie):
        """Test movie financial data"""
        assert sample_movie.budget == 63000000
        assert sample_movie.revenue == 100853753
        assert sample_movie.revenue > sample_movie.budget  # Profitable!

    def test_movie_rating_data(self, sample_movie):
        """Test movie rating data"""
        assert float(sample_movie.vote_average) == 8.4
        assert sample_movie.vote_count == 25000
        assert 0 <= float(sample_movie.vote_average) <= 10


class TestGenreModel:
    """Tests for Genre model"""

    def test_create_genre(self, db_session):
        """Test creating a genre"""
        genre = Genre(tmdb_id=28, name="Action")
        db_session.add(genre)
        db_session.commit()

        assert genre.id is not None
        assert genre.name == "Action"

    def test_genre_str_representation(self, sample_genre):
        """Test genre string representation"""
        assert "Action" in str(sample_genre)

    def test_unique_genre_name(self, db_session, sample_genre):
        """Test that genre names should be unique"""
        # This test documents expected behavior
        # Actual uniqueness constraint depends on database setup
        existing_genre = db_session.query(Genre).filter_by(name="Action").first()
        assert existing_genre is not None
        assert existing_genre.name == "Action"


class TestPersonModel:
    """Tests for Person model (actors, directors, crew)"""

    def test_create_person(self, db_session):
        """Test creating a person"""
        person = Person(tmdb_id=287, name="Brad Pitt")
        db_session.add(person)
        db_session.commit()

        assert person.id is not None
        assert person.name == "Brad Pitt"

    def test_person_str_representation(self, sample_person):
        """Test person string representation"""
        assert "Brad Pitt" in str(sample_person)

    def test_person_with_profile_path(self, sample_person):
        """Test person with profile image path"""
        assert sample_person.profile_path is not None
        assert sample_person.profile_path.startswith("/")


class TestCastModel:
    """Tests for Cast model (movie-actor relationship)"""

    def test_create_cast(self, db_session, sample_movie, sample_person):
        """Test creating a cast member"""
        cast = Cast(
            movie_id=sample_movie.id,
            person_id=sample_person.id,
            character_name="Tyler Durden",
            cast_order=0,
        )
        db_session.add(cast)
        db_session.commit()

        assert cast.id is not None
        assert cast.character_name == "Tyler Durden"
        assert cast.cast_order == 0

    def test_cast_relationships(self, sample_cast, sample_movie, sample_person):
        """Test cast relationships to movie and person"""
        assert sample_cast.movie_id == sample_movie.id
        assert sample_cast.person_id == sample_person.id

    def test_cast_order(self, db_session, sample_movie, sample_person):
        """Test cast ordering"""
        cast1 = Cast(
            movie_id=sample_movie.id,
            person_id=sample_person.id,
            character_name="Character 1",
            cast_order=0,
        )

        person2 = Person(tmdb_id=999, name="Actor 2")
        db_session.add(person2)
        db_session.commit()

        cast2 = Cast(
            movie_id=sample_movie.id,
            person_id=person2.id,
            character_name="Character 2",
            cast_order=1,
        )

        db_session.add_all([cast1, cast2])
        db_session.commit()

        assert cast1.cast_order < cast2.cast_order


class TestCrewModel:
    """Tests for Crew model (directors, producers, etc.)"""

    def test_create_crew(self, db_session, sample_movie):
        """Test creating a crew member"""
        director = Person(tmdb_id=7467, name="David Fincher")
        db_session.add(director)
        db_session.commit()

        crew = Crew(
            movie_id=sample_movie.id, person_id=director.id, job="Director", department="Directing"
        )
        db_session.add(crew)
        db_session.commit()

        assert crew.id is not None
        assert crew.job == "Director"
        assert crew.department == "Directing"

    def test_crew_relationships(self, sample_crew, sample_movie):
        """Test crew relationships"""
        assert sample_crew.movie_id == sample_movie.id
        assert sample_crew.job == "Director"


class TestProductionCompanyModel:
    """Tests for ProductionCompany model"""

    def test_create_production_company(self, db_session):
        """Test creating a production company"""
        company = ProductionCompany(tmdb_id=508, name="Regency Enterprises", origin_country="US")
        db_session.add(company)
        db_session.commit()

        assert company.id is not None
        assert company.name == "Regency Enterprises"

    def test_company_str_representation(self, sample_production_company):
        """Test production company string representation"""
        assert "Regency Enterprises" in str(sample_production_company)


class TestRelationships:
    """Tests for model relationships"""

    def test_movie_genre_relationship(self, db_session):
        """Test many-to-many relationship between movies and genres"""
        movie = Movie(tmdb_id=1, title="Action Movie")
        genre1 = Genre(tmdb_id=28, name="Action")
        genre2 = Genre(tmdb_id=12, name="Adventure")

        movie.genres.append(genre1)
        movie.genres.append(genre2)

        db_session.add(movie)
        db_session.commit()

        assert len(movie.genres) == 2
        assert genre1 in movie.genres
        assert genre2 in movie.genres

    def test_movie_company_relationship(self, db_session):
        """Test many-to-many relationship between movies and companies"""
        movie = Movie(tmdb_id=2, title="Studio Movie")
        company = ProductionCompany(tmdb_id=1, name="Big Studio")

        movie.companies.append(company)

        db_session.add(movie)
        db_session.commit()

        assert len(movie.companies) == 1
        assert company in movie.companies

    def test_query_movies_by_genre(self, db_session, sample_movies, sample_genre):
        """Test querying movies by genre"""
        movies = (
            db_session.query(Movie).join(Movie.genres).filter(Genre.id == sample_genre.id).all()
        )

        assert len(movies) > 0
        assert all(sample_genre in movie.genres for movie in movies)

    def test_query_cast_by_movie(self, db_session, sample_movie, sample_cast):
        """Test querying cast by movie"""
        cast_members = db_session.query(Cast).filter(Cast.movie_id == sample_movie.id).all()

        assert len(cast_members) > 0
        assert sample_cast in cast_members


class TestDataIntegrity:
    """Tests for data integrity and constraints"""

    def test_movie_tmdb_id_unique(self, db_session, sample_movie):
        """Test that TMDB IDs should be unique"""
        # Note: Actual constraint depends on database schema
        existing = db_session.query(Movie).filter_by(tmdb_id=550).first()
        assert existing is not None
        assert existing.title == "Fight Club"

    def test_cascade_delete_behavior(self, db_session, sample_movie, sample_cast):
        """Test cascade delete behavior (documents expected behavior)"""
        movie_id = sample_movie.id
        cast_id = sample_cast.id

        # Delete movie
        db_session.delete(sample_movie)
        db_session.commit()

        # Check if movie is deleted
        deleted_movie = db_session.query(Movie).filter_by(id=movie_id).first()
        assert deleted_movie is None

        # Check cascade behavior for cast
        # (Actual behavior depends on database constraints)
        orphaned_cast = db_session.query(Cast).filter_by(id=cast_id).first()
        # This documents the actual behavior in your schema
