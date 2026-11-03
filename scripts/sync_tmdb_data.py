"""
TMDB Data Synchronization Script

Collects movie IDs from TMDB's popular list, fetches each movie's details,
credits and keywords in parallel (one TMDB call per movie), and writes them
to the database from a single thread.

At 10 workers: ~5,000 movies in a few minutes.

Usage:
    python scripts/sync_tmdb_data.py --limit 5000
    python scripts/sync_tmdb_data.py --limit 5000 --update-existing
    python scripts/sync_tmdb_data.py --limit 1000 --workers 20
    python scripts/sync_tmdb_data.py --limit 5000 --strict   # exit 1 on any error

Exit codes:
    0  finished (a few per-movie errors are listed in the summary)
    1  genres or the ID list couldn't be fetched, a batch commit failed,
       errors exceeded 5% of the movies attempted, or --strict saw any error
    2  another sync already holds the lock (Postgres only)
    130 interrupted (Ctrl-C or SIGTERM); committed batches are kept
"""

import argparse
import logging
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from src.content import is_mature, keyword_names  # noqa: E402
from src.models import (  # noqa: E402
    Cast,
    Crew,
    Genre,
    Movie,
    Person,
    ProductionCompany,
    Session,
    engine,
    movie_companies_table,
    movie_genres_table,
)
from src.tmdb_api import TMDBClient, TMDBError  # noqa: E402

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/tmdb_sync_fast.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Postgres advisory lock key: only one sync may write at a time
SYNC_LOCK_ID = 72_201_101
# TMDB serves at most this many pages of any list
TMDB_MAX_PAGES = 500
# Give up collecting IDs after this many page failures in a row
MAX_CONSECUTIVE_PAGE_FAILURES = 3
# Above this share of failed movies the run is reported as failed
ERROR_RATE_LIMIT = 0.05

EXIT_OK, EXIT_FAILED, EXIT_LOCKED, EXIT_INTERRUPTED = 0, 1, 2, 130


class SyncAlreadyRunning(Exception):
    """Another sync process holds the advisory lock."""


def fetch_movie_data(tmdb_id: int, client: TMDBClient) -> dict | None:
    """Fetch details, credits and keywords for one movie. Runs in a thread.

    Returns None on any failure, including an empty or id-less reply, so a
    TMDB error can never turn into a blank movie row.
    """
    try:
        details = client.get_movie_details(tmdb_id, append=["credits", "keywords"])
    except TMDBError as e:
        logger.warning(f"Failed to fetch tmdb_id={tmdb_id}: {e}")
        return None
    if not details or "id" not in details:
        logger.warning(f"TMDB returned no movie data for tmdb_id={tmdb_id}")
        return None
    return {"tmdb_id": tmdb_id, "details": details, "credits": details.get("credits") or {}}


