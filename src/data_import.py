from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError

from src.models import Cast, Crew, Genre, Movie, Person, ProductionCompany, Session
from src.tmdb_api import TMDBClient


class DataImporter:
    """Import movie data from TMDB into the database"""

    def __init__(self):
        self.client = TMDBClient()
        self.session = Session()

    def import_genres(self):
        """Import all genres from TMDB"""
        print("Importing genres...")
        genres_data = self.client.get_genres()

        for genre_data in genres_data:
            genre = Genre(tmdb_id=genre_data["id"], name=genre_data["name"])

            try:
                self.session.add(genre)
                self.session.commit()
                print(f"  ✓ Added genre: {genre.name}")
            except IntegrityError:
                self.session.rollback()
                print(f"  - Genre already exists: {genre.name}")

        print(f"Genres import complete!")

    def import_movie(self, tmdb_movie_id: int) -> Optional[Movie]:
        """Import a single movie with all its details"""
        # Check if movie already exists
        existing = self.session.query(Movie).filter_by(tmdb_id=tmdb_movie_id).first()
        if existing:
            print(f"  - Movie already exists: {existing.title}")
            return existing

        # Get movie details
        movie_data = self.client.get_movie_details(tmdb_movie_id)
        if not movie_data or "id" not in movie_data:
            print(f"  ✗ Failed to get details for movie ID {tmdb_movie_id}")
            return None

        # Parse release date
        release_date = None
        if movie_data.get("release_date"):
            try:
                release_date = datetime.strptime(movie_data["release_date"], "%Y-%m-%d").date()
            except ValueError:
                pass

        # Create movie object
        movie = Movie(
            tmdb_id=movie_data["id"],
            title=movie_data.get("title", "Unknown"),
            original_title=movie_data.get("original_title"),
            overview=movie_data.get("overview"),
            release_date=release_date,
            runtime=movie_data.get("runtime"),
            budget=movie_data.get("budget"),
            revenue=movie_data.get("revenue"),
            popularity=movie_data.get("popularity"),
            vote_average=movie_data.get("vote_average"),
            vote_count=movie_data.get("vote_count"),
            poster_path=movie_data.get("poster_path"),
            backdrop_path=movie_data.get("backdrop_path"),
            imdb_id=movie_data.get("imdb_id"),
            status=movie_data.get("status"),
            tagline=movie_data.get("tagline"),
        )

        # Add genres
        for genre_data in movie_data.get("genres", []):
            genre = self.session.query(Genre).filter_by(tmdb_id=genre_data["id"]).first()
            if genre:
                movie.genres.append(genre)

        # Add production companies
        for company_data in movie_data.get("production_companies", []):
            company = (
                self.session.query(ProductionCompany).filter_by(tmdb_id=company_data["id"]).first()
            )

            if not company:
                company = ProductionCompany(
                    tmdb_id=company_data["id"],
                    name=company_data["name"],
                    logo_path=company_data.get("logo_path"),
                    origin_country=company_data.get("origin_country"),
                )
                self.session.add(company)

            movie.companies.append(company)

        try:
            self.session.add(movie)
            self.session.commit()
            print(
                f"  ✓ Added movie: {movie.title} ({movie.release_date.year if movie.release_date else 'N/A'})"
            )

            # Import cast and crew
            self.import_movie_credits(movie)

            return movie
        except IntegrityError as e:
            self.session.rollback()
            print(f"  ✗ Error adding movie: {e}")
            return None

    def import_movie_credits(self, movie: Movie):
        """Import cast and crew for a movie"""
        credits = self.client.get_movie_credits(movie.tmdb_id)

        if not credits:
            return

        # Import cast (top 10 actors)
        for cast_data in credits.get("cast", [])[:10]:
            # Get or create person
            person = self.session.query(Person).filter_by(tmdb_id=cast_data["id"]).first()

            if not person:
                person = Person(
                    tmdb_id=cast_data["id"],
                    name=cast_data["name"],
                    profile_path=cast_data.get("profile_path"),
                    popularity=cast_data.get("popularity"),
                )
                self.session.add(person)
                self.session.flush()  # Get the ID without committing

            # Create cast entry
            cast_entry = Cast(
                movie_id=movie.id,
                person_id=person.id,
                character_name=cast_data.get("character"),
                cast_order=cast_data.get("order"),
            )
            self.session.add(cast_entry)

        # Import key crew (directors, writers, producers)
        key_jobs = ["Director", "Writer", "Screenplay", "Producer", "Executive Producer"]

        for crew_data in credits.get("crew", []):
            if crew_data.get("job") not in key_jobs:
                continue

            # Get or create person
            person = self.session.query(Person).filter_by(tmdb_id=crew_data["id"]).first()

            if not person:
                person = Person(
                    tmdb_id=crew_data["id"],
                    name=crew_data["name"],
                    profile_path=crew_data.get("profile_path"),
                    popularity=crew_data.get("popularity"),
                )
                self.session.add(person)
                self.session.flush()

            # Create crew entry
            crew_entry = Crew(
                movie_id=movie.id,
                person_id=person.id,
                job=crew_data.get("job"),
                department=crew_data.get("department"),
            )
            self.session.add(crew_entry)

        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()

    def import_popular_movies(self, num_pages: int = 5):
        """Import popular movies (20 movies per page)"""
        print(f"\nImporting popular movies ({num_pages} pages)...")

        for page in range(1, num_pages + 1):
            print(f"\nPage {page}/{num_pages}:")
            popular = self.client.get_popular_movies(page=page)

            if not popular or "results" not in popular:
                print(f"Failed to get page {page}")
                continue

            for movie_data in popular["results"]:
                self.import_movie(movie_data["id"])

        print(f"\n✓ Import complete!")

    def close(self):
        """Close database session"""
        self.session.close()


# Main import script
if __name__ == "__main__":
    importer = DataImporter()

    try:
        # First import genres
        importer.import_genres()

        # Then import movies
        importer.import_popular_movies(num_pages=5)  # Import 100 movies

    finally:
        importer.close()
