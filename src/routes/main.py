"""Home page, movie browsing and detail, search, decades and studios."""

from flask import Blueprint, Response, abort, flash, redirect, render_template, request
from flask import session as flask_session
from flask import url_for
from sqlalchemy import case, desc, extract, func, select
from sqlalchemy.orm import contains_eager, selectinload

from config.config import Config
from src.extensions import limiter
from src.featured import (
    get_movie_of_the_day,
    get_personalized_recommendations,
    get_similar_movies,
    get_trailer_for_movie,
)
from src.helpers import (
    GEM_MAX_POPULARITY,
    GEM_MIN_RATING,
    GEM_MIN_VOTES,
    MAX_REVIEW_LENGTH,
    MOVIE_SORTS,
    _apply_movie_filters,
    _apply_movie_sort,
    _association_exists,
    _cached,
    _contains_pattern,
    _content_filtered,
    _featured_filters,
    _html_page_arg,
    _movie_search_query,
    _num,
    _public_rating_stats,
    _safe_next_url,
    _visible_content_filters,
    _year_range_filter,
    get_current_user,
    get_db_session,
)
from src.logger import get_logger
from src.models import (
    Cast,
    Crew,
    Genre,
    Movie,
    Person,
    ProductionCompany,
    Rating,
    Review,
    User,
    local_today,
    movie_companies_table,
    movie_genres_table,
    user_favorites_table,
    user_watchlist_table,
    utcnow,
)
from src.tmdb_api import TMDBClient

logger = get_logger(__name__)

bp = Blueprint("main", __name__)


# Home page "Top Rated" needs this many votes, so a niche title rated 9.4 by
# a few hundred people can't outrank the classics (FS-60)
TOP_RATED_MIN_VOTES = 1000


def _visible_reviews_query(session_db, movie_id):
    """Reviews for a movie that are safe to show to other users."""
    return (
        session_db.query(Review)
        .join(User, Review.user_id == User.id)
        .filter(Review.movie_id == movie_id, *_visible_content_filters(Review))
    )


def _year_options(session_db):
    """Distinct release years, newest first, for filter dropdowns."""

    def compute():
        rows = (
            session_db.query(extract("year", Movie.release_date).label("year"))
            .filter(Movie.release_date.isnot(None))
            .distinct()
            .order_by(desc("year"))
            .all()
        )
        return [int(y[0]) for y in rows if y[0]]

    return _cached("options:years", compute)


def _genre_options(session_db):
    """(id, name) pairs for genre dropdowns."""

    def compute():
        return [
            {"id": g.id, "name": g.name}
            for g in session_db.query(Genre.id, Genre.name).order_by(Genre.name).all()
        ]

    return _cached("options:genres", compute)


def _decade_options():
    return list(range(1920, utcnow().year + 1, 10))


def _home_stats(session_db):
    """Hero counts, cached (they only change at the weekly sync)."""

    def compute():
        total_movies = session_db.query(func.count(Movie.id)).scalar()
        total_genres = session_db.query(func.count(Genre.id)).scalar()
        total_directors = (
            session_db.query(func.count(func.distinct(Crew.person_id)))
            .filter(Crew.job == "Director")
            .scalar()
        )
        return total_movies, total_genres, total_directors

    return _cached("home:stats", compute)


