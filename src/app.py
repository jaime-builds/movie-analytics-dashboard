from datetime import datetime
from typing import Dict, Optional

from flask import Flask, jsonify, render_template, request
from sqlalchemy import and_, desc, extract, func

from config.config import Config
from src.models import Cast, Crew, Genre, Movie, Person, ProductionCompany, Session
from src.tmdb_api import TMDBClient

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.config.from_object(Config)


def get_db_session():
    """Get a new database session"""
    return Session()


def get_trailer_for_movie(tmdb_id: int) -> Optional[Dict]:
    """Fetch the best YouTube trailer for a movie from TMDB API."""
    client = TMDBClient()
    videos_data = client.get_movie_videos(tmdb_id)
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


@app.route("/")
def index():
    """Homepage with featured movies"""
    session = get_db_session()

    try:
        # Get top rated movies
        top_movies = (
            session.query(Movie)
            .filter(Movie.vote_count > 100)
            .order_by(desc(Movie.vote_average))
            .limit(12)
            .all()
        )

        # Get upcoming releases (soonest first)
        recent_movies = (
            session.query(Movie)
            .filter(Movie.release_date >= datetime.now().date())
            .order_by(Movie.release_date)
            .limit(12)
            .all()
        )

        # Get popular movies
        popular_movies = session.query(Movie).order_by(desc(Movie.popularity)).limit(12).all()

        return render_template(
            "index.html",
            top_movies=top_movies,
            recent_movies=recent_movies,
            popular_movies=popular_movies,
            config=Config,
        )
    finally:
        session.close()


@app.route("/movies")
def movies():
    """All movies page with filters"""
    session = get_db_session()

    try:
        # Get filter parameters
        genre_id = request.args.get("genre", type=int)
        sort_by = request.args.get("sort", default="title")
        page = request.args.get("page", default=1, type=int)

        # Advanced filter parameters
        year = request.args.get("year", type=int)
        decade = request.args.get("decade", type=int)
        rating_min = request.args.get("rating_min", type=float)
        rating_max = request.args.get("rating_max", type=float)
        runtime_min = request.args.get("runtime_min", type=int)
        runtime_max = request.args.get("runtime_max", type=int)

        # Base query
        query = session.query(Movie)

        # Apply genre filter
        if genre_id:
            query = query.join(Movie.genres).filter(Genre.id == genre_id)

        # Apply year filter
        if year:
            query = query.filter(extract("year", Movie.release_date) == year)

        # Apply decade filter (takes precedence over year if both provided)
        if decade:
            decade_start = decade
            decade_end = decade + 9
            query = query.filter(
                extract("year", Movie.release_date) >= decade_start,
                extract("year", Movie.release_date) <= decade_end,
            )

        # Apply rating range filter
        if rating_min is not None:
            query = query.filter(Movie.vote_average >= rating_min)
        if rating_max is not None:
            query = query.filter(Movie.vote_average <= rating_max)

        # Apply runtime range filter
        if runtime_min is not None:
            query = query.filter(Movie.runtime >= runtime_min)
        if runtime_max is not None:
            query = query.filter(Movie.runtime <= runtime_max)

        # Apply sorting
        if sort_by == "rating":
            query = query.filter(Movie.vote_count > 50).order_by(desc(Movie.vote_average))
        elif sort_by == "release_date":
            query = query.filter(Movie.release_date.isnot(None)).order_by(desc(Movie.release_date))
        elif sort_by == "title":
            query = query.order_by(Movie.title)
        else:  # popularity (default)
            query = query.order_by(desc(Movie.popularity))

        # Pagination
        per_page = 20
        offset = (page - 1) * per_page
        total_movies = query.count()
        movies_list = query.limit(per_page).offset(offset).all()

        # Get all genres for filter dropdown
        all_genres = session.query(Genre).order_by(Genre.name).all()

        # Get available years for filter (distinct years from movies)
        available_years = (
            session.query(extract("year", Movie.release_date).label("year"))
            .filter(Movie.release_date.isnot(None))
            .distinct()
            .order_by(desc("year"))
            .all()
        )
        available_years = [int(y[0]) for y in available_years if y[0]]

        # Generate decade options (1920s to 2020s)
        current_year = datetime.now().year
        available_decades = list(range(1920, current_year + 1, 10))

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
            config=Config,
        )
    finally:
        session.close()


