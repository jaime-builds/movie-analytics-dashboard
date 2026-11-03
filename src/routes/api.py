"""Read-only JSON API under /api/v1."""

from flask import Blueprint, jsonify, request
from sqlalchemy import desc, extract, func
from sqlalchemy.orm import selectinload

from src.extensions import cache, limiter
from src.helpers import (
    MOVIE_SORTS,
    _api_positive_int_arg,
    _apply_movie_filters,
    _apply_movie_sort,
    _cached,
    _contains_pattern,
    _movie_search_query,
    _num,
    _public_rating_stats,
    get_current_user,
    get_db_session,
)
from src.logger import get_logger
from src.models import (
    Cast,
    Collection,
    Crew,
    Genre,
    Movie,
    Person,
    collection_movies_table,
)

logger = get_logger(__name__)

bp = Blueprint("api", __name__)


def _movie_summary(movie):
    """JSON shape for a movie in API lists."""
    return {
        "id": movie.id,
        "tmdb_id": movie.tmdb_id,
        "title": movie.title,
        "original_title": movie.original_title,
        "overview": movie.overview,
        "release_date": movie.release_date.isoformat() if movie.release_date else None,
        "runtime": movie.runtime,
        "vote_average": _num(movie.vote_average),
        "vote_count": movie.vote_count,
        "popularity": _num(movie.popularity),
        "poster_path": movie.poster_path,
        "backdrop_path": movie.backdrop_path,
        "genres": [{"id": g.id, "name": g.name} for g in movie.genres],
    }


@bp.route("/api/v1/movies", methods=["GET"])
@limiter.limit("60 per minute")
def get_movies():
    """Get list of movies with filtering and pagination"""
    session = get_db_session()
    try:
        # Get query parameters
        page, error = _api_positive_int_arg("page", 1)
        if error:
            return error
        per_page, error = _api_positive_int_arg("per_page", 20, max_value=100)
        if error:
            return error
        sort_by = request.args.get("sort", default="popularity")
        if sort_by not in MOVIE_SORTS:
            sort_by = "popularity"

        query = _apply_movie_filters(
            session.query(Movie),
            genre_id=request.args.get("genre", type=int),
            year=request.args.get("year", type=int),
            decade=request.args.get("decade", type=int),
            rating_min=request.args.get("min_rating", type=float),
            rating_max=request.args.get("max_rating", type=float),
            runtime_min=request.args.get("runtime_min", type=int),
            runtime_max=request.args.get("runtime_max", type=int),
            min_vote_count=request.args.get("min_vote_count", type=int),
            status=request.args.get("status", ""),
        )
        # Opt-in: infinite scroll passes this when the family-friendly toggle is on
        if request.args.get("exclude_mature") in ("1", "true"):
            query = query.filter(Movie.is_mature.is_(False))
        query = _apply_movie_sort(query, sort_by)

        # Pagination
        total = query.order_by(None).count()
        offset = (page - 1) * per_page
        movies = query.options(selectinload(Movie.genres)).limit(per_page).offset(offset).all()

        movies_data = [_movie_summary(movie) for movie in movies]

        return jsonify(
            {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": (total + per_page - 1) // per_page,
                "movies": movies_data,
            }
        )
    finally:
        session.close()


