"""
Tests for src/data_import.py

Focuses on logic that can be tested without hitting the TMDB API:
- Date parsing in import_movie
- Duplicate movie handling
- Cast capping at 10
- Crew key_jobs filtering
- Genre duplicate handling
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.data_import import DataImporter
from src.models import Base, Cast, Crew, Genre, Movie, Person


@pytest.fixture
def importer(db_session):
    """Create a DataImporter with a mocked TMDB client and test DB session."""
    with patch("src.data_import.TMDBClient"), patch("src.data_import.Session") as mock_session:
        mock_session.return_value = db_session
        imp = DataImporter()
        imp.session = db_session
        imp.client = MagicMock()
        yield imp


def make_movie_data(**overrides):
    """Return a minimal valid TMDB movie data dict."""
    data = {
        "id": 12345,
        "title": "Test Import Film",
        "original_title": "Test Import Film",
        "overview": "A film for testing imports.",
        "release_date": "2005-07-15",
        "runtime": 120,
        "budget": 10000000,
        "revenue": 50000000,
        "popularity": 25.0,
        "vote_average": 7.2,
        "vote_count": 500,
        "poster_path": "/poster.jpg",
        "backdrop_path": "/backdrop.jpg",
        "imdb_id": "tt0000001",
        "status": "Released",
        "tagline": "A tagline.",
        "genres": [],
        "production_companies": [],
    }
    data.update(overrides)
    return data


# ============================================
# Date parsing
# ============================================


class TestDateParsing:
    """Test release date parsing logic in import_movie."""

    def test_valid_date_parsed_correctly(self, importer, db_session):
        importer.client.get_movie_details.return_value = make_movie_data(release_date="1999-10-15")
        importer.client.get_movie_credits.return_value = {"cast": [], "crew": []}

        movie = importer.import_movie(12345)

        assert movie is not None
        assert movie.release_date == date(1999, 10, 15)

    def test_missing_release_date_handled(self, importer, db_session):
        importer.client.get_movie_details.return_value = make_movie_data(release_date="")
        importer.client.get_movie_credits.return_value = {"cast": [], "crew": []}

        movie = importer.import_movie(12345)

        assert movie is not None
        assert movie.release_date is None

    def test_malformed_release_date_handled(self, importer, db_session):
        importer.client.get_movie_details.return_value = make_movie_data(release_date="not-a-date")
        importer.client.get_movie_credits.return_value = {"cast": [], "crew": []}

        movie = importer.import_movie(12345)

        assert movie is not None
        assert movie.release_date is None

    def test_none_release_date_handled(self, importer, db_session):
        data = make_movie_data()
        data["release_date"] = None
        importer.client.get_movie_details.return_value = data
        importer.client.get_movie_credits.return_value = {"cast": [], "crew": []}

        movie = importer.import_movie(12345)

        assert movie is not None
        assert movie.release_date is None


# ============================================
# Duplicate handling
# ============================================


class TestDuplicateHandling:
    """Test that import_movie skips already-imported movies."""

    def test_skips_existing_movie(self, importer, db_session):
        existing = Movie(
            tmdb_id=12345,
            title="Already Imported",
            overview="Exists",
            vote_average=7.0,
            vote_count=100,
            popularity=10.0,
        )
        db_session.add(existing)
        db_session.commit()

        result = importer.import_movie(12345)

        assert result is not None
        assert result.title == "Already Imported"
        # TMDB API should not have been called
        importer.client.get_movie_details.assert_not_called()

    def test_returns_none_when_api_returns_no_data(self, importer):
        importer.client.get_movie_details.return_value = {}

        result = importer.import_movie(99999)

        assert result is None

    def test_returns_none_when_api_returns_none(self, importer):
        importer.client.get_movie_details.return_value = None

        result = importer.import_movie(99999)

        assert result is None


# ============================================
# Movie field mapping
# ============================================


class TestMovieFieldMapping:
    """Test that movie fields are mapped correctly from TMDB data."""

    def test_movie_fields_mapped_correctly(self, importer, db_session):
        importer.client.get_movie_details.return_value = make_movie_data()
        importer.client.get_movie_credits.return_value = {"cast": [], "crew": []}

        movie = importer.import_movie(12345)

        assert movie.tmdb_id == 12345
        assert movie.title == "Test Import Film"
        assert movie.runtime == 120
        assert movie.budget == 10000000
        assert movie.revenue == 50000000
        assert movie.status == "Released"
        assert movie.imdb_id == "tt0000001"

    def test_missing_optional_fields_default_to_none(self, importer, db_session):
        data = make_movie_data()
        del data["tagline"]
        del data["backdrop_path"]
        importer.client.get_movie_details.return_value = data
        importer.client.get_movie_credits.return_value = {"cast": [], "crew": []}

        movie = importer.import_movie(12345)

        assert movie is not None
        assert movie.tagline is None
        assert movie.backdrop_path is None


# ============================================
# Cast import
# ============================================


class TestCastImport:
    """Test cast import logic."""

    def test_cast_capped_at_10(self, importer, db_session):
        cast_data = [
            {
                "id": 1000 + i,
                "name": f"Actor {i}",
                "character": f"Character {i}",
                "order": i,
                "profile_path": None,
                "popularity": 10.0,
            }
            for i in range(15)  # 15 cast members
        ]
        importer.client.get_movie_details.return_value = make_movie_data()
        importer.client.get_movie_credits.return_value = {"cast": cast_data, "crew": []}

        movie = importer.import_movie(12345)

        cast_count = db_session.query(Cast).filter_by(movie_id=movie.id).count()
        assert cast_count == 10

    def test_cast_creates_people(self, importer, db_session):
        cast_data = [
            {
                "id": 5001,
                "name": "Famous Actor",
                "character": "Hero",
                "order": 0,
                "profile_path": "/actor.jpg",
                "popularity": 50.0,
            }
        ]
        importer.client.get_movie_details.return_value = make_movie_data()
        importer.client.get_movie_credits.return_value = {"cast": cast_data, "crew": []}

        importer.import_movie(12345)

        person = db_session.query(Person).filter_by(tmdb_id=5001).first()
        assert person is not None
        assert person.name == "Famous Actor"

    def test_cast_reuses_existing_person(self, importer, db_session):
        existing_person = Person(tmdb_id=5001, name="Existing Actor")
        db_session.add(existing_person)
        db_session.commit()

        cast_data = [
            {
                "id": 5001,
                "name": "Existing Actor",
                "character": "Villain",
                "order": 0,
                "profile_path": None,
                "popularity": 20.0,
            }
        ]
        importer.client.get_movie_details.return_value = make_movie_data()
        importer.client.get_movie_credits.return_value = {"cast": cast_data, "crew": []}

        importer.import_movie(12345)

        person_count = db_session.query(Person).filter_by(tmdb_id=5001).count()
        assert person_count == 1  # No duplicate created


# ============================================
# Crew import
# ============================================


class TestCrewImport:
    """Test crew key_jobs filtering."""

    def test_only_key_jobs_imported(self, importer, db_session):
        crew_data = [
            {
                "id": 6001,
                "name": "Jane Director",
                "job": "Director",
                "department": "Directing",
                "profile_path": None,
                "popularity": 15.0,
            },
            {
                "id": 6002,
                "name": "Bob Grip",
                "job": "Key Grip",
                "department": "Camera",
                "profile_path": None,
                "popularity": 5.0,
            },
            {
                "id": 6003,
                "name": "Alice Writer",
                "job": "Writer",
                "department": "Writing",
                "profile_path": None,
                "popularity": 10.0,
            },
        ]
        importer.client.get_movie_details.return_value = make_movie_data()
        importer.client.get_movie_credits.return_value = {"cast": [], "crew": crew_data}

        movie = importer.import_movie(12345)

        crew_entries = db_session.query(Crew).filter_by(movie_id=movie.id).all()
        jobs = {c.job for c in crew_entries}
        assert "Director" in jobs
        assert "Writer" in jobs
        assert "Key Grip" not in jobs
        assert len(crew_entries) == 2

    def test_director_person_created(self, importer, db_session):
        crew_data = [
            {
                "id": 7001,
                "name": "Great Director",
                "job": "Director",
                "department": "Directing",
                "profile_path": None,
                "popularity": 30.0,
            },
        ]
        importer.client.get_movie_details.return_value = make_movie_data()
        importer.client.get_movie_credits.return_value = {"cast": [], "crew": crew_data}

        importer.import_movie(12345)

        person = db_session.query(Person).filter_by(tmdb_id=7001).first()
        assert person is not None
        assert person.name == "Great Director"


# ============================================
# Genre import
# ============================================


class TestGenreImport:
    """Test import_genres duplicate handling."""

    def test_imports_new_genres(self, importer, db_session):
        importer.client.get_genres.return_value = [
            {"id": 28, "name": "Action"},
            {"id": 35, "name": "Comedy"},
        ]

        importer.import_genres()

        genres = db_session.query(Genre).all()
        names = {g.name for g in genres}
        assert "Action" in names
        assert "Comedy" in names

    def test_skips_duplicate_genres(self, importer, db_session):
        existing = Genre(tmdb_id=28, name="Action")
        db_session.add(existing)
        db_session.commit()

        importer.client.get_genres.return_value = [
            {"id": 28, "name": "Action"},
        ]

        # Should not raise -- the rollback path is exercised and execution continues
        try:
            importer.import_genres()
        except Exception as e:
            pytest.fail(f"import_genres raised unexpectedly: {e}")