class FastTMDBSyncer:
    def __init__(
        self,
        limit: int = 5000,
        update_existing: bool = False,
        workers: int = 10,
        client: TMDBClient | None = None,
        session=None,
    ):
        # raise_errors: failures are counted, never written as empty rows.
        # max_retries: wait out TMDB's 429 rate limit instead of failing.
        self.client = client or TMDBClient(raise_errors=True, max_retries=3)
        self.session = session or Session()
        self.limit = limit
        self.update_existing = update_existing
        self.workers = workers
        self.batch_size = 50
        self._lock_connection = None
        self.stats = {
            "movies_added": 0,
            "movies_updated": 0,
            "movies_skipped": 0,
            "stats_refreshed": 0,
            "fetch_errors": 0,
            "write_errors": 0,
            "page_errors": 0,
            "commit_errors": 0,
        }
        # Written in the current batch but not committed yet. They move into
        # stats only once their batch commits, so the summary never counts a
        # movie a failed commit threw away.
        self._pending = {"movies_added": 0, "movies_updated": 0}
        self.fatal = False

    # ── locking ─────────────────────────────────────────────────────────
    def acquire_lock(self):
        """Refuse to run alongside another sync (Postgres advisory lock)."""
        if engine.dialect.name != "postgresql":
            return
        self._lock_connection = engine.connect()
        got_lock = self._lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": SYNC_LOCK_ID}
        ).scalar()
        if not got_lock:
            self._lock_connection.close()
            self._lock_connection = None
            raise SyncAlreadyRunning("another TMDB sync is already running")

    def release_lock(self):
        if self._lock_connection is not None:
            try:
                self._lock_connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": SYNC_LOCK_ID}
                )
            finally:
                self._lock_connection.close()
                self._lock_connection = None

    # ── genres ──────────────────────────────────────────────────────────
    def sync_genres(self):
        """Sync all genres from TMDB."""
        logger.info("Syncing genres...")
        try:
            genre_list = self.client.get_genres()
            if not genre_list:
                raise TMDBError("genre/movie/list: empty genre list")

            for genre_data in genre_list:
                genre = self.session.query(Genre).filter_by(tmdb_id=genre_data["id"]).first()
                if not genre:
                    genre = Genre(tmdb_id=genre_data["id"], name=genre_data["name"])
                    self.session.add(genre)
                else:
                    genre.name = genre_data["name"]

            self.session.commit()
            logger.info(f"Synced {len(genre_list)} genres")
        except (TMDBError, SQLAlchemyError) as e:
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

    # ── writing ─────────────────────────────────────────────────────────
    def write_movie(self, fetched: dict) -> str | None:
        """Write one fetched movie inside a savepoint. Always runs single-threaded.

        Returns "added", "updated" or "skipped", or None when the write failed.
        A failure rolls back only this movie's savepoint, never the rest of
        the uncommitted batch.
        """
        tmdb_id = fetched["tmdb_id"]
        details = fetched["details"]
        credits = fetched["credits"]

        try:
            with self.session.begin_nested():
                status = self._write_movie_rows(tmdb_id, details, credits)
        except SQLAlchemyError as e:
            logger.error(f"Error writing movie tmdb_id={tmdb_id}: {e}")
            self.stats["write_errors"] += 1
            return None

        if status == "skipped":
            self.stats["movies_skipped"] += 1
        else:
            self._pending[f"movies_{status}"] += 1
        return status

    def _write_movie_rows(self, tmdb_id: int, details: dict, credits: dict) -> str:
        existing = self.session.query(Movie).filter_by(tmdb_id=tmdb_id).first()

        if existing and not self.update_existing:
            return "skipped"

        is_new = existing is None
        movie = existing or Movie()

        release_date = None
        if details.get("release_date"):
            try:
                release_date = datetime.strptime(details["release_date"], "%Y-%m-%d").date()
            except ValueError:
                pass

        movie.tmdb_id = tmdb_id
        movie.title = details.get("title") or details.get("original_title") or "Untitled"
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
        movie.is_mature = is_mature(keyword_names(details))

        if is_new:
            self.session.add(movie)
        self.session.flush()

        # Genres. The link rows are cleared with a Core delete, which the
        # loaded relationship doesn't see, so expire it before re-adding.
        self.session.execute(
            movie_genres_table.delete().where(movie_genres_table.c.movie_id == movie.id)
        )
        self.session.expire(movie, ["genres", "companies"])
        for g in details.get("genres", []):
            genre = self.session.query(Genre).filter_by(tmdb_id=g["id"]).first()
            if genre and genre not in movie.genres:
                movie.genres.append(genre)

        # Production companies
        self.session.execute(
            movie_companies_table.delete().where(movie_companies_table.c.movie_id == movie.id)
        )
        for c in details.get("production_companies", []):
            company = self.session.query(ProductionCompany).filter_by(tmdb_id=c["id"]).first()
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
                cast_data["id"],
                cast_data["name"],
                cast_data.get("profile_path"),
            )
            self.session.add(
                Cast(
                    movie_id=movie.id,
                    person_id=person.id,
                    character_name=cast_data.get("character") or "Unknown",
                    cast_order=cast_data.get("order", 0),
                )
            )

        # Crew (directors only)
        for cm in self.session.query(Crew).filter_by(movie_id=movie.id).all():
            self.session.delete(cm)
        for crew_data in credits.get("crew", []):
            if crew_data.get("job") == "Director":
                person = self.get_person_or_create(
                    crew_data["id"],
                    crew_data["name"],
                    crew_data.get("profile_path"),
                )
                self.session.add(
                    Crew(
                        movie_id=movie.id,
                        person_id=person.id,
                        job=crew_data["job"],
                        department=crew_data.get("department", ""),
                    )
                )

        # Flush inside the savepoint, so any database error is raised (and
        # blamed) here rather than during the next movie or the batch commit
        self.session.flush()
        return "added" if is_new else "updated"

    def commit_batch(self) -> bool:
        """Commit the written movies; on failure count them as lost and carry on."""
        try:
            self.session.commit()
        except SQLAlchemyError as e:
            lost = sum(self._pending.values())
            logger.error(f"Batch commit failed, {lost} movie(s) not saved: {e}")
            self.session.rollback()
            self.stats["commit_errors"] += lost
            self._pending = {key: 0 for key in self._pending}
            self.fatal = True
            return False

        for key, count in self._pending.items():
            self.stats[key] += count
        self._pending = {key: 0 for key in self._pending}
        return True

    # ── collecting IDs ──────────────────────────────────────────────────
    def refresh_list_stats(self, results: list, existing_ids: set) -> None:
        """Update vote and popularity numbers for known movies from the list data.

        The popular list already carries these, so movies the weekly run skips
        still get current numbers without an extra TMDB call.
        """
        for movie_data in results:
            if movie_data.get("id") not in existing_ids:
                continue
            values = {
                key: movie_data[key]
                for key in ("popularity", "vote_average", "vote_count")
                if movie_data.get(key) is not None
            }
            if values:
                self.session.query(Movie).filter(Movie.tmdb_id == movie_data["id"]).update(
                    values, synchronize_session=False
                )
                self.stats["stats_refreshed"] += 1

    def collect_ids(self) -> list:
        tmdb_ids = []
        seen = set()
        page = 1
        total_pages = TMDB_MAX_PAGES
        consecutive_failures = 0
        logger.info("Collecting movie IDs from popular pages...")

        while len(tmdb_ids) < self.limit and page <= min(total_pages, TMDB_MAX_PAGES):
            try:
                data = self.client.get_popular_movies(page=page)
            except TMDBError as e:
                self.stats["page_errors"] += 1
                consecutive_failures += 1
                logger.error(f"Error fetching page {page}: {e}")
                if consecutive_failures >= MAX_CONSECUTIVE_PAGE_FAILURES:
                    logger.error("Too many page failures in a row; stopping ID collection")
                    break
                page += 1
                continue

            consecutive_failures = 0
            total_pages = data.get("total_pages") or total_pages
            results = [r for r in data.get("results", []) if r.get("id") is not None]
            if not results:
                break

            page_ids = [r["id"] for r in results]
            existing_ids = {
                row[0]
                for row in self.session.query(Movie.tmdb_id)
                .filter(Movie.tmdb_id.in_(page_ids))
                .all()
            }
            self.refresh_list_stats(results, existing_ids)

            for tmdb_id in page_ids:
                if len(tmdb_ids) >= self.limit:
                    break
                if tmdb_id in seen:
                    # The popular list shifts while it is paged, so an ID can repeat
                    continue
                seen.add(tmdb_id)
                if tmdb_id in existing_ids and not self.update_existing:
                    self.stats["movies_skipped"] += 1
                    continue
                tmdb_ids.append(tmdb_id)

            page += 1

        self.commit_batch()
        return tmdb_ids

    # ── main loop ───────────────────────────────────────────────────────
    def sync_popular_movies(self):
        """
        Fetch movie list pages sequentially, then fetch details+credits
        for each batch in parallel, then write to DB single-threaded.

        Pattern:
          [page fetch] → [parallel API fetch N movies] → [sequential DB write]
        """
        logger.info(f"Starting sync: {self.limit} movies, {self.workers} parallel workers")
        start_time = time.time()

        tmdb_ids = self.collect_ids()
        logger.info(f"Collected {len(tmdb_ids)} movie IDs to sync")

        if not tmdb_ids:
            if self.stats["page_errors"]:
                self.fatal = True
            logger.info("Nothing to sync.")
            self.log_summary(start_time, 0)
            return

        movies_written = 0
        fetch_batch_size = self.workers * 5  # fetch ahead 5x the worker count

        for batch_start in range(0, len(tmdb_ids), fetch_batch_size):
            batch_ids = tmdb_ids[batch_start : batch_start + fetch_batch_size]
            fetched_batch = []

            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {
                    executor.submit(fetch_movie_data, tid, self.client): tid for tid in batch_ids
                }
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        fetched_batch.append(result)
                    else:
                        self.stats["fetch_errors"] += 1

            for fetched in fetched_batch:
                self.write_movie(fetched)
                movies_written += 1

                if movies_written % self.batch_size == 0:
                    self.commit_batch()
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

        self.commit_batch()
        self.log_summary(start_time, len(tmdb_ids))

    def error_count(self) -> int:
        return (
            self.stats["fetch_errors"]
            + self.stats["write_errors"]
            + self.stats["page_errors"]
            + self.stats["commit_errors"]
        )

    def log_summary(self, start_time: float, attempted: int):
        elapsed = time.time() - start_time
        saved = self.stats["movies_added"] + self.stats["movies_updated"]
        rate = saved / elapsed if elapsed > 0 else 0
        logger.info("=" * 60)
        logger.info("SYNC COMPLETE")
        logger.info("=" * 60)
        logger.info(f"  Total time:      {elapsed/60:.1f} minutes")
        logger.info(f"  Movies added:    {self.stats['movies_added']}")
        logger.info(f"  Movies updated:  {self.stats['movies_updated']}")
        logger.info(f"  Movies skipped:  {self.stats['movies_skipped']}")
        logger.info(f"  Stats refreshed: {self.stats['stats_refreshed']}")
        logger.info(f"  Movies attempted: {attempted}")
        logger.info(
            f"  Errors:          {self.error_count()} "
            f"(fetch {self.stats['fetch_errors']}, write {self.stats['write_errors']}, "
            f"page {self.stats['page_errors']}, lost in commit {self.stats['commit_errors']})"
        )
        logger.info(f"  Average rate:    {rate:.1f} movies/sec")
        logger.info("=" * 60)

    def exit_code(self, strict: bool = False, attempted: int | None = None) -> int:
        errors = self.error_count()
        if self.fatal:
            return EXIT_FAILED
        if strict and errors:
            return EXIT_FAILED
        attempted = (
            attempted
            if attempted is not None
            else (self.stats["movies_added"] + self.stats["movies_updated"] + errors)
        )
        if attempted and errors / attempted > ERROR_RATE_LIMIT:
            return EXIT_FAILED
        return EXIT_OK

    def close(self):
        self.session.close()
        self.release_lock()


