"""Movie of the Day, recommendations, similar movies and trailers."""

import hashlib
from typing import Dict, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError

from src.helpers import (
    GEM_MAX_POPULARITY,
    GEM_MIN_RATING,
    GEM_MIN_VOTES,
    _content_filtered,
    _featured_filters,
)
from src.logger import get_logger
from src.models import (
    Movie,
    MovieOfTheDay,
    Rating,
    local_today,
    movie_genres_table,
    user_favorites_table,
    user_watchlist_table,
)
from src.tmdb_api import TMDBClient

logger = get_logger(__name__)


def get_trailer_for_movie(tmdb_id: int) -> Optional[Dict]:
    """Fetch the best YouTube trailer for a movie from TMDB API."""
    client = TMDBClient()
    try:
        videos_data = client.get_movie_videos(tmdb_id)
    except Exception as exc:
        logger.warning(f"Unable to fetch trailer for tmdb_id={tmdb_id}: {exc}", exc_info=True)
        return None

    results = videos_data.get("results", [])

    youtube_videos = [v for v in results if v.get("site") == "YouTube"]
    if not youtube_videos:
        return None

    # Priority: official trailers > any trailer > teasers > any video
    for filter_fn in [
        lambda v: v.get("type") == "Trailer" and v.get("official"),
        lambda v: v.get("type") == "Trailer",
        lambda v: v.get("type") == "Teaser",
    ]:
        matches = [v for v in youtube_videos if filter_fn(v)]
        if matches:
            return matches[0]

    return youtube_videos[0]


def get_similar_movies(session, movie_id, limit=6, movie=None):
    """
    Get similar movies based on shared genres.
    Sorted by:
    1. Number of matching genres (descending)
    2. Vote average (descending)
    3. Popularity (descending)

    Pass `movie` when the caller already loaded it, to skip a query.
    """
    if movie is None:
        movie = session.query(Movie).filter_by(id=movie_id).first()

    if not movie or not movie.genres:
        # If no movie or no genres, return popular movies
        return (
            _content_filtered(session.query(Movie))
            .filter(Movie.id != movie_id)
            .filter(Movie.vote_count > 20)
            .order_by(desc(Movie.popularity), Movie.id)
            .limit(limit)
            .all()
        )

    # Get genre IDs for the current movie
    movie_genre_ids = [genre.id for genre in movie.genres]

    # Create subquery to count matching genres for each movie
    genre_match_subquery = (
        select(
            movie_genres_table.c.movie_id,
            func.count(movie_genres_table.c.genre_id).label("match_count"),
        )
        .where(movie_genres_table.c.genre_id.in_(movie_genre_ids))
        .group_by(movie_genres_table.c.movie_id)
        .subquery()
    )

    # Query for similar movies with genre match count
    similar_movies = (
        _content_filtered(session.query(Movie))
        .join(genre_match_subquery, Movie.id == genre_match_subquery.c.movie_id)
        .filter(Movie.id != movie_id)
        .filter(Movie.vote_count > 20)
        .order_by(
            desc(genre_match_subquery.c.match_count),  # Most genre matches first
            desc(Movie.vote_average),  # Then by rating
            desc(Movie.popularity),  # Then by popularity
            Movie.id,
        )
        .limit(limit)
        .all()
    )

    return similar_movies