@app.route("/hidden-gems")
def hidden_gems():
    """Hidden gems page - high rated, low popularity movies"""
    session = get_db_session()

    try:
        # Get filter parameters
        genre_id = request.args.get("genre", type=int)
        decade = request.args.get("decade", type=int)
        min_rating = request.args.get("min_rating", default=7.0, type=float)
        max_popularity = request.args.get("max_popularity", default=20.0, type=float)
        sort_by = request.args.get("sort", default="gem_score")
        page = request.args.get("page", default=1, type=int)
        per_page = 24

        # Base query for hidden gems
        # High rating, low popularity, sufficient votes for credibility
        query = session.query(Movie).filter(
            Movie.vote_average >= min_rating,
            Movie.popularity <= max_popularity,
            Movie.vote_count >= 50,  # Ensure credible ratings
        )

        # Apply genre filter
        if genre_id:
            query = query.join(Movie.genres).filter(Genre.id == genre_id)

        # Apply decade filter
        if decade:
            decade_start = decade
            decade_end = decade + 9
            query = query.filter(
                extract("year", Movie.release_date) >= decade_start,
                extract("year", Movie.release_date) <= decade_end,
            )

        # Apply sorting
        if sort_by == "rating":
            query = query.order_by(desc(Movie.vote_average))
        elif sort_by == "most_hidden":
            # Most hidden = lowest popularity
            query = query.order_by(Movie.popularity)
        elif sort_by == "release_date":
            query = query.filter(Movie.release_date.isnot(None)).order_by(desc(Movie.release_date))
        else:  # gem_score (default)
            # Gem score = balance of high rating and low popularity
            # Formula: (rating / 10) * (1 / log(popularity + 1))
            # Higher score = better gem
            query = query.order_by(desc(Movie.vote_average / (func.log(Movie.popularity + 2) * 2)))

        # Get total count for pagination
        total_gems = query.count()

        # Apply pagination
        offset = (page - 1) * per_page
        gems = query.limit(per_page).offset(offset).all()

        # Calculate gem score for each movie (for display)
        for movie in gems:
            # Simple gem score formula - convert Decimal to float first
            rating = float(movie.vote_average)
            popularity = float(movie.popularity)

        if popularity > 0:
            movie.gem_score = round((rating / 10.0) * (100.0 / (popularity + 10)), 2)
        else:
            movie.gem_score = round(rating, 2)

        # Get all genres for filter
        all_genres = session.query(Genre).order_by(Genre.name).all()

        # Generate decade options
        current_year = datetime.now().year
        available_decades = list(range(1920, current_year + 1, 10))

        # Calculate pagination info
        total_pages = (total_gems + per_page - 1) // per_page

        return render_template(
            "hidden_gems.html",
            movies=gems,
            genres=all_genres,
            current_genre=genre_id,
            current_decade=decade,
            current_sort=sort_by,
            min_rating=min_rating,
            max_popularity=max_popularity,
            page=page,
            total_pages=total_pages,
            total_gems=total_gems,
            available_decades=available_decades,
            config=Config,
        )
    finally:
        session.close()


@app.route("/top-actors")
def top_actors():
    """Top actors page - most frequently appearing actors"""
    session = get_db_session()

    try:
        # Get query parameters for sorting and pagination
        sort_by = request.args.get("sort", default="movie_count")
        page = request.args.get("page", default=1, type=int)
        per_page = 24  # 4 rows of 6 actors

        # Query to get actors with their movie counts and average ratings
        actor_stats = (
            session.query(
                Person.id,
                Person.name,
                Person.profile_path,
                Person.popularity,
                func.count(Cast.movie_id).label("movie_count"),
                func.avg(Movie.vote_average).label("avg_rating"),
                func.max(Movie.release_date).label("latest_movie_date"),
            )
            .join(Cast, Person.id == Cast.person_id)
            .join(Movie, Cast.movie_id == Movie.id)
            .filter(Movie.vote_count > 20)
            .group_by(Person.id, Person.name, Person.profile_path, Person.popularity)
            .having(func.count(Cast.movie_id) >= 2)
        )

        # Apply sorting
        if sort_by == "rating":
            actor_stats = actor_stats.order_by(desc("avg_rating"))
        elif sort_by == "name":
            actor_stats = actor_stats.order_by(Person.name)
        elif sort_by == "popularity":
            actor_stats = actor_stats.order_by(desc(Person.popularity))
        else:  # movie_count (default)
            actor_stats = actor_stats.order_by(desc("movie_count"), desc("avg_rating"))

        # Get total count for pagination
        total_actors = actor_stats.count()

        # Apply pagination
        offset = (page - 1) * per_page
        actors = actor_stats.limit(per_page).offset(offset).all()

        # Calculate pagination info
        total_pages = (total_actors + per_page - 1) // per_page

        return render_template(
            "top_actors.html",
            actors=actors,
            current_sort=sort_by,
            page=page,
            total_pages=total_pages,
            total_actors=total_actors,
            config=Config,
        )
    finally:
        session.close()


@app.route("/actor/<int:actor_id>")
def actor_detail(actor_id):
    """Actor detail page showing their filmography"""
    session = get_db_session()

    try:
        # Get actor info
        actor = session.query(Person).filter_by(id=actor_id).first()

        if not actor:
            return "Actor not found", 404

        # Get all movies featuring this actor with their character names
        filmography = (
            session.query(Movie, Cast.character_name, Cast.cast_order)
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id)
            .order_by(desc(Movie.release_date))
            .all()
        )

        # Calculate statistics
        total_movies = len(filmography)
        avg_rating = (
            session.query(func.avg(Movie.vote_average))
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id, Movie.vote_count > 20)
            .scalar()
        )

        # Get genres this actor appears in most
        top_genres = (
            session.query(Genre.name, func.count(Movie.id).label("count"))
            .join(Movie.genres)
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id)
            .group_by(Genre.name)
            .order_by(desc("count"))
            .limit(5)
            .all()
        )

        return render_template(
            "actor_detail.html",
            actor=actor,
            filmography=filmography,
            total_movies=total_movies,
            avg_rating=round(avg_rating, 1) if avg_rating else None,
            top_genres=top_genres,
            config=Config,
        )
    finally:
        session.close()