@bp.route("/api/v1/movies/<int:movie_id>", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def get_movie(movie_id):
    """Get detailed information about a specific movie"""
    session = get_db_session()
    try:
        movie = session.query(Movie).filter_by(id=movie_id).first()

        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        # Get cast
        cast_data = (
            session.query(Cast, Person)
            .join(Person)
            .filter(Cast.movie_id == movie_id)
            .order_by(Cast.cast_order)
            .limit(10)
            .all()
        )

        # Get crew
        crew_data = session.query(Crew, Person).join(Person).filter(Crew.movie_id == movie_id).all()

        # Get average rating (publicly visible ratings only)
        avg_rating, num_ratings = _public_rating_stats(session, movie_id)

        # Serialize movie data
        movie_data = {
            "id": movie.id,
            "tmdb_id": movie.tmdb_id,
            "title": movie.title,
            "original_title": movie.original_title,
            "overview": movie.overview,
            "release_date": (movie.release_date.isoformat() if movie.release_date else None),
            "runtime": movie.runtime,
            "budget": movie.budget,
            "revenue": movie.revenue,
            "vote_average": _num(movie.vote_average),
            "vote_count": movie.vote_count,
            "popularity": _num(movie.popularity),
            "poster_path": movie.poster_path,
            "backdrop_path": movie.backdrop_path,
            "imdb_id": movie.imdb_id,
            "tagline": movie.tagline,
            "status": movie.status,
            "genres": [{"id": g.id, "name": g.name} for g in movie.genres],
            "production_companies": [{"id": c.id, "name": c.name} for c in movie.companies],
            "cast": [
                {
                    "person_id": person.id,
                    "name": person.name,
                    "character": cast.character_name,
                    "order": cast.cast_order,
                    "profile_path": person.profile_path,
                }
                for cast, person in cast_data
            ],
            "crew": [
                {
                    "person_id": person.id,
                    "name": person.name,
                    "job": crew.job,
                    "department": crew.department,
                }
                for crew, person in crew_data
            ],
            "user_rating": {
                "average": _num(avg_rating),
                "count": num_ratings or 0,
            },
        }

        return jsonify(movie_data)
    finally:
        session.close()


@bp.route("/api/v1/movies/search", methods=["GET"])
@limiter.limit("30 per minute")
def search_movies():
    """Search for movies by title"""
    session = get_db_session()
    try:
        query_text = request.args.get("q", "").strip()
        page, error = _api_positive_int_arg("page", 1)
        if error:
            return error
        per_page, error = _api_positive_int_arg("per_page", 20, max_value=100)
        if error:
            return error

        if not query_text:
            return jsonify({"error": "Query parameter 'q' is required"}), 400

        search_query = _movie_search_query(session, query_text)

        total = search_query.order_by(None).count()
        offset = (page - 1) * per_page
        movies = search_query.limit(per_page).offset(offset).all()

        # Serialize
        movies_data = []
        for movie in movies:
            movies_data.append(
                {
                    "id": movie.id,
                    "tmdb_id": movie.tmdb_id,
                    "title": movie.title,
                    "overview": movie.overview,
                    "release_date": (
                        movie.release_date.isoformat() if movie.release_date else None
                    ),
                    "vote_average": _num(movie.vote_average),
                    "poster_path": movie.poster_path,
                }
            )

        return jsonify(
            {
                "query": query_text,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": (total + per_page - 1) // per_page,
                "movies": movies_data,
            }
        )
    finally:
        session.close()


@bp.route("/api/v1/genres", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def get_genres():
    """Get all genres"""
    session = get_db_session()
    try:
        genres = session.query(Genre).order_by(Genre.name).all()

        genres_data = [
            {"id": genre.id, "tmdb_id": genre.tmdb_id, "name": genre.name} for genre in genres
        ]

        return jsonify({"genres": genres_data})
    finally:
        session.close()


@bp.route("/api/v1/analytics/overview", methods=["GET"])
@limiter.limit("100 per day")
@cache.cached(timeout=3600)
def analytics_overview():
    """Get overview analytics"""
    session = get_db_session()
    try:
        # Total movies
        total_movies = session.query(func.count(Movie.id)).scalar()

        # Average rating
        avg_rating = (
            session.query(func.avg(Movie.vote_average)).filter(Movie.vote_count > 50).scalar()
        )

        # Total revenue
        total_revenue = session.query(func.sum(Movie.revenue)).filter(Movie.revenue > 0).scalar()

        # Movies by year
        movies_by_year = (
            session.query(
                extract("year", Movie.release_date).label("year"),
                func.count(Movie.id).label("count"),
            )
            .filter(Movie.release_date.isnot(None))
            .group_by("year")
            .order_by("year")
            .all()
        )

        return jsonify(
            {
                "total_movies": total_movies,
                "average_rating": _num(avg_rating),
                # SUM(bigint) is NUMERIC on Postgres (a Decimal, which JSON would
                # send as a string); int() keeps it a number everywhere
                "total_revenue": int(total_revenue or 0),
                "movies_by_year": [
                    {"year": int(year), "count": count} for year, count in movies_by_year
                ],
            }
        )
    finally:
        session.close()


@bp.route("/api/v1/analytics/genres", methods=["GET"])
@limiter.limit("100 per day")
@cache.cached(timeout=3600)
def analytics_genres():
    """Get genre analytics"""
    session = get_db_session()
    try:
        # Genre distribution
        genre_stats = (
            session.query(
                Genre.name,
                func.count(Movie.id).label("count"),
                func.avg(Movie.vote_average).label("avg_rating"),
            )
            .join(Movie.genres)
            .filter(Movie.vote_count > 50)
            .group_by(Genre.name)
            .order_by(desc("count"), Genre.name)
            .all()
        )

        genres_data = [
            {
                "name": name,
                "movie_count": count,
                "average_rating": _num(avg_rating),
            }
            for name, count, avg_rating in genre_stats
        ]

        return jsonify({"genres": genres_data})
    finally:
        session.close()


@bp.route("/api/v1/analytics/top-movies", methods=["GET"])
@limiter.limit("100 per day")
@cache.cached(
    timeout=3600,
    # Key on the two real parameters only, so junk query strings can't fill the cache
    make_cache_key=lambda: "api_top_movies:%s:%s"
    % (request.args.get("metric", "rating"), request.args.get("limit", "10")),
)
def analytics_top_movies():
    """Get top movies by various metrics"""
    session = get_db_session()
    try:
        metric = request.args.get("metric", "rating")
        limit, error = _api_positive_int_arg("limit", 10, max_value=100)
        if error:
            return error

        if metric == "rating":
            movies = (
                session.query(Movie)
                .filter(Movie.vote_count > 100)
                .order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
                .limit(limit)
                .all()
            )
        elif metric == "revenue":
            movies = (
                session.query(Movie)
                .filter(Movie.revenue > 0)
                .order_by(desc(Movie.revenue), Movie.id)
                .limit(limit)
                .all()
            )
        elif metric == "popularity":
            movies = (
                session.query(Movie)
                .order_by(desc(Movie.popularity).nulls_last(), Movie.id)
                .limit(limit)
                .all()
            )
        else:
            return (
                jsonify({"error": "Invalid metric. Use: rating, revenue, or popularity"}),
                400,
            )

        movies_data = [
            {
                "id": movie.id,
                "title": movie.title,
                "vote_average": _num(movie.vote_average),
                "revenue": movie.revenue,
                "popularity": _num(movie.popularity),
            }
            for movie in movies
        ]

        return jsonify({"metric": metric, "movies": movies_data})
    finally:
        session.close()


@bp.route("/api/v1/actors/search", methods=["GET"])
@limiter.limit("60 per minute")
def search_actors():
    """Search actors by name — used by Common Films autocomplete."""
    session = get_db_session()
    try:
        q = request.args.get("q", "").strip()
        # Optional: only return actors who share movies with already-selected actors
        with_ids = request.args.getlist("with", type=int)  # list of already-selected person IDs
        per_page, error = _api_positive_int_arg("per_page", 8, max_value=20)
        if error:
            return error

        if not q or len(q) < 2:
            return jsonify({"actors": []})

        query = (
            session.query(
                Person.id,
                Person.name,
                Person.profile_path,
                func.count(func.distinct(Cast.movie_id)).label("movie_count"),
            )
            .join(Cast, Person.id == Cast.person_id)
            .filter(Person.name.ilike(_contains_pattern(q), escape="\\"))
            .group_by(Person.id, Person.name, Person.profile_path)
        )

        # If actors already selected, restrict to those who share at least one
        # movie with ALL of them (avoids dead-end combinations)
        if with_ids:
            for wid in with_ids:
                shared_movies = (
                    session.query(Cast.movie_id).filter(Cast.person_id == wid).subquery()
                )
                query = query.filter(Cast.movie_id.in_(shared_movies))

        query = query.order_by(desc("movie_count"), Person.id).limit(per_page)
        results = query.all()

        return jsonify(
            {
                "actors": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "profile_path": r.profile_path,
                        "movie_count": r.movie_count,
                    }
                    for r in results
                ]
            }
        )
    finally:
        session.close()


