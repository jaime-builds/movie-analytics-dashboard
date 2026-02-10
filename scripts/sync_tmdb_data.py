"""
TMDB Data Synchronization Script

This script fetches and updates movie data from TMDB API.
Can be run manually or scheduled via cron/scheduler.

Usage:
    python scripts/sync_tmdb_data.py [--limit 5000] [--update-existing]
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import requests

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError

from config.config import Config
from src.models import (
    Cast,
    Crew,
    Genre,
    Movie,
    Person,
    ProductionCompany,
    Session,
    movie_genres_table,
)
from src.tmdb_api import TMDBClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/tmdb_sync.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class TMDBDataSyncer:
    """Handles synchronization of movie data from TMDB"""

    def __init__(self, limit: int = 5000, update_existing: bool = False):
        self.client = TMDBClient()
        self.session = Session()
        self.limit = limit
        self.update_existing = update_existing
        self.stats = {"movies_added": 0, "movies_updated": 0, "movies_skipped": 0, "errors": 0}

    def sync_genres(self) -> None:
        """Sync genre list from TMDB"""
        logger.info("Syncing genres...")

        try:
            # Check if get_genres method exists
            if not hasattr(self.client, "get_genres"):
                logger.warning("TMDBClient doesn't have get_genres method. Using manual API call.")
                import requests

                response = requests.get(
                    f"{self.client.base_url}/genre/movie/list",
                    params={"api_key": self.client.api_key},
                )
                response.raise_for_status()
                genres_data = response.json()
            else:
                genres_data = self.client.get_genres()

            # Handle both dict with 'genres' key and direct list
            if isinstance(genres_data, dict):
                genre_list = genres_data.get("genres", [])
            elif isinstance(genres_data, list):
                genre_list = genres_data
            else:
                logger.error(f"Unexpected genres_data type: {type(genres_data)}")
                logger.error(f"Data: {genres_data}")
                return

            if not genre_list:
                logger.warning("No genres returned from API")
                return

            for genre_data in genre_list:
                genre = self.session.query(Genre).filter_by(tmdb_id=genre_data["id"]).first()

                if not genre:
                    genre = Genre(tmdb_id=genre_data["id"], name=genre_data["name"])
                    self.session.add(genre)
                    logger.debug(f"Added genre: {genre_data['name']}")
                else:
                    genre.name = genre_data["name"]
                    logger.debug(f"Updated genre: {genre_data['name']}")

            self.session.commit()
            logger.info(f"Synced {len(genre_list)} genres")

        except Exception as e:
            logger.error(f"Error syncing genres: {e}", exc_info=True)
            self.session.rollback()
            raise

    def get_person_or_create(
        self, person_id: int, name: str, profile_path: str = None
    ) -> Optional[Person]:
        """Get or create a person by TMDB ID"""
        try:
            person = self.session.query(Person).filter_by(tmdb_id=person_id).first()

            if not person:
                person = Person(tmdb_id=person_id, name=name, profile_path=profile_path)
                self.session.add(person)
                self.session.flush()  # Get the ID without committing
                logger.debug(f"Created person: {name}")
            elif profile_path and not person.profile_path:
                # Update profile path if we got one and don't have one yet
                person.profile_path = profile_path
                logger.debug(f"Updated profile for: {name}")

            return person

        except Exception as e:
            logger.error(f"Error creating person {name}: {e}")
            return None

    def sync_movie(self, movie_data: dict) -> bool:
        """Sync a single movie with full details"""
        tmdb_id = movie_data.get("id")

        try:
            # Check if movie exists
            existing_movie = self.session.query(Movie).filter_by(tmdb_id=tmdb_id).first()

            if existing_movie and not self.update_existing:
                self.stats["movies_skipped"] += 1
                logger.debug(f"Skipping existing movie: {movie_data.get('title')}")
                return False

            # Add small delay to avoid rate limiting (TMDB allows 40 req/10sec)
            time.sleep(0.25)

            # Fetch detailed movie data
            details = self.client.get_movie_details(tmdb_id)
            credits = self.client.get_movie_credits(tmdb_id)

            # Create or update movie
            if existing_movie:
                movie = existing_movie
                is_new = False
            else:
                movie = Movie()
                is_new = True

            # Parse release date string to date object
            release_date_str = details.get("release_date")
            release_date = None
            if release_date_str:
                try:
                    release_date = datetime.strptime(release_date_str, "%Y-%m-%d").date()
                except ValueError:
                    logger.warning(f"Invalid date format for movie {tmdb_id}: {release_date_str}")

            # Update movie fields
            movie.tmdb_id = tmdb_id
            movie.title = details.get("title", "")
            movie.overview = details.get("overview", "")
            movie.release_date = release_date
            movie.runtime = details.get("runtime")
            movie.budget = details.get("budget", 0)
            movie.revenue = details.get("revenue", 0)
            movie.popularity = details.get("popularity", 0.0)
            movie.vote_average = details.get("vote_average", 0.0)
            movie.vote_count = details.get("vote_count", 0)
            movie.poster_path = details.get("poster_path")
            movie.backdrop_path = details.get("backdrop_path")
            movie.original_language = details.get("original_language", "en")
            movie.status = details.get("status", "Released")

            if is_new:
                self.session.add(movie)
                self.session.flush()  # Get movie ID

            # Sync genres
            if is_new or self.update_existing:
                # Clear existing genres if updating
                if not is_new:
                    self.session.execute(
                        movie_genres_table.delete().where(movie_genres_table.c.movie_id == movie.id)
                    )

                for genre_data in details.get("genres", []):
                    genre = self.session.query(Genre).filter_by(tmdb_id=genre_data["id"]).first()
                    if genre:
                        movie.genres.append(genre)

            # Sync production companies (skip if relationship doesn't exist)
            if hasattr(movie, "companies") and (is_new or self.update_existing):
                try:
                    for company_data in details.get("production_companies", [])[:3]:
                        company = (
                            self.session.query(ProductionCompany)
                            .filter_by(tmdb_id=company_data["id"])
                            .first()
                        )

                        if not company:
                            company = ProductionCompany(
                                tmdb_id=company_data["id"],
                                name=company_data["name"],
                                logo_path=company_data.get("logo_path"),
                                origin_country=company_data.get("origin_country"),
                            )
                            self.session.add(company)
                            self.session.flush()

                        if company not in movie.companies:
                            movie.companies.append(company)
                except Exception as e:
                    logger.warning(f"Could not sync production companies: {e}")

            # Sync cast (top 10) - skip if Cast model incomplete
            if is_new or self.update_existing:
                try:
                    # Clear existing cast if updating
                    if not is_new:
                        for cast_member in (
                            self.session.query(Cast).filter_by(movie_id=movie.id).all()
                        ):
                            self.session.delete(cast_member)

                    for cast_data in credits.get("cast", [])[:10]:
                        person = self.get_person_or_create(
                            cast_data["id"],
                            cast_data["name"],
                            cast_data.get("profile_path"),  # Add profile image
                        )

                        if person:
                            cast = Cast(
                                movie_id=movie.id,
                                person_id=person.id,
                                cast_order=cast_data.get("order", 0),
                            )
                            self.session.add(cast)
                except Exception as e:
                    logger.warning(f"Could not sync cast for movie {tmdb_id}: {e}")

            # Sync crew (directors, writers, producers)
            if is_new or self.update_existing:
                try:
                    # Clear existing crew if updating
                    if not is_new:
                        for crew_member in (
                            self.session.query(Crew).filter_by(movie_id=movie.id).all()
                        ):
                            self.session.delete(crew_member)

                    relevant_jobs = ["Director", "Writer", "Screenplay", "Producer"]
                    for crew_data in credits.get("crew", []):
                        if crew_data["job"] in relevant_jobs:
                            person = self.get_person_or_create(
                                crew_data["id"],
                                crew_data["name"],
                                crew_data.get("profile_path"),  # Add profile image
                            )

                            if person:
                                crew = Crew(
                                    movie_id=movie.id,
                                    person_id=person.id,
                                    job=crew_data["job"],
                                    department=crew_data.get("department", ""),
                                )
                                self.session.add(crew)
                except Exception as e:
                    logger.warning(f"Could not sync crew for movie {tmdb_id}: {e}")

            self.session.commit()

            if is_new:
                self.stats["movies_added"] += 1
                logger.info(f"Added movie: {movie.title} ({movie.release_date})")
            else:
                self.stats["movies_updated"] += 1
                logger.info(f"Updated movie: {movie.title}")

            return True

        except Exception as e:
            logger.error(f"Error syncing movie {tmdb_id}: {e}")
            self.session.rollback()
            self.stats["errors"] += 1
            return False

    def sync_popular_movies(self) -> None:
        """Sync popular movies from TMDB"""
        logger.info(f"Starting sync of {self.limit} popular movies...")

        page = 1
        movies_synced = 0

        while movies_synced < self.limit:
            try:
                logger.info(f"Fetching page {page}...")
                data = self.client.get_popular_movies(page=page)
                movies = data.get("results", [])

                if not movies:
                    logger.info("No more movies to fetch")
                    break

                for movie_data in movies:
                    if movies_synced >= self.limit:
                        break

                    if self.sync_movie(movie_data):
                        movies_synced += 1

                    # Progress update every 100 movies
                    if movies_synced % 100 == 0:
                        logger.info(f"Progress: {movies_synced}/{self.limit} movies synced")

                page += 1

            except Exception as e:
                logger.error(f"Error fetching page {page}: {e}")
                page += 1
                continue

        logger.info(f"Sync completed: {self.stats}")

    def sync_recent_updates(self, days: int = 7) -> None:
        """Sync movies that were updated recently on TMDB"""
        logger.info(f"Syncing movies updated in the last {days} days...")

        # Get movies from database that were added/updated recently
        cutoff_date = datetime.now() - timedelta(days=days)

        recent_movies = self.session.query(Movie).filter(Movie.created_at >= cutoff_date).all()

        logger.info(f"Updating {len(recent_movies)} recent movies...")

        for movie in recent_movies:
            try:
                details = self.client.get_movie_details(movie.tmdb_id)

                # Update key fields
                movie.popularity = details.get("popularity", movie.popularity)
                movie.vote_average = details.get("vote_average", movie.vote_average)
                movie.vote_count = details.get("vote_count", movie.vote_count)
                movie.revenue = details.get("revenue", movie.revenue)

                self.session.commit()
                self.stats["movies_updated"] += 1

            except Exception as e:
                logger.error(f"Error updating movie {movie.title}: {e}")
                self.session.rollback()
                continue

        logger.info(f"Updated {self.stats['movies_updated']} recent movies")

    def close(self):
        """Close database session"""
        self.session.close()


def main():
    """Main entry point for the sync script"""
    parser = argparse.ArgumentParser(description="Sync movie data from TMDB")
    parser.add_argument(
        "--limit", type=int, default=5000, help="Number of movies to sync (default: 5000)"
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Update existing movies instead of skipping them",
    )
    parser.add_argument(
        "--recent-only", action="store_true", help="Only update recently added movies"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="When using --recent-only, update movies from last N days (default: 7)",
    )

    args = parser.parse_args()

    syncer = TMDBDataSyncer(limit=args.limit, update_existing=args.update_existing)

    try:
        # Always sync genres first
        syncer.sync_genres()

        if args.recent_only:
            # Only update recent movies
            syncer.sync_recent_updates(days=args.days)
        else:
            # Full sync of popular movies
            syncer.sync_popular_movies()

        logger.info("=" * 60)
        logger.info("SYNC STATISTICS:")
        logger.info(f"  Movies added:   {syncer.stats['movies_added']}")
        logger.info(f"  Movies updated: {syncer.stats['movies_updated']}")
        logger.info(f"  Movies skipped: {syncer.stats['movies_skipped']}")
        logger.info(f"  Errors:         {syncer.stats['errors']}")
        logger.info("=" * 60)

    except KeyboardInterrupt:
        logger.info("Sync interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error during sync: {e}")
        sys.exit(1)
    finally:
        syncer.close()


if __name__ == "__main__":
    main()