@app.route("/movie/<int:movie_id>")
def movie_detail(movie_id):
    """Movie detail page"""
    session = get_db_session()

    try:
        movie = session.query(Movie).filter_by(id=movie_id).first()

        if not movie:
            return "Movie not found", 404

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

        # Get similar movies (same genres)
        if movie.genres:
            genre_ids = [g.id for g in movie.genres]
            similar_movies = (
                session.query(Movie)
                .join(Movie.genres)
                .filter(Genre.id.in_(genre_ids))
                .filter(Movie.id != movie_id)
                .order_by(desc(Movie.popularity))
                .limit(6)
                .all()
            )
        else:
            similar_movies = []

        # Get trailer from TMDB API
        trailer = get_trailer_for_movie(movie.tmdb_id)

        return render_template(
            "movie_detail.html",
            movie=movie,
            cast=cast,
            directors=directors,
            similar_movies=similar_movies,
            trailer=trailer,
            config=Config,
        )
    finally:
        session.close()


@app.route("/analytics")
def analytics():
    """Analytics dashboard"""
    session = get_db_session()

    try:
        # Genre distribution
        genre_stats = (
            session.query(Genre.name, func.count(Movie.id).label("count"))
            .join(Movie.genres)
            .group_by(Genre.name)
            .order_by(desc("count"))
            .all()
        )

        # Movies by year
        year_stats = (
            session.query(
                func.strftime("%Y", Movie.release_date).label("year"),
                func.count(Movie.id).label("count"),
            )
            .filter(Movie.release_date.isnot(None))
            .group_by("year")
            .order_by("year")
            .all()
        )

        # Average ratings by genre
        genre_ratings = (
            session.query(
                Genre.name,
                func.avg(Movie.vote_average).label("avg_rating"),
                func.count(Movie.id).label("count"),
            )
            .join(Movie.genres)
            .filter(Movie.vote_count > 50)
            .group_by(Genre.name)
            .having(func.count(Movie.id) >= 3)
            .order_by(desc("avg_rating"))
            .all()
        )

        # Get top 10 movies with budget/revenue data (optimized query)
        top_budget_movies = (
            session.query(Movie.title, Movie.budget, Movie.revenue)
            .filter(Movie.budget > 0, Movie.revenue > 0)
            .order_by(Movie.revenue.desc())
            .limit(10)
            .all()
        )

        # Top production companies
        top_companies = (
            session.query(
                ProductionCompany.name,
                func.count(Movie.id).label("movie_count"),
                func.avg(Movie.vote_average).label("avg_rating"),
            )
            .join(ProductionCompany.movies)
            .filter(Movie.vote_count > 50)
            .group_by(ProductionCompany.name)
            .having(func.count(Movie.id) >= 2)
            .order_by(desc("movie_count"))
            .limit(10)
            .all()
        )

        # Overall statistics
        total_movies = session.query(func.count(Movie.id)).scalar()
        avg_rating = (
            session.query(func.avg(Movie.vote_average)).filter(Movie.vote_count > 50).scalar()
        )
        total_revenue = session.query(func.sum(Movie.revenue)).filter(Movie.revenue > 0).scalar()

        return render_template(
            "analytics.html",
            genre_stats=genre_stats,
            year_stats=year_stats,
            genre_ratings=genre_ratings,
            budget_revenue=top_budget_movies,
            top_companies=top_companies,
            total_movies=total_movies,
            avg_rating=round(avg_rating, 1) if avg_rating else 0,
            total_revenue=total_revenue or 0,
            config=Config,
        )
    finally:
        session.close()


@app.route("/search")
def search():
    """Search movies"""
    session = get_db_session()

    try:
        query = request.args.get("q", "")

        if not query:
            return render_template("search.html", movies=[], query="", config=Config)

        # Search in title and overview
        movies_list = (
            session.query(Movie)
            .filter((Movie.title.ilike(f"%{query}%")) | (Movie.overview.ilike(f"%{query}%")))
            .order_by(desc(Movie.popularity))
            .limit(50)
            .all()
        )

        return render_template("search.html", movies=movies_list, query=query, config=Config)
    finally:
        session.close()


@app.template_filter("format_currency")
def format_currency(value):
    """Format number as currency"""
    if not value:
        return "N/A"
    return f"${value:,.0f}"


@app.template_filter("format_runtime")
def format_runtime(minutes):
    """Format runtime in minutes to hours and minutes"""
    if not minutes:
        return "N/A"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


@app.template_filter("format_date")
def format_date(date_obj):
    """Format date as 'Month Day, Year' (e.g., March 23, 2026)"""
    if not date_obj:
        return "N/A"
    return date_obj.strftime("%B %d, %Y")


if __name__ == "__main__":
    app.run(debug=True)