def _raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TMDB sync with parallel fetching")
    parser.add_argument("--limit", type=int, default=5000, help="Max movies to sync")
    parser.add_argument("--update-existing", action="store_true", help="Re-fetch existing movies")
    parser.add_argument(
        "--workers", type=int, default=10, help="Parallel fetch workers (default: 10)"
    )
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any movie or page failed")
    args = parser.parse_args(argv)

    # `docker stop` sends SIGTERM; treat it like Ctrl-C
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)

    syncer = FastTMDBSyncer(
        limit=args.limit,
        update_existing=args.update_existing,
        workers=args.workers,
    )

    try:
        syncer.acquire_lock()
        syncer.sync_genres()
        syncer.sync_popular_movies()
        return syncer.exit_code(strict=args.strict)
    except SyncAlreadyRunning as e:
        logger.error(f"{e}; exiting without changes")
        return EXIT_LOCKED
    except KeyboardInterrupt:
        # Committed batches stay; the half-written batch is discarded rather
        # than saving a movie with only some of its genres or credits
        syncer.session.rollback()
        logger.info("Sync interrupted; committed batches kept, the current batch discarded")
        return EXIT_INTERRUPTED
    except (TMDBError, SQLAlchemyError) as e:
        logger.error(f"Sync failed: {e}")
        return EXIT_FAILED
    finally:
        syncer.close()


if __name__ == "__main__":
    sys.exit(main())
