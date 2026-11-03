"""
Set movies.is_mature for movies already in the database.

New and updated movies get the flag during the weekly sync. Run this once
after migration 009 to classify everything imported before it.

By default it asks TMDB for every movie carrying each mature keyword in
src/content.py (about 400 requests in total, a minute or two) and flags the
movies in the database that appear in those lists. `--per-movie` instead
fetches every movie's own keyword list (one request per movie: hours for
~22,000 movies), which is only worth it to double-check the keyword mode.

Usage:
    python scripts/backfill_mature_flags.py --dry-run     # report only
    python scripts/backfill_mature_flags.py               # write the flags
    python scripts/backfill_mature_flags.py --per-movie --workers 20

In production:
    docker exec dashboard-app python scripts/backfill_mature_flags.py --dry-run

Exit codes: 0 done, 1 too many TMDB lookups failed, 2 a sync is running.
"""

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from src.content import MATURE_KEYWORDS, is_mature  # noqa: E402
from src.models import Movie, Session, engine  # noqa: E402
from src.tmdb_api import TMDBClient, TMDBError  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Same advisory lock as scripts/sync_tmdb_data.py, so the two never overlap
SYNC_LOCK_ID = 72_201_101
CHUNK_SIZE = 200
# TMDB serves at most this many pages of any list
TMDB_MAX_PAGES = 500


# ── keyword mode (default) ──────────────────────────────────────────────
def mature_keyword_ids(client: TMDBClient) -> dict:
    """TMDB keyword ids whose name is exactly one of MATURE_KEYWORDS."""
    found = {}
    for name in sorted(MATURE_KEYWORDS):
        page, total_pages = 1, 1
        while page <= total_pages:
            data = client.search_keywords(name, page=page)
            total_pages = min(data.get("total_pages") or 1, TMDB_MAX_PAGES)
            for keyword in data.get("results", []):
                if (keyword.get("name") or "").strip().lower() == name:
                    found[keyword["id"]] = name
            page += 1
    return found


def mature_tmdb_ids(client: TMDBClient) -> set:
    """Every TMDB movie id tagged with a mature keyword, via discover/movie."""
    keyword_ids = mature_keyword_ids(client)
    logger.info(f"Found {len(keyword_ids)} mature keywords: {sorted(set(keyword_ids.values()))}")
    tmdb_ids = set()
    for keyword_id, name in sorted(keyword_ids.items()):
        page, total_pages = 1, 1
        while page <= total_pages:
            data = client.discover_movies(
                with_keywords=keyword_id, include_adult="false", page=page
            )
            total_pages = min(data.get("total_pages") or 1, TMDB_MAX_PAGES)
            tmdb_ids.update(m["id"] for m in data.get("results", []) if m.get("id"))
            page += 1
        logger.info(f"'{name}': {total_pages} page(s), {len(tmdb_ids)} movies so far")
    return tmdb_ids


def backfill_by_keyword(session, client: TMDBClient, dry_run: bool = False) -> dict:
    stats = {"checked": 0, "flagged": 0, "changed": 0, "failed": 0}
    try:
        flagged_ids = mature_tmdb_ids(client)
    except TMDBError as e:
        # A partial list could wrongly unflag movies, so nothing is written
        logger.error(f"Keyword lookup failed, nothing changed: {e}")
        stats["failed"] = 1
        return stats

    movies = session.query(Movie.id, Movie.tmdb_id, Movie.title, Movie.is_mature).all()
    to_flag, to_unflag = [], []
    for movie in movies:
        stats["checked"] += 1
        flag = movie.tmdb_id in flagged_ids
        if flag:
            stats["flagged"] += 1
        if flag != bool(movie.is_mature):
            stats["changed"] += 1
            (to_flag if flag else to_unflag).append(movie.id)
            logger.info(f"{'FLAG  ' if flag else 'UNFLAG'} {movie.title} (tmdb_id={movie.tmdb_id})")

    if not dry_run:
        for ids, value in ((to_flag, True), (to_unflag, False)):
            for start in range(0, len(ids), 1000):
                session.query(Movie).filter(Movie.id.in_(ids[start : start + 1000])).update(
                    {"is_mature": value}, synchronize_session=False
                )
        session.commit()
    return stats


# ── per-movie mode (slow, thorough) ─────────────────────────────────────
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
    parser.add_argument(
        "--per-movie",
        action="store_true",
        help="Look up every movie's keywords one by one (slow; default uses keyword searches)",
    )
    parser.add_argument("--workers", type=int, default=10, help="Parallel lookups (--per-movie)")
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
    client = TMDBClient(raise_errors=True, max_retries=3)
    try:
        if args.per_movie:
            stats = backfill(session, client, workers=args.workers, dry_run=args.dry_run)
        else:
            stats = backfill_by_keyword(session, client, dry_run=args.dry_run)
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
    if not args.per_movie:
        return 1 if stats["failed"] else 0
    total = stats["checked"] + stats["failed"]
    return 1 if total and stats["failed"] / total > 0.05 else 0


if __name__ == "__main__":
    sys.exit(main())