@bp.route("/api/v1/actors", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def get_actors():
    """Get list of actors with pagination"""
    session = get_db_session()
    try:
        page, error = _api_positive_int_arg("page", 1)
        if error:
            return error
        per_page, error = _api_positive_int_arg("per_page", 20, max_value=100)
        if error:
            return error

        def compute():
            # Same counting rule as /top-actors; one query returns the page
            # and the total (window count), and the result is cached
            movie_count = func.count(func.distinct(Cast.movie_id)).label("movie_count")
            actors_query = (
                session.query(
                    Person.id,
                    Person.name,
                    Person.profile_path,
                    movie_count,
                    func.count().over().label("total"),
                )
                .join(Cast, Person.id == Cast.person_id)
                .join(Movie, Cast.movie_id == Movie.id)
                .filter(Movie.vote_count > 20)
                .group_by(Person.id, Person.name, Person.profile_path)
                .having(func.count(func.distinct(Cast.movie_id)) >= 2)
                .order_by(desc("movie_count"), Person.id)
            )
            rows = actors_query.limit(per_page).offset((page - 1) * per_page).all()
            total = rows[0].total if rows else actors_query.order_by(None).count()
            return total, [
                {
                    "id": r.id,
                    "name": r.name,
                    "profile_path": r.profile_path,
                    "movie_count": r.movie_count,
                }
                for r in rows
            ]

        total, actors_data = _cached(f"api_actors:{page}:{per_page}", compute)

        return jsonify(
            {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": (total + per_page - 1) // per_page,
                "actors": actors_data,
            }
        )
    finally:
        session.close()


ACTOR_FILMOGRAPHY_LIMIT = 200


@bp.route("/api/v1/actors/<int:actor_id>", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def get_actor(actor_id):
    """Get detailed information about an actor"""
    session = get_db_session()
    try:
        actor = session.query(Person).filter_by(id=actor_id).first()

        if not actor:
            return jsonify({"error": "Actor not found"}), 404

        # Filmography, one entry per movie (multiple roles joined), newest first
        filmography = []
        by_movie = {}
        for movie, cast in (
            session.query(Movie, Cast)
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id)
            .order_by(desc(Movie.release_date).nulls_last(), Movie.id, Cast.cast_order)
            .all()
        ):
            if movie.id in by_movie:
                entry = by_movie[movie.id]
                entry["character"] = f"{entry['character'] or 'Unknown'} / {cast.character_name}"
                continue
            entry = {
                "movie_id": movie.id,
                "title": movie.title,
                "character": cast.character_name,
                "release_date": movie.release_date.isoformat() if movie.release_date else None,
                "vote_average": _num(movie.vote_average),
            }
            by_movie[movie.id] = entry
            filmography.append(entry)

        # Calculate stats
        total_movies = len(filmography)
        avg_rating = (
            session.query(func.avg(Movie.vote_average))
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id, Movie.vote_count > 20)
            .scalar()
        )

        actor_data = {
            "id": actor.id,
            "name": actor.name,
            "profile_path": actor.profile_path,
            "total_movies": total_movies,
            "average_rating": _num(avg_rating),
            # Capped so a prolific actor can't produce a huge response
            "filmography": filmography[:ACTOR_FILMOGRAPHY_LIMIT],
            "filmography_truncated": total_movies > ACTOR_FILMOGRAPHY_LIMIT,
        }

        return jsonify(actor_data)
    finally:
        session.close()


