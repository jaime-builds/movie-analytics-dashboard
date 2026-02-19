"""
FAST TMDB Data Synchronization Script

Optimized version with:
- Reduced API delay (0.1s instead of 0.25s)
- Batch commits (every 50 movies)
- Progress updates

Usage:
    python scripts/sync_tmdb_data_fast.py --limit 20000
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/tmdb_sync_fast.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class FastTMDBSyncer:
    """Optimized TMDB data syncer"""

    def __init__(self, limit: int = 5000, update_existing: bool = False):
        self.client = TMDBClient()
        self.session = Session()
        self.limit = limit
        self.update_existing = update_existing
        self.stats = {"movies_added": 0, "movies_updated": 0, "movies_skipped": 0, "errors": 0}
        self.batch_size = 50  # Commit every 50 movies

    def sync_genres(self):
        """Sync genres (unchanged)"""
        logger.info("Syncing genres...")
        try:
            import requests

            response = requests.get(
                f"{self.client.base_url}/genre/movie/list",
                params={"api_key": self.client.api_key},
            )
            response.raise_for_status()
            genres_data = response.json()

            genre_list = genres_data.get("genres", [])

            for genre_data in genre_list:
                genre = self.session.query(Genre).filter_by(tmdb_id=genre_data["id"]).first()
                if not genre:
                    genre = Genre(tmdb_id=genre_data["id"], name=genre_data["name"])
                    self.session.add(genre)
                else:
                    genre.name = genre_data["name"]

            self.session.commit()
            logger.info(f"Synced {len(genre_list)} genres")
        except Exception as e:
            logger.error(f"Error syncing genres: {e}")
            self.session.rollback()
            raise

    def get_person_or_create(self, person_id: int, name: str, profile_path: str = None):
        """Get or create person"""
        person = self.session.query(Person).filter_by(tmdb_id=person_id).first()
        if not person:
            person = Person(tmdb_id=person_id, name=name, profile_path=profile_path)
            self.session.add(person)
            self.session.flush()
        elif profile_path and not person.profile_path:
            person.profile_path = profile_path
        return person

    def sync_movie(self, movie_data: dict) -> bool:
        """Sync single movie (optimized)"""
        tmdb_id = movie_data.get("id")

        try:
            existing_movie = self.session.query(Movie).filter_by(tmdb_id=tmdb_id).first()

            if existing_movie and not self.update_existing:
                self.stats["movies_skipped"] += 1
                return False

            # OPTIMIZED: Reduced delay from 0.25s to 0.1s
            time.sleep(0.1)  # 10 req/sec (TMDB allows 40/10sec)

            details = self.client.get_movie_details(tmdb_id)
            credits = self.client.get_movie_credits(tmdb_id)

            if existing_movie:
                movie = existing_movie
                is_new = False
            else:
                movie = Movie()
                is_new = True

            # Parse release date
            release_date = None
            if details.get("release_date"):
                try:
                    release_date = datetime.strptime(details["release_date"], "%Y-%m-%d").date()
                except ValueError:
                    pass

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
            movie.status = details.get("status", "Released")

            if is_new:
                self.session.add(movie)
                self.session.flush()

            # Sync genres
            if is_new or self.update_existing:
                if not is_new:
                    self.session.execute(
                        movie_genres_table.delete().where(movie_genres_table.c.movie_id == movie.id)
                    )
                for genre_data in details.get("genres", []):
                    genre = self.session.query(Genre).filter_by(tmdb_id=genre_data["id"]).first()
                    if genre:
                        movie.genres.append(genre)

            # Sync cast (top 10)
            if is_new or self.update_existing:
                if not is_new:
                    for cast_member in self.session.query(Cast).filter_by(movie_id=movie.id).all():
                        self.session.delete(cast_member)

                for cast_data in credits.get("cast", [])[:10]:
                    person = self.get_person_or_create(
                        cast_data["id"], cast_data["name"], cast_data.get("profile_path")
                    )
                    if person:
                        cast = Cast(
                            movie_id=movie.id,
                            person_id=person.id,
                            character_name=cast_data.get("character", "Unknown"),
                            cast_order=cast_data.get("order", 0),
                        )
                        self.session.add(cast)

            # Sync crew (directors only for speed)
            if is_new or self.update_existing:
                if not is_new:
                    for crew_member in self.session.query(Crew).filter_by(movie_id=movie.id).all():
                        self.session.delete(crew_member)

                for crew_data in credits.get("crew", []):
                    if crew_data["job"] == "Director":  # Only directors for speed
                        person = self.get_person_or_create(
                            crew_data["id"], crew_data["name"], crew_data.get("profile_path")
                        )
                        if person:
                            crew = Crew(
                                movie_id=movie.id,
                                person_id=person.id,
                                job=crew_data["job"],
                                department=crew_data.get("department", ""),
                            )
                            self.session.add(crew)

            # Don't commit here - batch commits instead
            if is_new:
                self.stats["movies_added"] += 1
            else:
                self.stats["movies_updated"] += 1

            return True

        except Exception as e:
            logger.error(f"Error syncing movie {tmdb_id}: {e}")
            self.stats["errors"] += 1
            return False

    def sync_popular_movies(self):
        """Sync popular movies with batch commits"""
        logger.info(f"FAST SYNC: Starting import of {self.limit} movies...")
        logger.info(f"Optimizations: 0.1s delay, batch commits every {self.batch_size} movies")

        start_time = time.time()
        page = 1
        movies_synced = 0

        while movies_synced < self.limit:
            try:
                data = self.client.get_popular_movies(page=page)
                movies = data.get("results", [])

                if not movies:
                    break

                for movie_data in movies:
                    if movies_synced >= self.limit:
                        break

                    if self.sync_movie(movie_data):
                        movies_synced += 1

                    # OPTIMIZED: Batch commit every N movies
                    if movies_synced % self.batch_size == 0:
                        self.session.commit()
                        elapsed = time.time() - start_time
                        rate = movies_synced / elapsed
                        eta = (self.limit - movies_synced) / rate / 60
                        logger.info(
                            f"Progress: {movies_synced}/{self.limit} "
                            f"({movies_synced/self.limit*100:.1f}%) | "
                            f"Rate: {rate:.1f} movies/sec | "
                            f"ETA: {eta:.1f} min"
                        )

                page += 1

            except Exception as e:
                logger.error(f"Error on page {page}: {e}")
                self.session.rollback()
                page += 1
                continue

        # Final commit
        self.session.commit()

        elapsed = time.time() - start_time
        logger.info(f"\n{'='*60}")
        logger.info(f"FAST SYNC COMPLETE!")
        logger.info(f"{'='*60}")
        logger.info(f"  Total time: {elapsed/60:.1f} minutes")
        logger.info(f"  Movies added: {self.stats['movies_added']}")
        logger.info(f"  Movies updated: {self.stats['movies_updated']}")
        logger.info(f"  Movies skipped: {self.stats['movies_skipped']}")
        logger.info(f"  Errors: {self.stats['errors']}")
        logger.info(f"  Average rate: {movies_synced/elapsed:.1f} movies/sec")
        logger.info(f"{'='*60}\n")

    def close(self):
        self.session.close()


def main():
    parser = argparse.ArgumentParser(description="Fast TMDB sync")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--update-existing", action="store_true")
    args = parser.parse_args()

    syncer = FastTMDBSyncer(limit=args.limit, update_existing=args.update_existing)

    try:
        syncer.sync_genres()
        syncer.sync_popular_movies()
    except KeyboardInterrupt:
        logger.info("Sync interrupted")
        syncer.session.commit()  # Save progress
    finally:
        syncer.close()


if __name__ == "__main__":
    main()
