"""
TMDB Data Synchronization Script

Uses ThreadPoolExecutor to fetch movie details and credits in parallel,
dramatically reducing sync time compared to sequential fetching.

At 10 workers: ~5,000 movies in ~5-6 minutes (vs 45+ minutes sequential).

Usage:
    python scripts/sync_tmdb_data.py --limit 5000
    python scripts/sync_tmdb_data.py --limit 5000 --update-existing
    python scripts/sync_tmdb_data.py --limit 1000 --workers 20
"""

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
    movie_companies_table,
    movie_genres_table,
)
from src.tmdb_api import TMDBClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/tmdb_sync_fast.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def fetch_movie_data(tmdb_id: int, client: TMDBClient) -> dict | None:
    """Fetch details + credits for a single movie. Runs in a thread."""
    try:
        details = client.get_movie_details(tmdb_id)
        credits = client.get_movie_credits(tmdb_id)
        return {"tmdb_id": tmdb_id, "details": details, "credits": credits}
    except Exception as e:
        logger.warning(f"Failed to fetch tmdb_id={tmdb_id}: {e}")
        return None


class FastTMDBSyncer:
    def __init__(self, limit: int = 5000, update_existing: bool = False, workers: int = 10):
        self.client = TMDBClient()
        self.session = Session()
        self.limit = limit
        self.update_existing = update_existing
        self.workers = workers
        self.batch_size = 50
        self.stats = {"movies_added": 0, "movies_updated": 0, "movies_skipped": 0, "errors": 0}

    def sync_genres(self):
        """Sync all genres from TMDB."""
        logger.info("Syncing genres...")
        try:
            import requests

            response = requests.get(
                f"{self.client.base_url}/genre/movie/list",
                params={"api_key": self.client.api_key},
            )
            response.raise_for_status()
            genre_list = response.json().get("genres", [])

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
        """Get or create a Person row. Called only from the write thread."""
        person = self.session.query(Person).filter_by(tmdb_id=person_id).first()
        if not person:
            person = Person(tmdb_id=person_id, name=name, profile_path=profile_path)
            self.session.add(person)
            self.session.flush()
        elif profile_path and not person.profile_path:
            person.profile_path = profile_path
        return person

    def write_movie(self, fetched: dict) -> bool:
        """Write a single fetched movie to the DB. Always runs single-threaded."""
        tmdb_id = fetched["tmdb_id"]
        details = fetched["details"]
        credits = fetched["credits"]

        try:
            existing = self.session.query(Movie).filter_by(tmdb_id=tmdb_id).first()

            if existing and not self.update_existing:
                self.stats["movies_skipped"] += 1
                return False

            is_new = existing is None
            movie = existing or Movie()

            release_date = None
            if details.get("release_date"):
                try:
                    release_date = datetime.strptime(details["release_date"], "%Y-%m-%d").date()
                except ValueError:
                    pass

            movie.tmdb_id = tmdb_id
            movie.title = details.get("title", "")
            movie.original_title = details.get("original_title", "")
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
            movie.imdb_id = details.get("imdb_id")
            movie.status = details.get("status", "Released")
            movie.tagline = details.get("tagline", "")

            if is_new:
                self.session.add(movie)
                self.session.flush()

            if is_new or self.update_existing:
                # Genres
                self.session.execute(
                    movie_genres_table.delete().where(movie_genres_table.c.movie_id == movie.id)
                )
                self.session.flush()
                with self.session.no_autoflush:
                    for g in details.get("genres", []):
                        genre = self.session.query(Genre).filter_by(tmdb_id=g["id"]).first()
                        if genre and genre not in movie.genres:
                            movie.genres.append(genre)

                # Production companies
                self.session.execute(
                    movie_companies_table.delete().where(
                        movie_companies_table.c.movie_id == movie.id
                    )
                )
                self.session.flush()
                with self.session.no_autoflush:
                    for c in details.get("production_companies", []):
                        company = (
                            self.session.query(ProductionCompany).filter_by(tmdb_id=c["id"]).first()
                        )
                        if not company:
                            company = ProductionCompany(
                                tmdb_id=c["id"],
                                name=c.get("name", ""),
                                logo_path=c.get("logo_path"),
                                origin_country=c.get("origin_country", ""),
                            )
                            self.session.add(company)
                            self.session.flush()
                        if company not in movie.companies:
                            movie.companies.append(company)

                # Cast (top 10)
                for cm in self.session.query(Cast).filter_by(movie_id=movie.id).all():
                    self.session.delete(cm)
                for cast_data in credits.get("cast", [])[:10]:
                    person = self.get_person_or_create(
                        cast_data["id"], cast_data["name"], cast_data.get("profile_path")
                    )
                    self.session.add(
                        Cast(
                            movie_id=movie.id,
                            person_id=person.id,
                            character_name=cast_data.get("character", "Unknown"),
                            cast_order=cast_data.get("order", 0),
                        )
                    )

                # Crew (directors only)
                for cm in self.session.query(Crew).filter_by(movie_id=movie.id).all():
                    self.session.delete(cm)
                for crew_data in credits.get("crew", []):
                    if crew_data["job"] == "Director":
                        person = self.get_person_or_create(
                            crew_data["id"], crew_data["name"], crew_data.get("profile_path")
                        )
                        self.session.add(
                            Crew(
                                movie_id=movie.id,
                                person_id=person.id,
                                job=crew_data["job"],
                                department=crew_data.get("department", ""),
                            )
                        )

            if is_new:
                self.stats["movies_added"] += 1
            else:
                self.stats["movies_updated"] += 1

            return True

        except Exception as e:
            logger.error(f"Error writing movie tmdb_id={tmdb_id}: {e}")
            self.stats["errors"] += 1
            self.session.rollback()
            return False

    def sync_popular_movies(self):
        """
        Fetch movie list pages sequentially, then fetch details+credits
        for each batch in parallel, then write to DB single-threaded.

        Pattern:
          [page fetch] → [parallel API fetch N movies] → [sequential DB write]
        """
        logger.info(f"Starting sync: {self.limit} movies, {self.workers} parallel workers")
        start_time = time.time()

        # ── Step 1: collect all tmdb_ids we need ──────────────────────────
        tmdb_ids = []
        page = 1
        logger.info("Collecting movie IDs from popular pages...")

        while len(tmdb_ids) < self.limit:
            try:
                data = self.client.get_popular_movies(page=page)
                results = data.get("results", [])
                if not results:
                    break

                for movie_data in results:
                    if len(tmdb_ids) >= self.limit:
                        break
                    # Skip movies we already have if not updating
                    if not self.update_existing:
                        existing = (
                            self.session.query(Movie).filter_by(tmdb_id=movie_data["id"]).first()
                        )
                        if existing:
                            self.stats["movies_skipped"] += 1
                            continue
                    tmdb_ids.append(movie_data["id"])

                page += 1
            except Exception as e:
                logger.error(f"Error fetching page {page}: {e}")
                page += 1

        logger.info(f"Collected {len(tmdb_ids)} movie IDs to sync")

        if not tmdb_ids:
            logger.info("Nothing to sync.")
            return

        # ── Step 2: fetch details + credits in parallel ───────────────────
        # Process in batches so we can write incrementally and show progress
        movies_written = 0
        batch_size = self.workers * 5  # fetch ahead 5x the worker count

        for batch_start in range(0, len(tmdb_ids), batch_size):
            batch_ids = tmdb_ids[batch_start : batch_start + batch_size]
            fetched_batch = []

            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {
                    executor.submit(fetch_movie_data, tid, self.client): tid for tid in batch_ids
                }
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        fetched_batch.append(result)

            # ── Step 3: write batch to DB (single-threaded) ───────────────
            for fetched in fetched_batch:
                self.write_movie(fetched)
                movies_written += 1

                if movies_written % self.batch_size == 0:
                    self.session.commit()
                    elapsed = time.time() - start_time
                    rate = movies_written / elapsed if elapsed > 0 else 0
                    remaining = len(tmdb_ids) - movies_written
                    eta = remaining / rate / 60 if rate > 0 else 0
                    logger.info(
                        f"Progress: {movies_written}/{len(tmdb_ids)} "
                        f"({movies_written/len(tmdb_ids)*100:.1f}%) | "
                        f"Rate: {rate:.1f} movies/sec | "
                        f"ETA: {eta:.1f} min"
                    )

        # Final commit
        self.session.commit()

        elapsed = time.time() - start_time
        rate = movies_written / elapsed if elapsed > 0 else 0
        logger.info(f"\n{'='*60}")
        logger.info(f"SYNC COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"  Total time:      {elapsed/60:.1f} minutes")
        logger.info(f"  Movies added:    {self.stats['movies_added']}")
        logger.info(f"  Movies updated:  {self.stats['movies_updated']}")
        logger.info(f"  Movies skipped:  {self.stats['movies_skipped']}")
        logger.info(f"  Errors:          {self.stats['errors']}")
        logger.info(f"  Average rate:    {rate:.1f} movies/sec")
        logger.info(f"{'='*60}\n")

    def close(self):
        self.session.close()


def main():
    parser = argparse.ArgumentParser(description="TMDB sync with parallel fetching")
    parser.add_argument("--limit", type=int, default=5000, help="Max movies to sync")
    parser.add_argument("--update-existing", action="store_true", help="Re-fetch existing movies")
    parser.add_argument(
        "--workers", type=int, default=10, help="Parallel fetch workers (default: 10)"
    )
    args = parser.parse_args()

    syncer = FastTMDBSyncer(
        limit=args.limit,
        update_existing=args.update_existing,
        workers=args.workers,
    )

    try:
        syncer.sync_genres()
        syncer.sync_popular_movies()
    except KeyboardInterrupt:
        logger.info("Sync interrupted — saving progress")
        syncer.session.commit()
    finally:
        syncer.close()


if __name__ == "__main__":
    main()