def get_personalized_recommendations(session_db, user, limit=6, exclude_ids=()):
    """
    Get personalized movie recommendations based on user's favorites.

    Algorithm:
    1. Get all genres from user's favorite movies
    2. Find highly-rated movies in those genres the user hasn't favorited,
       watchlisted or rated (and not in exclude_ids, e.g. the page's movie)
    3. Weight by genre overlap and rating
    """
    favorite_ids = select(user_favorites_table.c.movie_id).where(
        user_favorites_table.c.user_id == user.id
    )
    seen_filters = [
        Movie.id.notin_(favorite_ids),
        Movie.id.notin_(
            select(user_watchlist_table.c.movie_id).where(user_watchlist_table.c.user_id == user.id)
        ),
        Movie.id.notin_(select(Rating.movie_id).where(Rating.user_id == user.id)),
    ]
    if exclude_ids:
        seen_filters.append(Movie.id.notin_(list(exclude_ids)))

    # Genres of the user's favorites, in one query
    favorite_genre_ids = [
        row[0]
        for row in session_db.query(movie_genres_table.c.genre_id)
        .filter(movie_genres_table.c.movie_id.in_(favorite_ids))
        .distinct()
        .all()
    ]

    if not favorite_genre_ids:
        # No favorites (or none with genres): popular highly-rated movies
        return (
            _content_filtered(session_db.query(Movie))
            .filter(Movie.vote_count > 100, *seen_filters)
            .order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
            .limit(limit)
            .all()
        )

    # Count genre matches for each movie
    genre_match_subquery = (
        select(
            movie_genres_table.c.movie_id,
            func.count(movie_genres_table.c.genre_id).label("match_count"),
        )
        .where(movie_genres_table.c.genre_id.in_(favorite_genre_ids))
        .group_by(movie_genres_table.c.movie_id)
        .subquery()
    )

    return (
        _content_filtered(session_db.query(Movie))
        .join(genre_match_subquery, Movie.id == genre_match_subquery.c.movie_id)
        .filter(Movie.vote_count > 50, *seen_filters)
        .order_by(
            desc(genre_match_subquery.c.match_count),  # Most genre matches
            desc(Movie.vote_average),  # Then by rating
            desc(Movie.popularity),  # Then by popularity
            Movie.id,
        )
        .limit(limit)
        .all()
    )


def _pick_movie_of_the_day(session_db, today):
    """Deterministically choose today's movie id from the eligible gem pool."""
    pool_query = session_db.query(Movie.id).filter(
        Movie.vote_average >= GEM_MIN_RATING,
        Movie.popularity <= GEM_MAX_POPULARITY,
        Movie.vote_count >= GEM_MIN_VOTES,
        *_featured_filters(),
    )

    recent_ids = [
        row.movie_id
        for row in session_db.query(MovieOfTheDay.movie_id)
        .order_by(desc(MovieOfTheDay.shown_date))
        .limit(30)
        .all()
    ]

    # Only IDs are loaded; the chosen movie is fetched on its own afterwards
    candidates = [
        row.id for row in pool_query.filter(Movie.id.notin_(recent_ids)).order_by(Movie.id).all()
    ]
    if not candidates:
        # Anti-repeat window exhausted the pool — fall back to the full pool
        candidates = [row.id for row in pool_query.order_by(Movie.id).all()]
    if not candidates:
        return None

    digest = hashlib.sha256(today.isoformat().encode("utf-8")).hexdigest()
    return candidates[int(digest, 16) % len(candidates)]


def get_movie_of_the_day(session_db):
    """Return today's featured movie, selecting and recording one if needed.

    Candidates come from the Hidden Gems pool (same criteria as /hidden-gems
    defaults), excluding the last 30 daily picks. The pick is deterministic
    per calendar day: a sha256 hash of the ISO date indexes into the candidate
    list sorted by movie id, so concurrent workers agree on the same movie
    without locking. (Python's built-in hash() is per-process randomized, so
    it can't be used here.)
    """
    today = local_today()

    existing = (
        session_db.query(MovieOfTheDay).filter(MovieOfTheDay.shown_date == today).one_or_none()
    )
    if existing:
        movie = (
            session_db.query(Movie)
            .filter(Movie.id == existing.movie_id, *_featured_filters())
            .one_or_none()
        )
        if movie is not None:
            return movie
        # Today's pick was flagged mature or hidden after it was chosen: swap it
        replacement_id = _pick_movie_of_the_day(session_db, today)
        if replacement_id is None:
            return None
        existing.movie_id = replacement_id
        session_db.commit()
        return session_db.query(Movie).filter(Movie.id == replacement_id).one_or_none()

    pick_id = _pick_movie_of_the_day(session_db, today)
    if pick_id is None:
        return None

    try:
        # Savepoint so a losing race only discards this insert, not the session
        with session_db.begin_nested():
            session_db.add(MovieOfTheDay(movie_id=pick_id, shown_date=today))
        session_db.commit()
    except IntegrityError:
        # Another worker inserted today's row first — use its pick instead
        existing = (
            session_db.query(MovieOfTheDay).filter(MovieOfTheDay.shown_date == today).one_or_none()
        )
        if existing is None:
            return None
        return session_db.query(Movie).filter(Movie.id == existing.movie_id).one_or_none()

    return session_db.query(Movie).filter(Movie.id == pick_id).one_or_none()
