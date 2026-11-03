"""
Set movies.is_mature for movies already in the database.

New and updated movies get the flag during the weekly sync. Run this once
after migration 009 to classify everything imported before it. It fetches
each movie's TMDB keywords (one call per movie, 10 in parallel) and sets
is_mature from the list in src/content.py.

Usage:
    python scripts/backfill_mature_flags.py --dry-run     # report only
    python scripts/backfill_mature_flags.py               # write the flags
    python scripts/backfill_mature_flags.py --workers 20

In production:
    docker exec dashboard-app python scripts/backfill_mature_flags.py --dry-run

Exit codes: 0 done, 1 more than 5% of lookups failed, 2 a sync is running.
"""

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from src.content import is_mature  # noqa: E402
from src.models import Movie, Session, engine  # noqa: E402
from src.tmdb_api import TMDBClient, TMDBError  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Same advisory lock as scripts/sync_tmdb_data.py, so the two never overlap
SYNC_LOCK_ID = 72_201_101
CHUNK_SIZE = 200


def _keywords(client: TMDBClient, tmdb_id: int):
    try:
        return tmdb_id, [k.get("name", "") for k in client.get_movie_keywords(tmdb_id)]
    except TMDBError as e:
        logger.warning(f"Keyword lookup failed for tmdb_id={tmdb_id}: {e}")
        return tmdb_id, None


def backfill(session, client: TMDBClient, workers: int = 10, dry_run: bool = False) -> dict:
    stats = {"checked": 0, "flagged": 0, "changed": 0, "failed": 0}
    rows = session.query(Movie.id, Movie.tmdb_id, Movie.title, Movie.is_mature).order_by(Movie.id)
    movies = rows.all()
    logger.info(f"Checking {len(movies)} movies with {workers} workers")

    for start in range(0, len(movies), CHUNK_SIZE):
        chunk = movies[start : start + CHUNK_SIZE]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = dict(executor.map(lambda m: _keywords(client, m.tmdb_id), chunk))

        for movie in chunk:
            names = results.get(movie.tmdb_id)
            if names is None:
                stats["failed"] += 1
                continue
            stats["checked"] += 1
            flag = is_mature(names)
            if flag:
                stats["flagged"] += 1
            if flag != bool(movie.is_mature):
                stats["changed"] += 1
                logger.info(
                    f"{'FLAG  ' if flag else 'UNFLAG'} {movie.title} (tmdb_id={movie.tmdb_id})"
                )
                if not dry_run:
                    session.query(Movie).filter(Movie.id == movie.id).update(
                        {"is_mature": flag}, synchronize_session=False
                    )

        if not dry_run:
            session.commit()
        logger.info(f"Progress: {min(start + CHUNK_SIZE, len(movies))}/{len(movies)}")

    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Backfill movies.is_mature from TMDB keywords")
    parser.add_argument("--workers", type=int, default=10, help="Parallel TMDB lookups")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args(argv)

    lock_connection = None
    if engine.dialect.name == "postgresql":
        lock_connection = engine.connect()
        if not lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": SYNC_LOCK_ID}
        ).scalar():
            lock_connection.close()
            logger.error("A TMDB sync is running; try again when it finishes")
            return 2

    session = Session()
    try:
        stats = backfill(
            session,
            TMDBClient(raise_errors=True, max_retries=3),
            workers=args.workers,
            dry_run=args.dry_run,
        )
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Backfill failed: {e}")
        return 1
    finally:
        session.close()
        if lock_connection is not None:
            lock_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SYNC_LOCK_ID})
            lock_connection.close()

    verb = "would change" if args.dry_run else "changed"
    logger.info(
        f"Done: {stats['checked']} checked, {stats['flagged']} mature, "
        f"{stats['changed']} {verb}, {stats['failed']} lookups failed"
    )
    total = stats["checked"] + stats["failed"]
    return 1 if total and stats["failed"] / total > 0.05 else 0


if __name__ == "__main__":
    sys.exit(main())