@bp.route("/")
def index():
    """Homepage with featured movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        # Every home page list skips mature and admin-hidden movies (FS-60)
        featured = session.query(Movie).filter(*_featured_filters())

        # Top rated, among movies with enough votes for the average to mean something
        top_movies = (
            featured.filter(Movie.vote_count >= TOP_RATED_MIN_VOTES)
            .order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
            .limit(12)
            .all()
        )

        # Upcoming releases (soonest first)
        upcoming_movies = (
            featured.filter(Movie.release_date >= local_today())
            .order_by(Movie.release_date, Movie.id)
            .limit(12)
            .all()
        )

        # Most popular
        popular_movies = featured.order_by(desc(Movie.popularity), Movie.id).limit(12).all()

        # Featured movie of the day (from the Hidden Gems pool)
        movie_of_the_day = get_movie_of_the_day(session)

        total_movies, total_genres, total_directors = _home_stats(session)

        return render_template(
            "index.html",
            top_movies=top_movies,
            top_rated_min_votes=TOP_RATED_MIN_VOTES,
            upcoming_movies=upcoming_movies,
            popular_movies=popular_movies,
            movie_of_the_day=movie_of_the_day,
            total_movies=total_movies,
            total_genres=total_genres,
            total_directors=total_directors,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@bp.route("/movies")
def movies():
    """All movies page with filters and pagination"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        # Get filter parameters
        genre_id = request.args.get("genre", type=int)
        sort_by = request.args.get("sort", default="popularity")
        page = _html_page_arg()

        # Advanced filter parameters
        year = request.args.get("year", type=int)
        decade = request.args.get("decade", type=int)
        rating_min = request.args.get("rating_min", type=float)
        rating_max = request.args.get("rating_max", type=float)
        runtime_min = request.args.get("runtime_min", type=int)
        runtime_max = request.args.get("runtime_max", type=int)
        min_vote_count = request.args.get("min_vote_count", type=int)
        status_filter = request.args.get("status", "")

        query = _apply_movie_filters(
            _content_filtered(session.query(Movie)),
            genre_id=genre_id,
            year=year,
            decade=decade,
            rating_min=rating_min,
            rating_max=rating_max,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            min_vote_count=min_vote_count,
            status=status_filter,
        )
        if sort_by not in MOVIE_SORTS:
            sort_by = "popularity"
        query = _apply_movie_sort(query, sort_by)

        # Pagination
        per_page = 20
        offset = (page - 1) * per_page
        total_movies = query.order_by(None).count()
        movies_list = query.limit(per_page).offset(offset).all()

        all_genres = _genre_options(session)
        available_years = _year_options(session)
        available_decades = _decade_options()

        # Calculate pagination info
        total_pages = (total_movies + per_page - 1) // per_page

        return render_template(
            "movies.html",
            movies=movies_list,
            genres=all_genres,
            current_genre=genre_id,
            current_sort=sort_by,
            page=page,
            total_pages=total_pages,
            total_movies=total_movies,
            available_years=available_years,
            available_decades=available_decades,
            selected_year=year,
            selected_decade=decade,
            selected_rating_min=rating_min,
            selected_rating_max=rating_max,
            selected_runtime_min=runtime_min,
            selected_runtime_max=runtime_max,
            selected_min_vote_count=min_vote_count,
            selected_status=status_filter,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@bp.route("/hidden-gems")
def hidden_gems():
    """Hidden gems page - high rated, low popularity movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        # Get filter parameters
        genre_id = request.args.get("genre", type=int)
        decade = request.args.get("decade", type=int)
        min_rating = request.args.get("min_rating", default=GEM_MIN_RATING, type=float)
        max_popularity = request.args.get("max_popularity", default=GEM_MAX_POPULARITY, type=float)
        sort_by = request.args.get("sort", default="gem_score")
        page = _html_page_arg()
        per_page = 24

        # Base query for hidden gems
        query = _content_filtered(session.query(Movie)).filter(
            Movie.vote_average >= min_rating,
            Movie.popularity <= max_popularity,
            Movie.vote_count >= GEM_MIN_VOTES,
        )

        # Apply genre filter
        if genre_id:
            query = query.join(Movie.genres).filter(Genre.id == genre_id)

        # Apply decade filter
        if decade:
            query = query.filter(_year_range_filter(Movie.release_date, decade, decade + 9))

        # Apply sorting (Movie.id last keeps pages stable)
        if sort_by == "rating":
            query = query.order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
        elif sort_by == "most_hidden":
            query = query.order_by(Movie.popularity, Movie.id)
        elif sort_by == "release_date":
            query = query.filter(Movie.release_date.isnot(None)).order_by(
                desc(Movie.release_date), Movie.id
            )
        else:  # gem_score (default)
            query = query.order_by(
                desc(Movie.vote_average / (func.log(Movie.popularity + 2) * 2)),
                Movie.id,
            )

        # Get total count for pagination
        total_gems = query.order_by(None).count()

        # Apply pagination
        offset = (page - 1) * per_page
        gems_list = query.limit(per_page).offset(offset).all()

        all_genres = _genre_options(session)
        available_decades = _decade_options()

        # Calculate pagination info
        total_pages = (total_gems + per_page - 1) // per_page

        return render_template(
            "hidden_gems.html",
            gems=gems_list,
            genres=all_genres,
            selected_genre=genre_id,
            selected_decade=decade,
            min_rating=min_rating,
            max_popularity=max_popularity,
            sort_by=sort_by,
            page=page,
            total_pages=total_pages,
            total_gems=total_gems,
            available_decades=available_decades,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


TMDB_EXTRAS_CACHE_SECONDS = 24 * 3600


def _tmdb_movie_extras(tmdb_id):
    """Trailer and US watch providers for a movie, cached per movie for a day."""

    def compute():
        trailer = get_trailer_for_movie(tmdb_id)
        try:
            watch_providers = TMDBClient().get_watch_providers(tmdb_id)
        except Exception as exc:
            logger.warning(
                f"Unable to fetch watch providers for tmdb_id={tmdb_id}: {exc}",
                exc_info=True,
            )
            watch_providers = {}
        return {"trailer": trailer, "watch_providers": watch_providers}

    return _cached(f"tmdb:extras:{tmdb_id}", compute, timeout=TMDB_EXTRAS_CACHE_SECONDS)


@bp.route("/movie/<int:movie_id>")
def movie_detail(movie_id):
    """Movie detail page with ratings and reviews"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        movie = session.query(Movie).filter_by(id=movie_id).first()

        if not movie:
            abort(404)

        # Get cast (top 10)
        cast = (
            session.query(Cast, Person)
            .join(Person)
            .filter(Cast.movie_id == movie_id)
            .order_by(Cast.cast_order)
            .limit(10)
            .all()
        )

        # Get directors
        directors = (
            session.query(Crew, Person)
            .join(Person)
            .filter(Crew.movie_id == movie_id, Crew.job == "Director")
            .all()
        )

        # Get similar movies (sorted by genre match and rating)
        similar_movies = get_similar_movies(session, movie_id, limit=6, movie=movie)

        # Trailer and streaming providers come from TMDB. Both are cached for a
        # day per movie, so a slow TMDB can't hold up every movie page view.
        tmdb_extras = _tmdb_movie_extras(movie.tmdb_id)
        trailer = tmdb_extras["trailer"]
        watch_providers = tmdb_extras["watch_providers"]

        # Check if movie is in user's favorites/watchlist (EXISTS, not the whole list)
        is_favorited = False
        is_in_watchlist = False
        if user:
            is_favorited = _association_exists(
                session, user_favorites_table, user_id=user.id, movie_id=movie.id
            )
            is_in_watchlist = _association_exists(
                session, user_watchlist_table, user_id=user.id, movie_id=movie.id
            )

        # The user's own rating and review, so the forms show what they wrote
        user_rating = None
        user_review = None
        if user:
            user_rating = (
                session.query(Rating)
                .filter_by(user_id=user.id, movie_id=movie_id, is_deleted=False)
                .first()
            )
            user_review = (
                session.query(Review).filter_by(user_id=user.id, movie_id=movie_id).first()
            )

        # NEW: Get average rating and count (publicly visible ratings only)
        avg_rating, num_ratings = _public_rating_stats(session, movie_id)

        # NEW: Get reviews (paginated)
        review_page = _html_page_arg()
        per_page = 10

        # The join to User already happens for the visibility filter; reuse it so
        # review.user.username doesn't cost one query per review
        reviews_query = (
            _visible_reviews_query(session, movie_id)
            .options(contains_eager(Review.user))
            .order_by(desc(Review.created_at), desc(Review.id))
        )

        total_reviews = reviews_query.order_by(None).count()
        reviews = reviews_query.limit(per_page).offset((review_page - 1) * per_page).all()
        total_review_pages = (total_reviews + per_page - 1) // per_page

        # NEW: Get personalized recommendations (if user logged in)
        personalized_recs = []
        if user:
            personalized_recs = get_personalized_recommendations(
                session, user, limit=6, exclude_ids=[movie.id]
            )

        return render_template(
            "movie_detail.html",
            movie=movie,
            cast=cast,
            directors=directors,
            similar_movies=similar_movies,
            trailer=trailer,
            watch_providers=watch_providers,
            current_user=user,
            is_favorited=is_favorited,
            is_in_watchlist=is_in_watchlist,
            user_rating=user_rating,
            user_review=user_review,
            max_review_length=MAX_REVIEW_LENGTH,
            avg_rating=round(avg_rating, 1) if avg_rating else None,
            num_ratings=num_ratings or 0,
            reviews=reviews,
            review_page=review_page,
            total_reviews=total_reviews,
            total_review_pages=total_review_pages,
            personalized_recommendations=personalized_recs,
            config=Config,
        )
    finally:
        session.close()


SEARCH_RESULT_LIMIT = 50


@bp.route("/search")
def search():
    """Search movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        query = request.args.get("q", "").strip()

        if not query:
            return render_template(
                "search.html",
                movies=[],
                query="",
                total=0,
                limit=SEARCH_RESULT_LIMIT,
                current_user=user,
                config=Config,
            )

        search_query = _content_filtered(_movie_search_query(session, query))
        total = search_query.order_by(None).count()
        movies_list = search_query.limit(SEARCH_RESULT_LIMIT).all()

        return render_template(
            "search.html",
            movies=movies_list,
            query=query,
            total=total,
            limit=SEARCH_RESULT_LIMIT,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


# Decade flavor text for the index cards
_DECADE_DESCRIPTIONS = {
    1920: "The silent era gives way to sound. Hollywood establishes its golden foundation.",
    1930: "Depression-era escapism drives the studio system to its peak creative output.",
    1940: "War shapes storytelling. Film noir emerges from the shadows.",
    1950: "Widescreen spectacle, sci-fi anxieties, and the birth of teen culture.",
    1960: "The old studio system collapses. Counterculture rewrites cinema's rules.",
    1970: "The Movie Brats arrive. Auteur filmmaking at its most daring and raw.",
    1980: "Blockbuster culture takes hold. Practical effects reach their pinnacle.",
    1990: "Independent cinema explodes. Genre boundaries blur and shatter.",
    2000: "Digital filmmaking democratizes the art. Franchise era begins.",
    2010: "Streaming disrupts everything. Prestige TV and cinema converge.",
    2020: "A pandemic reshapes release windows. Streaming becomes the new normal.",
}


# A movie counts on decade pages once it has at least one vote (TMDB stores
# 0.0 for unrated movies, which would drag averages down)
DECADE_MIN_VOTES = 1


def _decade_movie_filters(decade_start):
    return (
        _year_range_filter(Movie.release_date, decade_start, decade_start + 9),
        Movie.vote_count >= DECADE_MIN_VOTES,
    )


def _decades_index(session_db):
    """Per-decade totals and a backdrop for each card, as plain data."""
    # Get per-year stats then bucket into decades in Python
    # (SQLite integer division inside func.cast is unreliable for grouping)
    year_raw = (
        session_db.query(
            extract("year", Movie.release_date).label("year"),
            func.count(Movie.id).label("movie_count"),
            func.avg(Movie.vote_average).label("avg_rating"),
            func.sum(Movie.revenue).label("total_revenue"),
        )
        .filter(Movie.release_date.isnot(None))
        .filter(Movie.vote_count >= DECADE_MIN_VOTES)
        .group_by("year")
        .all()
    )

    decade_buckets = {}
    for row in year_raw:
        if not row.year:
            continue
        ds = (int(row.year) // 10) * 10
        bucket = decade_buckets.setdefault(
            ds, {"movie_count": 0, "ratings": [], "total_revenue": 0}
        )
        bucket["movie_count"] += row.movie_count
        if row.avg_rating is not None:
            bucket["ratings"].append((float(row.avg_rating), row.movie_count))
        bucket["total_revenue"] += int(row.total_revenue or 0)

    decades_list = []
    for decade_start in sorted(decade_buckets.keys()):
        bucket = decade_buckets[decade_start]
        total_weighted = sum(r * c for r, c in bucket["ratings"])
        total_count = sum(c for _, c in bucket["ratings"])
        avg_rating = total_weighted / total_count if total_count else 0

        # Most popular movie with a backdrop for the card image
        hero_backdrop = (
            _content_filtered(session_db.query(Movie.backdrop_path))
            .filter(
                _year_range_filter(Movie.release_date, decade_start, decade_start + 9),
                Movie.backdrop_path.isnot(None),
                Movie.vote_count > 50,
                *_featured_filters(),
            )
            .order_by(desc(Movie.popularity), Movie.id)
            .limit(1)
            .scalar()
        )

        decades_list.append(
            {
                "decade_start": decade_start,
                "decade_end": decade_start + 9,
                "label": f"{decade_start}s",
                "movie_count": bucket["movie_count"],
                "avg_rating": round(avg_rating, 1),
                "total_revenue": bucket["total_revenue"],
                "description": _DECADE_DESCRIPTIONS.get(decade_start, ""),
                "hero_backdrop": hero_backdrop,
            }
        )
    return decades_list


@bp.route("/decades")
def decades():
    """Decade overview index page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)

        decades_list = _cached("decades:index", lambda: _decades_index(session_db))

        return render_template(
            "decades.html",
            decades=decades_list,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@bp.route("/decade/<int:decade_start>")
def decade_detail(decade_start):
    """Individual decade detail page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        decade_end = decade_start + 9

        # Validate decade: a decade starts on a year ending in 0
        if decade_start % 10 or decade_start < 1900 or decade_start > utcnow().year:
            abort(404)

        decade_filters = _decade_movie_filters(decade_start)
        base_query = _content_filtered(session_db.query(Movie)).filter(*decade_filters)

        total_movies = base_query.order_by(None).count()
        if total_movies == 0:
            abort(404)

        # Top rated (min 20 votes for reliability)
        top_rated = (
            base_query.filter(Movie.vote_count >= 20)
            .order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
            .limit(12)
            .all()
        )

        # Most popular
        most_popular = base_query.order_by(desc(Movie.popularity), Movie.id).limit(12).all()

        # Defining films: high rating AND high popularity — the cultural touchstones
        defining_films = (
            base_query.filter(Movie.vote_count >= 50)
            .order_by(desc(Movie.popularity * Movie.vote_average), Movie.id)
            .limit(6)
            .all()
        )

        # Genre breakdown, counted over the same movies as total_movies, with
        # ids so the badges can link to /movies?genre=<id>
        genre_stats = (
            session_db.query(Genre.id, Genre.name, func.count(Movie.id).label("count"))
            .join(Movie.genres)
            .filter(*decade_filters)
            .group_by(Genre.id, Genre.name)
            .order_by(desc("count"), Genre.name)
            .all()
        )

        # Stats
        avg_rating = (
            session_db.query(func.avg(Movie.vote_average))
            .filter(*decade_filters, Movie.vote_count >= 20)
            .scalar()
        )
        total_revenue = (
            session_db.query(func.sum(Movie.revenue))
            .filter(*decade_filters, Movie.revenue > 0)
            .scalar()
        )

        # Movies by year (for chart), over the same movies
        by_year = (
            session_db.query(
                extract("year", Movie.release_date).label("year"),
                func.count(Movie.id).label("count"),
                func.avg(Movie.vote_average).label("avg_rating"),
            )
            .filter(*decade_filters)
            .group_by("year")
            .order_by("year")
            .all()
        )

        stats = {
            "total_movies": total_movies,
            "avg_rating": round(float(avg_rating), 2) if avg_rating else 0,
            "total_revenue": int(total_revenue or 0),
            "top_genre": genre_stats[0].name if genre_stats else "N/A",
        }

        chart_data = {
            "years": [int(r.year) for r in by_year],
            "counts": [r.count for r in by_year],
            "ratings": [
                round(float(r.avg_rating), 2) if r.avg_rating is not None else None for r in by_year
            ],
        }

        return render_template(
            "decade_detail.html",
            decade_start=decade_start,
            decade_end=decade_end,
            label=f"{decade_start}s",
            description=_DECADE_DESCRIPTIONS.get(decade_start, ""),
            stats=stats,
            defining_films=defining_films,
            top_rated=top_rated,
            most_popular=most_popular,
            genre_stats=genre_stats,
            chart_data=chart_data,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


# Studios list and detail pages count movies with at least one vote, so the
# two agree; unrated movies (TMDB 0.0) would otherwise drag averages down
COMPANY_MIN_VOTES = 1

_COMPANY_SORTS = {
    "movies": (desc("movie_count"), ProductionCompany.id),
    "avg_rating": (desc("avg_rating"), desc("movie_count"), ProductionCompany.id),
    "total_revenue": (desc("total_revenue"), ProductionCompany.id),
    "name": (ProductionCompany.name, ProductionCompany.id),
}


@bp.route("/companies")
def companies():
    """Production companies listing page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        page = _html_page_arg()
        per_page = 24

        search = request.args.get("q", "").strip()
        sort_by = request.args.get("sort", "movies")
        if sort_by not in _COMPANY_SORTS:
            sort_by = "movies"

        companies_query = (
            session_db.query(
                ProductionCompany.id,
                ProductionCompany.name,
                ProductionCompany.logo_path,
                ProductionCompany.origin_country,
                func.count(Movie.id).label("movie_count"),
                func.avg(Movie.vote_average).label("avg_rating"),
                func.sum(Movie.revenue).label("total_revenue"),
            )
            .join(ProductionCompany.movies)
            .filter(Movie.vote_count >= COMPANY_MIN_VOTES)
        )
        if search:
            companies_query = companies_query.filter(
                ProductionCompany.name.ilike(_contains_pattern(search), escape="\\")
            )
        companies_query = (
            companies_query.group_by(
                ProductionCompany.id,
                ProductionCompany.name,
                ProductionCompany.logo_path,
                ProductionCompany.origin_country,
            )
            .having(func.count(Movie.id) >= 3)
            .order_by(*_COMPANY_SORTS[sort_by])
        )

        total = companies_query.order_by(None).count()
        total_pages = (total + per_page - 1) // per_page if total else 1
        page = max(1, min(page, total_pages))
        companies_data = companies_query.limit(per_page).offset((page - 1) * per_page).all()

        # Top 3 rated movies for every studio on the page, in one query
        company_ids = [row.id for row in companies_data]
        top_by_company = {company_id: [] for company_id in company_ids}
        if company_ids:
            rank = (
                func.row_number()
                .over(
                    partition_by=movie_companies_table.c.company_id,
                    order_by=(
                        desc(Movie.vote_average),
                        desc(Movie.vote_count),
                        Movie.id,
                    ),
                )
                .label("rank")
            )
            ranked = (
                select(
                    movie_companies_table.c.company_id,
                    Movie.id,
                    Movie.title,
                    Movie.release_date,
                    Movie.vote_average,
                    rank,
                )
                .join(Movie, movie_companies_table.c.movie_id == Movie.id)
                .where(
                    movie_companies_table.c.company_id.in_(company_ids),
                    Movie.vote_count >= COMPANY_MIN_VOTES,
                )
                .subquery()
            )
            for row in session_db.execute(
                select(ranked)
                .where(ranked.c.rank <= 3)
                .order_by(ranked.c.company_id, ranked.c.rank)
            ):
                top_by_company[row.company_id].append(
                    {
                        "id": row.id,
                        "title": row.title,
                        "year": row.release_date.year if row.release_date else None,
                        "vote_average": _num(row.vote_average) or 0,
                    }
                )

        companies_list = [
            {
                "id": row.id,
                "name": row.name,
                "logo_path": row.logo_path,
                "origin_country": row.origin_country,
                "movie_count": row.movie_count,
                "avg_rating": _num(row.avg_rating) or 0,
                "total_revenue": int(row.total_revenue or 0),
                "top_movies": top_by_company[row.id],
            }
            for row in companies_data
        ]

        return render_template(
            "companies.html",
            companies=companies_list,
            page=page,
            total_pages=total_pages,
            total=total,
            search=search,
            sort_by=sort_by,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


COMPANY_MOVIES_PER_PAGE = 48


@bp.route("/company/<int:company_id>")
def company_detail(company_id):
    """Individual production company detail page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)

        company = session_db.query(ProductionCompany).filter_by(id=company_id).first()
        if not company:
            abort(404)

        company_movies = (
            session_db.query(Movie)
            .join(Movie.companies)
            .filter(ProductionCompany.id == company_id)
            .filter(Movie.vote_count >= COMPANY_MIN_VOTES)
        )

        # Totals in SQL, so a studio with thousands of movies stays one query
        (
            total_movies,
            avg_rating,
            total_revenue,
            first_date,
            last_date,
        ) = company_movies.with_entities(
            func.count(Movie.id),
            func.avg(Movie.vote_average),
            func.sum(Movie.revenue),
            func.min(Movie.release_date),
            func.max(Movie.release_date),
        ).one()
        first_year = first_date.year if first_date else None
        last_year = last_date.year if last_date else None
        years_active = (last_year - first_year + 1) if first_year and last_year else 0

        movie_ids = company_movies.with_entities(Movie.id).subquery()
        genres = [
            {"name": name, "count": count}
            for name, count in session_db.query(Genre.name, func.count().label("count"))
            .join(movie_genres_table, Genre.id == movie_genres_table.c.genre_id)
            .filter(movie_genres_table.c.movie_id.in_(select(movie_ids.c.id)))
            .group_by(Genre.name)
            .order_by(desc("count"), Genre.name)
            .all()
        ]

        by_year = (
            company_movies.with_entities(
                extract("year", Movie.release_date).label("year"),
                func.avg(Movie.vote_average).label("avg_rating"),
                func.sum(Movie.revenue).label("revenue"),
            )
            .filter(Movie.release_date.isnot(None))
            .group_by("year")
            .order_by("year")
            .all()
        )
        chart_data = {
            "years": [int(r.year) for r in by_year],
            "ratings": [
                round(float(r.avg_rating), 2) if r.avg_rating is not None else None for r in by_year
            ],
            "revenues": [round(float(r.revenue or 0) / 1_000_000, 1) for r in by_year],
        }

        stats = {
            "total_movies": total_movies,
            "avg_rating": _num(avg_rating),
            "total_revenue": int(total_revenue or 0),
            "years_active": years_active,
            "first_year": first_year,
            "last_year": last_year,
            "genres": genres,
        }

        # The movie list is paginated, newest first (undated last)
        page = _html_page_arg()
        per_page = COMPANY_MOVIES_PER_PAGE
        total_pages = (total_movies + per_page - 1) // per_page if total_movies else 1
        page = max(1, min(page, total_pages))
        movies = (
            company_movies.options(selectinload(Movie.genres))
            .order_by(desc(Movie.release_date).nulls_last(), Movie.id)
            .limit(per_page)
            .offset((page - 1) * per_page)
            .all()
        )
        movies_list = [
            {
                "id": m.id,
                "title": m.title,
                "year": m.release_date.year if m.release_date else None,
                "poster_path": m.poster_path,
                "vote_average": _num(m.vote_average) or 0,
                "revenue": m.revenue,
                "runtime": m.runtime,
                "genres": [g.name for g in m.genres],
            }
            for m in movies
        ]

        return render_template(
            "company_detail.html",
            company=company,
            movies=movies_list,
            stats=stats,
            chart_data=chart_data,
            page=page,
            total_pages=total_pages,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@bp.route("/compare")
def compare():
    """Movie comparison page"""
    session = get_db_session()
    try:
        user = get_current_user(session)
        # Unique ids, in the order given, capped at 4
        ids = list(dict.fromkeys(request.args.getlist("id", type=int)))[:4]

        movies_list = []
        if ids:
            movies_list = session.query(Movie).filter(Movie.id.in_(ids)).all()
            # Preserve request order
            id_order = {mid: i for i, mid in enumerate(ids)}
            movies_list = sorted(movies_list, key=lambda m: id_order.get(m.id, 999))

        # First-listed director for each movie, in one query
        directors = {movie.id: None for movie in movies_list}
        if movies_list:
            for movie_id, person in (
                session.query(Crew.movie_id, Person)
                .join(Person, Person.id == Crew.person_id)
                .filter(Crew.movie_id.in_(directors.keys()), Crew.job == "Director")
                .order_by(Crew.movie_id, Crew.id)
                .all()
            ):
                if directors[movie_id] is None:
                    directors[movie_id] = person

        return render_template(
            "compare.html",
            movies=movies_list,
            directors=directors,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@bp.route("/advanced-search")
def advanced_search():
    """Advanced multi-filter search — combines text query with genre, year,
    decade, rating range, and runtime range in a single unified UI."""
    session = get_db_session()
    try:
        user = get_current_user(session)

        # Pull every filter param
        q = request.args.get("q", "").strip()
        genre_id = request.args.get("genre", type=int)
        decade = request.args.get("decade", type=int)
        year = request.args.get("year", type=int)
        rating_min = request.args.get("rating_min", type=float)
        rating_max = request.args.get("rating_max", type=float)
        runtime_min = request.args.get("runtime_min", type=int)
        runtime_max = request.args.get("runtime_max", type=int)
        min_votes = request.args.get("min_votes", type=int)
        sort_by = request.args.get("sort", default="relevance")
        page = _html_page_arg()
        per_page = 24

        # Only run the query when at least one filter is present
        has_filters = any(
            [
                q,
                genre_id,
                decade,
                year,
                rating_min is not None,
                rating_max is not None,
                runtime_min is not None,
                runtime_max is not None,
                min_votes is not None,
            ]
        )

        movies_list = []
        total = 0
        total_pages = 0

        if has_filters:
            if q:
                # Text search across title and overview, title matches first
                query = _movie_search_query(session, q).order_by(None)
            else:
                query = session.query(Movie)
            query = _apply_movie_filters(
                _content_filtered(query),
                genre_id=genre_id,
                year=year,
                decade=decade,
                rating_min=rating_min,
                rating_max=rating_max,
                runtime_min=runtime_min,
                runtime_max=runtime_max,
                min_vote_count=min_votes,
            )

            # Sorting (Movie.id last keeps pages stable)
            if sort_by == "rating":
                # Same rule as /movies: a rating needs 50+ votes to rank
                query = query.filter(Movie.vote_count > 50).order_by(
                    desc(Movie.vote_average), desc(Movie.vote_count), Movie.id
                )
            elif sort_by == "release_date":
                query = query.filter(Movie.release_date.isnot(None)).order_by(
                    desc(Movie.release_date), Movie.id
                )
            elif sort_by == "title":
                query = query.order_by(Movie.title, Movie.id)
            elif sort_by == "runtime":
                query = query.filter(Movie.runtime.isnot(None)).order_by(Movie.runtime, Movie.id)
            elif q:
                # relevance: title matches first, then popularity
                pattern = _contains_pattern(q)
                query = query.order_by(
                    case((Movie.title.ilike(pattern, escape="\\"), 0), else_=1),
                    desc(Movie.popularity).nulls_last(),
                    Movie.id,
                )
            else:  # relevance without text: popularity
                query = query.order_by(desc(Movie.popularity).nulls_last(), Movie.id)

            total = query.order_by(None).count()
            total_pages = (total + per_page - 1) // per_page
            movies_list = query.limit(per_page).offset((page - 1) * per_page).all()

        # Sidebar data
        all_genres = _genre_options(session)
        available_decades = _decade_options()

        return render_template(
            "advanced_search.html",
            movies=movies_list,
            total=total,
            total_pages=total_pages,
            page=page,
            per_page=per_page,
            has_filters=has_filters,
            genres=all_genres,
            available_decades=available_decades,
            # echo back every param so the form re-populates
            q=q,
            selected_genre=genre_id,
            selected_decade=decade,
            selected_year=year,
            selected_rating_min=rating_min,
            selected_rating_max=rating_max,
            selected_runtime_min=runtime_min,
            selected_runtime_max=runtime_max,
            selected_min_votes=min_votes,
            selected_sort=sort_by,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@bp.route("/preferences/family-friendly", methods=["POST"])
def set_family_friendly():
    """Turn family-friendly mode on or off for this browser (session cookie)."""
    requested = request.form.get("enabled", "").strip().lower()
    if requested in ("true", "false"):
        flask_session["family_friendly"] = requested == "true"
        if requested == "true":
            flash("Family-friendly mode is on: movies flagged mature are hidden.", "info")
        else:
            flash("Family-friendly mode is off.", "info")
    return redirect(_safe_next_url() or url_for("main.index"))


@bp.route("/robots.txt")
@limiter.exempt
def robots_txt():
    lines = [
        "User-agent: *",
        "Disallow: /admin",
        "Disallow: /api/",
        "Disallow: /login",
        "Disallow: /register",
        "Disallow: /preferences/",
        "Disallow: /analytics/export/",
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@bp.route("/favicon.ico")
@limiter.exempt
def favicon():
    return redirect(url_for("static", filename="images/jaime_builds_logo.png"), code=301)