@bp.route("/api/v1/health", methods=["GET"])
@limiter.exempt
def health():
    """Health check endpoint"""
    session = get_db_session()
    try:
        # Test database connection
        movie_count = session.query(func.count(Movie.id)).scalar()

        return jsonify({"status": "healthy", "database": "connected", "movie_count": movie_count})
    except Exception as e:
        logger.error(f"Health check database failure: {e}", exc_info=True)
        return jsonify({"status": "unhealthy", "error": "database unavailable"}), 500
    finally:
        session.close()


@bp.route("/api/v1/docs", methods=["GET"])
def docs():
    """API documentation"""
    docs = {
        "version": "1.0",
        "notes": {
            "numbers": "Decimal values are JSON numbers; a value of 0 is 0, missing is null.",
            "rate_limits": "Per IP. Exceeding a limit returns HTTP 429 with a JSON error.",
        },
        "endpoints": {
            "movies": {
                "GET /api/v1/movies": {
                    "description": "Get list of movies with filtering and pagination",
                    "parameters": {
                        "page": "Page number (default: 1, max: 10000)",
                        "per_page": "Results per page (default: 20, max: 100)",
                        "genre": "Filter by genre ID",
                        "sort": "popularity (default), rating (50+ votes), release_date, "
                        "upcoming (from today, soonest first), title. Unknown values use popularity.",
                        "year": "Filter by release year",
                        "decade": "Filter by decade start, e.g. 1990 (takes precedence over year)",
                        "min_rating": "Minimum TMDB rating",
                        "max_rating": "Maximum TMDB rating",
                        "runtime_min": "Minimum runtime in minutes",
                        "runtime_max": "Maximum runtime in minutes",
                        "min_vote_count": "Minimum TMDB vote count",
                        "status": "TMDB status, e.g. Released",
                        "exclude_mature": "1 to leave out movies flagged mature",
                    },
                },
                "GET /api/v1/movies/<id>": {
                    "description": "Get detailed information about a specific movie"
                },
                "GET /api/v1/movies/search": {
                    "description": "Search movie titles and overviews (title matches first)",
                    "parameters": {
                        "q": "Search text (required; % and _ match literally)",
                        "page": "Page number",
                        "per_page": "Results per page (default: 20, max: 100)",
                    },
                },
            },
            "genres": {"GET /api/v1/genres": {"description": "Get all genres"}},
            "analytics": {
                "GET /api/v1/analytics/overview": {"description": "Get overview analytics"},
                "GET /api/v1/analytics/genres": {"description": "Get genre analytics"},
                "GET /api/v1/analytics/top-movies": {
                    "description": "Get top movies by metric",
                    "parameters": {
                        "metric": "rating, revenue, or popularity",
                        "limit": "Number of results (default: 10, max: 100)",
                    },
                },
            },
            "actors": {
                "GET /api/v1/actors": {
                    "description": "Actors in 2+ movies (20+ votes each), most movies first",
                    "parameters": {
                        "page": "Page number (default: 1)",
                        "per_page": "Results per page (default: 20, max: 100)",
                    },
                },
                "GET /api/v1/actors/search": {
                    "description": "Search actors by name (used by Common Films)",
                    "parameters": {
                        "q": "Name text, at least 2 characters (required)",
                        "per_page": "Results (default: 8, max: 20)",
                        "with": "Repeatable actor ID: only return actors who share a movie "
                        "with every listed actor",
                    },
                },
                "GET /api/v1/actors/<id>": {
                    "description": "Actor details and filmography (up to 200 movies)"
                },
            },
            "collections": {
                "GET /api/v1/collections": {
                    "description": "The logged-in user's collections (session cookie "
                    "required; 401 JSON otherwise)"
                }
            },
            "system": {
                "GET /api/v1/health": {"description": "Health check endpoint"},
                "GET /api/v1/docs": {"description": "API documentation"},
            },
        },
    }

    return jsonify(docs)


@bp.route("/api/v1/collections", methods=["GET"])
@limiter.limit("100 per hour")
def get_collections():
    """Get current user's collections"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        user_collections = (
            session_db.query(
                Collection.id,
                Collection.name,
                Collection.description,
                Collection.updated_at,
                func.count(collection_movies_table.c.movie_id).label("movie_count"),
            )
            .outerjoin(
                collection_movies_table,
                Collection.id == collection_movies_table.c.collection_id,
            )
            .filter(Collection.user_id == user.id)
            .group_by(
                Collection.id,
                Collection.name,
                Collection.description,
                Collection.updated_at,
            )
            .order_by(desc(Collection.updated_at))
            .all()
        )

        return jsonify(
            {
                "collections": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "description": c.description,
                        "movie_count": c.movie_count,
                        "updated_at": (c.updated_at.isoformat() if c.updated_at else None),
                    }
                    for c in user_collections
                ]
            }
        )
    finally:
        session_db.close()
