import csv
import io
import logging
import time
from datetime import datetime
from typing import Dict, Optional

from flask import Flask, Response, flash, jsonify, redirect, render_template, request
from flask import session as flask_session
from flask import url_for
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import Integer, and_, desc, extract, func, select
from werkzeug.exceptions import HTTPException

from config.config import Config
from src.logger import get_logger
from src.models import (
    Cast,
    Collection,
    Crew,
    Genre,
    Movie,
    Person,
    ProductionCompany,
    Rating,
    Review,
    Session,
    User,
    collection_movies_table,
    movie_genres_table,
)
from src.tmdb_api import TMDBClient

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Caching -- Redis in production, SimpleCache in local dev
# ---------------------------------------------------------------------------
_redis_url = Config.REDIS_URL

if _redis_url:
    _cache_config = {
        "CACHE_TYPE": "RedisCache",
        "CACHE_REDIS_URL": _redis_url,
        "CACHE_DEFAULT_TIMEOUT": 300,
    }
else:
    _cache_config = {
        "CACHE_TYPE": "SimpleCache",
        "CACHE_DEFAULT_TIMEOUT": 300,
    }

cache = Cache()
cache.init_app(app, config=_cache_config)

# ---------------------------------------------------------------------------
# Rate limiting -- Redis in production, memory in local dev
# In production behind Railway's proxy, trust X-Forwarded-For so the limiter
# keys on the real client IP rather than the proxy's internal address.
# ---------------------------------------------------------------------------
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=_redis_url if _redis_url else "memory://",
)

if _redis_url:
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


def get_db_session():
    """Get a new database session"""
    return Session()


# ==========================================
# REQUEST LOGGING
# ==========================================


@app.before_request
def _log_request_start():
    """Stamp the request start time for duration tracking."""
    request._start_time = time.monotonic()


@app.after_request
def _log_request_end(response):
    """Log every completed request with method, path, status, and duration."""
    duration_ms = round((time.monotonic() - getattr(request, "_start_time", 0)) * 1000)
    level = logging.WARNING if response.status_code >= 400 else logging.INFO
    logger.log(
        level,
        f"{request.method} {request.path} -> {response.status_code}",
        extra={
            "method": request.method,
            "path": request.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "ip": request.remote_addr,
        },
    )
    return response


@app.errorhandler(Exception)
def _handle_unhandled_exception(exc):
    """Log unhandled exceptions as ERROR before re-raising."""
    # Let Flask handle its own HTTP exceptions (404, 405, etc.) normally
    if isinstance(exc, HTTPException):
        return exc
    logger.error(
        f"Unhandled exception on {request.method} {request.path}: {exc}",
        exc_info=True,
        extra={"ip": request.remote_addr, "path": request.path},
    )
    return "Internal Server Error", 500


def get_current_user(session_db):
    """Get the currently logged-in user from session"""
    user_id = flask_session.get("user_id")
    if not user_id:
        return None
    return session_db.query(User).filter_by(id=user_id).first()


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


def get_similar_movies(session, movie_id, limit=6):
    """
    Get similar movies based on shared genres.
    Sorted by:
    1. Number of matching genres (descending)
    2. Vote average (descending)
    3. Popularity (descending)
    """
    # Get the current movie
    movie = session.query(Movie).filter_by(id=movie_id).first()

    if not movie or not movie.genres:
        # If no movie or no genres, return popular movies
        return (
            session.query(Movie)
            .filter(Movie.id != movie_id)
            .filter(Movie.vote_count > 20)
            .order_by(desc(Movie.popularity))
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
        session.query(Movie)
        .join(genre_match_subquery, Movie.id == genre_match_subquery.c.movie_id)
        .filter(Movie.id != movie_id)
        .filter(Movie.vote_count > 20)
        .order_by(
            desc(genre_match_subquery.c.match_count),  # Most genre matches first
            desc(Movie.vote_average),  # Then by rating
            desc(Movie.popularity),  # Then by popularity
        )
        .limit(limit)
        .all()
    )

    return similar_movies


def get_personalized_recommendations(session_db, user, limit=6):
    """
    Get personalized movie recommendations based on user's favorites.

    Algorithm:
    1. Get all genres from user's favorite movies
    2. Find highly-rated movies in those genres that user hasn't favorited
    3. Weight by genre overlap and rating
    """
    # Get user's favorite movies
    favorite_movies = user.favorites.all()

    if not favorite_movies:
        # If no favorites, return popular highly-rated movies
        return (
            session_db.query(Movie)
            .filter(Movie.vote_count > 100)
            .order_by(desc(Movie.vote_average))
            .limit(limit)
            .all()
        )

    # Get all genre IDs from user's favorites
    favorite_genre_ids = set()
    for movie in favorite_movies:
        for genre in movie.genres:
            favorite_genre_ids.add(genre.id)

    if not favorite_genre_ids:
        # Fallback to popular movies
        return (
            session_db.query(Movie)
            .filter(Movie.vote_count > 100)
            .order_by(desc(Movie.popularity))
            .limit(limit)
            .all()
        )

    # Get IDs of movies already favorited (to exclude)
    favorited_movie_ids = [m.id for m in favorite_movies]

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

    # Query for recommendations
    recommendations = (
        session_db.query(Movie)
        .join(genre_match_subquery, Movie.id == genre_match_subquery.c.movie_id)
        .filter(Movie.id.notin_(favorited_movie_ids))
        .filter(Movie.vote_count > 50)
        .order_by(
            desc(genre_match_subquery.c.match_count),  # Most genre matches
            desc(Movie.vote_average),  # Then by rating
            desc(Movie.popularity),  # Then by popularity
        )
        .limit(limit)
        .all()
    )

    return recommendations


# ==========================================
# USER AUTHENTICATION ROUTES
# ==========================================


@app.route("/register", methods=["GET", "POST"])
def register():
    session_db = get_db_session()
    try:
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            password_confirm = request.form.get("password_confirm", "")

            # Validation
            if not username or not password:
                flash("Username and password are required", "danger")
                return render_template("register.html")

            if len(username) < 3:
                flash("Username must be at least 3 characters", "danger")
                return render_template("register.html")

            if len(password) < 6:
                flash("Password must be at least 6 characters", "danger")
                return render_template("register.html")

            if password != password_confirm:
                flash("Passwords do not match", "danger")
                return render_template("register.html")

            # Check if username exists
            if session_db.query(User).filter_by(username=username).first():
                flash("Username already exists. Please choose another.", "danger")
                return render_template("register.html")

            # Create new user
            user = User(username=username)
            user.set_password(password)
            session_db.add(user)
            session_db.commit()

            # Log the user in
            flask_session["user_id"] = user.id
            logger.info(
                f"New user registered: {username}",
                extra={"user_id": user.id, "username": username, "ip": request.remote_addr},
            )
            flash(f"Welcome, {username}! Your account has been created.", "success")
            return redirect(url_for("index"))

        return render_template("register.html")
    finally:
        session_db.close()


@app.route("/login", methods=["GET", "POST"])
def login():
    session_db = get_db_session()
    try:
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            user = session_db.query(User).filter_by(username=username).first()

            if user and user.check_password(password):
                flask_session["user_id"] = user.id
                logger.info(
                    f"Successful login: {username}",
                    extra={"user_id": user.id, "username": username, "ip": request.remote_addr},
                )
                flash(f"Welcome back, {username}!", "success")

                # Redirect to 'next' page if it exists, otherwise home
                next_page = request.args.get("next")
                return redirect(next_page if next_page else url_for("index"))

            logger.warning(
                f"Failed login attempt: {username}",
                extra={"username": username, "ip": request.remote_addr},
            )
            flash("Invalid username or password", "danger")
            return render_template("login.html")

        return render_template("login.html")
    finally:
        session_db.close()


@app.route("/logout")
def logout():
    flask_session.pop("user_id", None)
    flash("You have been logged out successfully.", "info")
    return redirect(url_for("index"))


# ==========================================
# FAVORITES / WATCHLIST ROUTES
# ==========================================


@app.route("/favorites")
def favorites():
    """Display user's favorite movies"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your favorites", "warning")
            return redirect(url_for("login", next=request.url))

        # Convert dynamic relationship to list
        favorites = user.favorites.all()

        return render_template(
            "favorites.html", favorites=favorites, current_user=user, config=Config
        )
    finally:
        session_db.close()


@app.route("/watchlist")
def watchlist():
    """Display user's watchlist"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your watchlist", "warning")
            return redirect(url_for("login", next=request.url))

        # Convert dynamic relationship to list
        watchlist = user.watchlist.all()

        return render_template(
            "watchlist.html", watchlist=watchlist, current_user=user, config=Config
        )
    finally:
        session_db.close()


@app.route("/movie/<int:movie_id>/favorite", methods=["POST"])
def add_favorite(movie_id):
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        # Check if already in favorites
        if movie not in user.favorites.all():
            user.favorites.append(movie)
            session_db.commit()
            return jsonify({"status": "added"})

        return jsonify({"status": "already_added"})
    finally:
        session_db.close()


@app.route("/movie/<int:movie_id>/unfavorite", methods=["POST"])
def remove_favorite(movie_id):
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        if movie in user.favorites.all():
            user.favorites.remove(movie)
            session_db.commit()
            return jsonify({"status": "removed"})

        return jsonify({"status": "not_found"})
    finally:
        session_db.close()


@app.route("/movie/<int:movie_id>/watchlist", methods=["POST"])
def add_watchlist(movie_id):
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        if movie not in user.watchlist.all():
            user.watchlist.append(movie)
            session_db.commit()
            return jsonify({"status": "added"})

        return jsonify({"status": "already_added"})
    finally:
        session_db.close()


@app.route("/movie/<int:movie_id>/unwatchlist", methods=["POST"])
def remove_watchlist(movie_id):
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        if movie in user.watchlist.all():
            user.watchlist.remove(movie)
            session_db.commit()
            return jsonify({"status": "removed"})

        return jsonify({"status": "not_found"})
    finally:
        session_db.close()


# ==========================================
# NEW: RATINGS & REVIEWS ROUTES (FEATURE 1)
# ==========================================


@app.route("/movie/<int:movie_id>/rate", methods=["POST"])
def rate_movie(movie_id):
    """Submit or update a rating for a movie"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        # Get rating value from form
        rating_value = request.form.get("rating", type=int)

        # Validate rating
        if not rating_value or rating_value < 1 or rating_value > 5:
            return jsonify({"error": "Rating must be between 1 and 5"}), 400

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        # Check if user already rated this movie
        existing_rating = (
            session_db.query(Rating).filter_by(user_id=user.id, movie_id=movie_id).first()
        )

        if existing_rating:
            # Update existing rating
            existing_rating.rating = rating_value
            existing_rating.updated_at = datetime.utcnow()
            flash(f"Your rating has been updated to {rating_value} stars", "success")
        else:
            # Create new rating
            new_rating = Rating(user_id=user.id, movie_id=movie_id, rating=rating_value)
            session_db.add(new_rating)
            flash(f"You rated this movie {rating_value} stars", "success")

        session_db.commit()

        # Calculate new average rating
        avg_rating = (
            session_db.query(func.avg(Rating.rating)).filter(Rating.movie_id == movie_id).scalar()
        )
        num_ratings = (
            session_db.query(func.count(Rating.id)).filter(Rating.movie_id == movie_id).scalar()
        )

        return jsonify(
            {
                "status": "success",
                "rating": rating_value,
                "avg_rating": float(avg_rating) if avg_rating else 0,
                "num_ratings": num_ratings,
            }
        )
    finally:
        session_db.close()


@app.route("/movie/<int:movie_id>/review", methods=["POST"])
def submit_review(movie_id):
    """Submit a review for a movie"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to submit a review", "warning")
            return redirect(url_for("login", next=request.url))

        review_content = request.form.get("review_content", "").strip()

        # Validate review content
        if not review_content:
            flash("Review cannot be empty", "danger")
            return redirect(url_for("movie_detail", movie_id=movie_id))

        if len(review_content) < 10:
            flash("Review must be at least 10 characters long", "danger")
            return redirect(url_for("movie_detail", movie_id=movie_id))

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            flash("Movie not found", "danger")
            return redirect(url_for("index"))

        # Check if user already reviewed this movie
        existing_review = (
            session_db.query(Review).filter_by(user_id=user.id, movie_id=movie_id).first()
        )

        if existing_review:
            # Update existing review
            existing_review.content = review_content
            existing_review.updated_at = datetime.utcnow()
            flash("Your review has been updated", "success")
        else:
            # Create new review
            new_review = Review(user_id=user.id, movie_id=movie_id, content=review_content)
            session_db.add(new_review)
            flash("Your review has been submitted", "success")

        session_db.commit()
        return redirect(url_for("movie_detail", movie_id=movie_id))
    finally:
        session_db.close()


@app.route("/movie/<int:movie_id>/review/<int:review_id>/delete", methods=["POST"])
def delete_review(movie_id, review_id):
    """Delete a review"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        review = session_db.query(Review).filter_by(id=review_id).first()

        if not review:
            return jsonify({"error": "Review not found"}), 404

        # Check if user owns this review
        if review.user_id != user.id:
            return jsonify({"error": "Unauthorized"}), 403

        session_db.delete(review)
        session_db.commit()

        flash("Review deleted successfully", "success")
        return jsonify({"status": "deleted"})
    finally:
        session_db.close()


# ==========================================
# NEW: RECOMMENDATIONS ROUTE (FEATURE 2)
# ==========================================


@app.route("/recommendations")
def recommendations():
    """User's personalized recommendations page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to see personalized recommendations", "warning")
            return redirect(url_for("login", next=request.url))

        # Get personalized recommendations
        recommended_movies = get_personalized_recommendations(session_db, user, limit=12)

        return render_template(
            "recommendations.html",
            recommendations=recommended_movies,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


# ==========================================
# DIRECTOR ROUTES
# ==========================================


@app.route("/directors")
def directors():
    """Director spotlight page"""
    session_db = get_db_session()
    try:
        page = request.args.get("page", 1, type=int)
        per_page = 24

        user = get_current_user(session_db)

        # Get directors who have directed at least 3 movies
        directors_query = (
            session_db.query(
                Person.id,
                Person.name,
                func.count(Movie.id).label("movie_count"),
                func.avg(Movie.vote_average).label("avg_rating"),
                func.sum(Movie.revenue).label("total_revenue"),
            )
            .join(Crew, Person.id == Crew.person_id)
            .join(Movie, Crew.movie_id == Movie.id)
            .filter(Crew.job == "Director")
            .filter(Movie.vote_count > 10)
            .group_by(Person.id, Person.name)
            .having(func.count(Movie.id) >= 3)
            .order_by(desc("movie_count"))
        )

        # Pagination
        total = directors_query.count()
        total_pages = (total + per_page - 1) // per_page

        directors_data = directors_query.limit(per_page).offset((page - 1) * per_page).all()

        # Get top movies for each director
        directors_list = []
        for director_data in directors_data:
            # Get top 3 movies by rating
            top_movies = (
                session_db.query(Movie)
                .join(Crew, Movie.id == Crew.movie_id)
                .filter(Crew.person_id == director_data.id)
                .filter(Crew.job == "Director")
                .filter(Movie.vote_count > 10)
                .order_by(desc(Movie.vote_average))
                .limit(3)
                .all()
            )

            directors_list.append(
                {
                    "id": director_data.id,
                    "name": director_data.name,
                    "movie_count": director_data.movie_count,
                    "avg_rating": director_data.avg_rating or 0,
                    "total_revenue": director_data.total_revenue or 0,
                    "top_movies": [
                        {
                            "id": m.id,
                            "title": m.title,
                            "year": m.release_date.year if m.release_date else None,
                            "vote_average": m.vote_average,
                        }
                        for m in top_movies
                    ],
                }
            )

        return render_template(
            "directors.html",
            directors=directors_list,
            page=page,
            total_pages=total_pages,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/director/<int:director_id>")
def director_detail(director_id):
    """Individual director filmography page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)

        # Get director info
        director = session_db.query(Person).filter_by(id=director_id).first()
        if not director:
            return "Director not found", 404

        # Get all movies directed by this person
        movies_query = (
            session_db.query(Movie)
            .join(Crew, Movie.id == Crew.movie_id)
            .filter(Crew.person_id == director_id)
            .filter(Crew.job == "Director")
            .order_by(desc(Movie.release_date))
        )

        movies = movies_query.all()

        # Calculate statistics
        total_movies = len(movies)
        avg_rating = (
            sum(m.vote_average or 0 for m in movies) / total_movies if total_movies > 0 else 0
        )
        total_revenue = sum(m.revenue or 0 for m in movies)

        years = [m.release_date.year for m in movies if m.release_date]
        first_year = min(years) if years else None
        last_year = max(years) if years else None
        years_active = (last_year - first_year + 1) if first_year and last_year else 0

        # Genre distribution
        genre_counts = {}
        for movie in movies:
            for genre in movie.genres:
                genre_counts[genre.name] = genre_counts.get(genre.name, 0) + 1

        genres = [
            {"name": name, "count": count}
            for name, count in sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)
        ]

        # Chart data (movies by year)
        year_data = {}
        for movie in movies:
            if movie.release_date:
                year = movie.release_date.year
                if year not in year_data:
                    year_data[year] = {"ratings": [], "revenues": []}
                year_data[year]["ratings"].append(movie.vote_average or 0)
                year_data[year]["revenues"].append((movie.revenue or 0) / 1000000)

        chart_years = sorted(year_data.keys())
        chart_ratings = [
            sum(year_data[y]["ratings"]) / len(year_data[y]["ratings"]) for y in chart_years
        ]
        chart_revenues = [sum(year_data[y]["revenues"]) for y in chart_years]

        stats = {
            "total_movies": total_movies,
            "avg_rating": avg_rating,
            "total_revenue": total_revenue,
            "years_active": years_active,
            "first_year": first_year,
            "last_year": last_year,
            "genres": genres,
        }

        chart_data = {"years": chart_years, "ratings": chart_ratings, "revenues": chart_revenues}

        movies_list = [
            {
                "id": m.id,
                "title": m.title,
                "year": m.release_date.year if m.release_date else None,
                "poster_path": m.poster_path,
                "vote_average": m.vote_average,
                "revenue": m.revenue,
                "runtime": m.runtime,
                "genres": [g.name for g in m.genres],
            }
            for m in movies
        ]

        return render_template(
            "director_detail.html",
            director=director,
            movies=movies_list,
            stats=stats,
            chart_data=chart_data,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


# ==========================================
# MAIN ROUTES
# ==========================================


@app.route("/")
def index():
    """Homepage with featured movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

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

        # Stats for homepage hero
        total_movies = session.query(func.count(Movie.id)).scalar()
        total_genres = session.query(func.count(Genre.id)).scalar()
        total_directors = (
            session.query(func.count(func.distinct(Crew.person_id)))
            .filter(Crew.job == "Director")
            .scalar()
        )

        return render_template(
            "index.html",
            top_movies=top_movies,
            recent_movies=recent_movies,
            popular_movies=popular_movies,
            total_movies=total_movies,
            total_genres=total_genres,
            total_directors=total_directors,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@app.route("/movies")
def movies():
    """All movies page with filters and pagination"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        # Get filter parameters
        genre_id = request.args.get("genre", type=int)
        sort_by = request.args.get("sort", default="popularity")
        page = request.args.get("page", default=1, type=int)

        # Advanced filter parameters
        year = request.args.get("year", type=int)
        decade = request.args.get("decade", type=int)
        rating_min = request.args.get("rating_min", type=float)
        rating_max = request.args.get("rating_max", type=float)
        runtime_min = request.args.get("runtime_min", type=int)
        runtime_max = request.args.get("runtime_max", type=int)
        min_vote_count = request.args.get("min_vote_count", type=int)
        status_filter = request.args.get("status", "")

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

        # Apply min vote count filter
        if min_vote_count:
            query = query.filter(Movie.vote_count >= min_vote_count)

        # Apply status filter
        if status_filter:
            query = query.filter(Movie.status == status_filter)

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
            selected_min_vote_count=min_vote_count,
            selected_status=status_filter,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@app.route("/hidden-gems")
def hidden_gems():
    """Hidden gems page - high rated, low popularity movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        # Get filter parameters
        genre_id = request.args.get("genre", type=int)
        decade = request.args.get("decade", type=int)
        min_rating = request.args.get("min_rating", default=7.0, type=float)
        max_popularity = request.args.get("max_popularity", default=20.0, type=float)
        sort_by = request.args.get("sort", default="gem_score")
        page = request.args.get("page", default=1, type=int)
        per_page = 24

        # Base query for hidden gems
        query = session.query(Movie).filter(
            Movie.vote_average >= min_rating,
            Movie.popularity <= max_popularity,
            Movie.vote_count >= 50,
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
            query = query.order_by(Movie.popularity)
        elif sort_by == "release_date":
            query = query.filter(Movie.release_date.isnot(None)).order_by(desc(Movie.release_date))
        else:  # gem_score (default)
            query = query.order_by(desc(Movie.vote_average / (func.log(Movie.popularity + 2) * 2)))

        # Get total count for pagination
        total_gems = query.count()

        # Apply pagination
        offset = (page - 1) * per_page
        gems_list = query.limit(per_page).offset(offset).all()

        # Get all genres for filter dropdown
        all_genres = session.query(Genre).order_by(Genre.name).all()

        # Generate decade options
        current_year = datetime.now().year
        available_decades = list(range(1920, current_year + 1, 10))

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


@app.route("/top-actors")
def top_actors():
    """Top actors page - actors who appear in most movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        sort_by = request.args.get("sort", default="movie_count")
        page = request.args.get("page", default=1, type=int)
        per_page = 24

        # Base query - count movies per actor
        query = (
            session.query(
                Person,
                func.count(Cast.movie_id).label("movie_count"),
                func.avg(Movie.vote_average).label("avg_rating"),
                func.avg(Movie.popularity).label("avg_popularity"),
            )
            .join(Cast, Person.id == Cast.person_id)
            .join(Movie, Cast.movie_id == Movie.id)
            .filter(Movie.vote_count > 20)
            .group_by(Person.id)
            .having(func.count(Cast.movie_id) >= 2)
        )

        # Apply sorting
        if sort_by == "avg_rating":
            query = query.order_by(desc("avg_rating"))
        elif sort_by == "avg_popularity":
            query = query.order_by(desc("avg_popularity"))
        elif sort_by == "name":
            query = query.order_by(Person.name)
        else:
            query = query.order_by(desc("movie_count"))

        # Get total count for pagination
        total_actors = query.count()

        # Apply pagination
        offset = (page - 1) * per_page
        actors_raw = query.limit(per_page).offset(offset).all()

        # Unpack tuples into a more template-friendly format
        actors_list = [
            {
                "person": row[0],
                "movie_count": row[1],
                "avg_rating": row[2],
                "avg_popularity": row[3],
            }
            for row in actors_raw
        ]

        # Calculate pagination info
        total_pages = (total_actors + per_page - 1) // per_page

        return render_template(
            "top_actors.html",
            actors=actors_list,
            sort_by=sort_by,
            page=page,
            total_pages=total_pages,
            total_actors=total_actors,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@app.route("/actor/<int:actor_id>")
def actor_detail(actor_id):
    """Actor detail page with filmography"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        # Get actor info
        actor = session.query(Person).filter_by(id=actor_id).first()

        if not actor:
            return "Actor not found", 404

        # Get filmography (movies with this actor) - fixed to return proper tuple
        filmography_raw = (
            session.query(Movie, Cast)
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id)
            .order_by(desc(Movie.release_date))
            .all()
        )

        # Convert to format expected by template: (movie, character, cast_order)
        filmography = []
        for movie, cast in filmography_raw:
            # Get character name from Cast if it exists
            character = (
                getattr(cast, "character_name", None)
                or getattr(cast, "character", None)
                or "Unknown"
            )
            cast_order = cast.cast_order if hasattr(cast, "cast_order") else 0
            filmography.append((movie, character, cast_order))

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
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@app.route("/movie/<int:movie_id>")
def movie_detail(movie_id):
    """Movie detail page with ratings and reviews"""
    session = get_db_session()

    try:
        user = get_current_user(session)

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

        # Get similar movies (sorted by genre match and rating)
        similar_movies = get_similar_movies(session, movie_id, limit=6)

        # Get trailer from TMDB API
        trailer = get_trailer_for_movie(movie.tmdb_id)

        # Get streaming/watch providers from TMDB API
        client = TMDBClient()
        watch_providers = client.get_watch_providers(movie.tmdb_id)

        # Check if movie is in user's favorites/watchlist
        is_favorited = False
        is_in_watchlist = False
        if user:
            is_favorited = movie in user.favorites.all()
            is_in_watchlist = movie in user.watchlist.all()

        # NEW: Get user's rating for this movie (if logged in)
        user_rating = None
        if user:
            user_rating = (
                session.query(Rating).filter_by(user_id=user.id, movie_id=movie_id).first()
            )

        # NEW: Get average rating and count
        avg_rating = (
            session.query(func.avg(Rating.rating)).filter(Rating.movie_id == movie_id).scalar()
        )
        num_ratings = (
            session.query(func.count(Rating.id)).filter(Rating.movie_id == movie_id).scalar()
        )

        # NEW: Get reviews (paginated)
        review_page = request.args.get("page", 1, type=int)
        per_page = 10

        reviews_query = (
            session.query(Review)
            .filter(Review.movie_id == movie_id)
            .order_by(desc(Review.created_at))
        )

        total_reviews = reviews_query.count()
        reviews = reviews_query.limit(per_page).offset((review_page - 1) * per_page).all()
        total_review_pages = (total_reviews + per_page - 1) // per_page

        # NEW: Get personalized recommendations (if user logged in)
        personalized_recs = []
        if user:
            personalized_recs = get_personalized_recommendations(session, user, limit=6)

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
            avg_rating=round(avg_rating, 1) if avg_rating else None,
            num_ratings=num_ratings or 0,
            reviews=reviews,
            review_page=review_page,
            total_review_pages=total_review_pages,
            personalized_recommendations=personalized_recs,
            config=Config,
        )
    finally:
        session.close()


@app.route("/analytics")
@cache.cached(timeout=3600)
def analytics():
    """Analytics dashboard"""
    session = get_db_session()

    try:
        user = get_current_user(session)

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
                extract("year", Movie.release_date).label("year"),
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

        # Get top 10 movies with budget/revenue data
        top_budget_movies = (
            session.query(Movie.title, Movie.budget, Movie.revenue)
            .filter(Movie.budget > 0, Movie.revenue > 0)
            .order_by(Movie.revenue.desc())
            .limit(10)
            .all()
        )

        # Budget vs revenue scatter data (up to 300 movies with known budget)
        budget_revenue_scatter = [
            [r[0], r[1], r[2], float(r[3]) if r[3] is not None else None]
            for r in (
                session.query(Movie.title, Movie.budget, Movie.revenue, Movie.vote_average)
                .filter(Movie.budget > 1_000_000, Movie.revenue > 0)
                .order_by(desc(Movie.revenue))
                .limit(300)
                .all()
            )
        ]

        # Most profitable movies (revenue - budget), top 15
        most_profitable = [
            [r[0], r[1], r[2]]
            for r in (
                session.query(Movie.title, Movie.budget, Movie.revenue)
                .filter(Movie.budget > 1_000_000, Movie.revenue > 0)
                .order_by(desc(Movie.revenue - Movie.budget))
                .limit(15)
                .all()
            )
        ]

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
            budget_revenue_scatter=budget_revenue_scatter,
            most_profitable=most_profitable,
            top_companies=top_companies,
            total_movies=total_movies,
            avg_rating=round(avg_rating, 1) if avg_rating else 0,
            total_revenue=total_revenue or 0,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@app.route("/analytics/export/csv")
@limiter.limit("20 per hour")
def analytics_export_csv():
    """Export analytics data as a CSV file download"""
    session = get_db_session()
    try:
        # Genre statistics
        genre_stats = (
            session.query(
                Genre.name,
                func.count(Movie.id).label("count"),
                func.avg(Movie.vote_average).label("avg_rating"),
            )
            .join(Movie.genres)
            .group_by(Genre.name)
            .order_by(desc("count"))
            .all()
        )

        # Movies by year
        year_stats = (
            session.query(
                extract("year", Movie.release_date).label("year"),
                func.count(Movie.id).label("count"),
            )
            .filter(Movie.release_date.isnot(None))
            .group_by("year")
            .order_by("year")
            .all()
        )

        # Top 25 movies by rating
        top_rated = (
            session.query(
                Movie.title, Movie.vote_average, Movie.vote_count, Movie.revenue, Movie.release_date
            )
            .filter(Movie.vote_count > 100)
            .order_by(desc(Movie.vote_average))
            .limit(25)
            .all()
        )

        # Top 25 movies by revenue
        top_revenue = (
            session.query(
                Movie.title, Movie.budget, Movie.revenue, Movie.vote_average, Movie.release_date
            )
            .filter(Movie.revenue > 0)
            .order_by(desc(Movie.revenue))
            .limit(25)
            .all()
        )

        # Build CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)

        # --- Section 1: Genre Statistics ---
        writer.writerow(["GENRE STATISTICS"])
        writer.writerow(["Genre", "Movie Count", "Average Rating"])
        for name, count, avg_rating in genre_stats:
            writer.writerow([name, count, f"{avg_rating:.2f}" if avg_rating else "N/A"])

        writer.writerow([])

        # --- Section 2: Movies by Release Year ---
        writer.writerow(["MOVIES BY RELEASE YEAR"])
        writer.writerow(["Year", "Movie Count"])
        for year, count in year_stats:
            writer.writerow([year, count])

        writer.writerow([])

        # --- Section 3: Top 25 Movies by Rating ---
        writer.writerow(["TOP 25 MOVIES BY RATING"])
        writer.writerow(["Title", "Rating", "Vote Count", "Revenue", "Release Year"])
        for title, rating, vote_count, revenue, release_date in top_rated:
            writer.writerow(
                [
                    title,
                    f"{rating:.1f}" if rating else "N/A",
                    vote_count or 0,
                    f"${revenue:,}" if revenue else "N/A",
                    release_date.year if release_date else "N/A",
                ]
            )

        writer.writerow([])

        # --- Section 4: Top 25 Movies by Revenue ---
        writer.writerow(["TOP 25 MOVIES BY REVENUE"])
        writer.writerow(["Title", "Budget", "Revenue", "Rating", "Release Year"])
        for title, budget, revenue, rating, release_date in top_revenue:
            writer.writerow(
                [
                    title,
                    f"${budget:,}" if budget else "N/A",
                    f"${revenue:,}" if revenue else "N/A",
                    f"{rating:.1f}" if rating else "N/A",
                    release_date.year if release_date else "N/A",
                ]
            )

        output.seek(0)
        filename = f"movie_analytics_{datetime.utcnow().strftime('%Y%m%d')}.csv"

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        session.close()


@app.route("/search")
def search():
    """Search movies"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        query = request.args.get("q", "")

        if not query:
            return render_template(
                "search.html", movies=[], query="", current_user=user, config=Config
            )

        # Search in title and overview
        movies_list = (
            session.query(Movie)
            .filter((Movie.title.ilike(f"%{query}%")) | (Movie.overview.ilike(f"%{query}%")))
            .order_by(desc(Movie.popularity))
            .limit(50)
            .all()
        )

        return render_template(
            "search.html", movies=movies_list, query=query, current_user=user, config=Config
        )
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


# ==========================================
# RESTful API ENDPOINTS
# ==========================================


@app.route("/api/v1/movies", methods=["GET"])
@limiter.exempt
def api_get_movies():
    """Get list of movies with filtering and pagination"""
    session = get_db_session()
    try:
        # Get query parameters
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        genre_id = request.args.get("genre", type=int)
        sort_by = request.args.get("sort", default="popularity")
        year = request.args.get("year", type=int)
        min_rating = request.args.get("min_rating", type=float)
        min_vote_count = request.args.get("min_vote_count", type=int)
        status_filter = request.args.get("status", "")

        # Limit per_page to prevent abuse
        per_page = min(per_page, 100)

        # Base query
        query = session.query(Movie)

        # Apply filters
        if genre_id:
            query = query.join(Movie.genres).filter(Genre.id == genre_id)

        if year:
            query = query.filter(extract("year", Movie.release_date) == year)

        if min_rating is not None:
            query = query.filter(Movie.vote_average >= min_rating)

        if min_vote_count:
            query = query.filter(Movie.vote_count >= min_vote_count)

        if status_filter:
            query = query.filter(Movie.status == status_filter)

        # Apply sorting
        if sort_by == "rating":
            query = query.filter(Movie.vote_count > 50).order_by(desc(Movie.vote_average))
        elif sort_by == "release_date":
            query = query.filter(Movie.release_date.isnot(None)).order_by(desc(Movie.release_date))
        elif sort_by == "title":
            query = query.order_by(Movie.title)
        else:  # popularity
            query = query.order_by(desc(Movie.popularity))

        # Pagination
        total = query.count()
        offset = (page - 1) * per_page
        movies = query.limit(per_page).offset(offset).all()

        # Serialize movies
        movies_data = []
        for movie in movies:
            movies_data.append(
                {
                    "id": movie.id,
                    "tmdb_id": movie.tmdb_id,
                    "title": movie.title,
                    "original_title": movie.original_title,
                    "overview": movie.overview,
                    "release_date": movie.release_date.isoformat() if movie.release_date else None,
                    "runtime": movie.runtime,
                    "vote_average": float(movie.vote_average) if movie.vote_average else None,
                    "vote_count": movie.vote_count,
                    "popularity": float(movie.popularity) if movie.popularity else None,
                    "poster_path": movie.poster_path,
                    "backdrop_path": movie.backdrop_path,
                    "genres": [{"id": g.id, "name": g.name} for g in movie.genres],
                }
            )

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


@app.route("/api/v1/movies/<int:movie_id>", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def api_get_movie(movie_id):
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

        # Get average rating
        avg_rating = (
            session.query(func.avg(Rating.rating)).filter(Rating.movie_id == movie_id).scalar()
        )

        num_ratings = (
            session.query(func.count(Rating.id)).filter(Rating.movie_id == movie_id).scalar()
        )

        # Serialize movie data
        movie_data = {
            "id": movie.id,
            "tmdb_id": movie.tmdb_id,
            "title": movie.title,
            "original_title": movie.original_title,
            "overview": movie.overview,
            "release_date": movie.release_date.isoformat() if movie.release_date else None,
            "runtime": movie.runtime,
            "budget": movie.budget,
            "revenue": movie.revenue,
            "vote_average": float(movie.vote_average) if movie.vote_average else None,
            "vote_count": movie.vote_count,
            "popularity": float(movie.popularity) if movie.popularity else None,
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
                "average": float(avg_rating) if avg_rating else None,
                "count": num_ratings or 0,
            },
        }

        return jsonify(movie_data)
    finally:
        session.close()


@app.route("/api/v1/movies/search", methods=["GET"])
@limiter.limit("30 per minute")
def api_search_movies():
    """Search for movies by title"""
    session = get_db_session()
    try:
        query_text = request.args.get("q", "")
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)

        if not query_text:
            return jsonify({"error": "Query parameter 'q' is required"}), 400

        # Limit per_page
        per_page = min(per_page, 100)

        # Search query
        search_query = (
            session.query(Movie)
            .filter(
                (Movie.title.ilike(f"%{query_text}%")) | (Movie.overview.ilike(f"%{query_text}%"))
            )
            .order_by(desc(Movie.popularity))
        )

        total = search_query.count()
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
                    "release_date": movie.release_date.isoformat() if movie.release_date else None,
                    "vote_average": float(movie.vote_average) if movie.vote_average else None,
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


@app.route("/api/v1/genres", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def api_get_genres():
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


@app.route("/api/v1/analytics/overview", methods=["GET"])
@limiter.limit("100 per day")
@cache.cached(timeout=3600)
def api_analytics_overview():
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
                "average_rating": float(avg_rating) if avg_rating else None,
                "total_revenue": total_revenue or 0,
                "movies_by_year": [
                    {"year": int(year), "count": count} for year, count in movies_by_year
                ],
            }
        )
    finally:
        session.close()


@app.route("/api/v1/analytics/genres", methods=["GET"])
@limiter.limit("100 per day")
@cache.cached(timeout=3600)
def api_analytics_genres():
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
            .order_by(desc("count"))
            .all()
        )

        genres_data = [
            {
                "name": name,
                "movie_count": count,
                "average_rating": float(avg_rating) if avg_rating else None,
            }
            for name, count, avg_rating in genre_stats
        ]

        return jsonify({"genres": genres_data})
    finally:
        session.close()


@app.route("/api/v1/analytics/top-movies", methods=["GET"])
@limiter.limit("100 per day")
@cache.cached(timeout=3600, query_string=True)
def api_analytics_top_movies():
    """Get top movies by various metrics"""
    session = get_db_session()
    try:
        metric = request.args.get("metric", "rating")
        limit = request.args.get("limit", 10, type=int)
        limit = min(limit, 100)

        if metric == "rating":
            movies = (
                session.query(Movie)
                .filter(Movie.vote_count > 100)
                .order_by(desc(Movie.vote_average))
                .limit(limit)
                .all()
            )
        elif metric == "revenue":
            movies = (
                session.query(Movie)
                .filter(Movie.revenue > 0)
                .order_by(desc(Movie.revenue))
                .limit(limit)
                .all()
            )
        elif metric == "popularity":
            movies = session.query(Movie).order_by(desc(Movie.popularity)).limit(limit).all()
        else:
            return jsonify({"error": "Invalid metric. Use: rating, revenue, or popularity"}), 400

        movies_data = [
            {
                "id": movie.id,
                "title": movie.title,
                "vote_average": float(movie.vote_average) if movie.vote_average else None,
                "revenue": movie.revenue,
                "popularity": float(movie.popularity) if movie.popularity else None,
            }
            for movie in movies
        ]

        return jsonify({"metric": metric, "movies": movies_data})
    finally:
        session.close()


@app.route("/api/v1/actors", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def api_get_actors():
    """Get list of actors with pagination"""
    session = get_db_session()
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        per_page = min(per_page, 100)

        # Get actors with movie count
        actors_query = (
            session.query(Person, func.count(Cast.movie_id).label("movie_count"))
            .join(Cast, Person.id == Cast.person_id)
            .join(Movie, Cast.movie_id == Movie.id)
            .filter(Movie.vote_count > 20)
            .group_by(Person.id)
            .having(func.count(Cast.movie_id) >= 2)
            .order_by(desc("movie_count"))
        )

        total = actors_query.count()
        offset = (page - 1) * per_page
        actors = actors_query.limit(per_page).offset(offset).all()

        actors_data = [
            {
                "id": person.id,
                "name": person.name,
                "profile_path": person.profile_path,
                "movie_count": movie_count,
            }
            for person, movie_count in actors
        ]

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


@app.route("/api/v1/actors/<int:actor_id>", methods=["GET"])
@limiter.limit("200 per day; 50 per hour")
def api_get_actor(actor_id):
    """Get detailed information about an actor"""
    session = get_db_session()
    try:
        actor = session.query(Person).filter_by(id=actor_id).first()

        if not actor:
            return jsonify({"error": "Actor not found"}), 404

        # Get filmography
        filmography = (
            session.query(Movie, Cast)
            .join(Cast, Movie.id == Cast.movie_id)
            .filter(Cast.person_id == actor_id)
            .order_by(desc(Movie.release_date))
            .all()
        )

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
            "average_rating": float(avg_rating) if avg_rating else None,
            "filmography": [
                {
                    "movie_id": movie.id,
                    "title": movie.title,
                    "character": cast.character_name,
                    "release_date": movie.release_date.isoformat() if movie.release_date else None,
                    "vote_average": float(movie.vote_average) if movie.vote_average else None,
                }
                for movie, cast in filmography
            ],
        }

        return jsonify(actor_data)
    finally:
        session.close()


@app.route("/api/v1/health", methods=["GET"])
@limiter.exempt
def api_health():
    """Health check endpoint"""
    session = get_db_session()
    try:
        # Test database connection
        movie_count = session.query(func.count(Movie.id)).scalar()

        return jsonify({"status": "healthy", "database": "connected", "movie_count": movie_count})
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500
    finally:
        session.close()


@app.route("/api/v1/docs", methods=["GET"])
def api_docs():
    """API documentation"""
    docs = {
        "version": "1.0",
        "endpoints": {
            "movies": {
                "GET /api/v1/movies": {
                    "description": "Get list of movies with filtering and pagination",
                    "parameters": {
                        "page": "Page number (default: 1)",
                        "per_page": "Results per page (default: 20, max: 100)",
                        "genre": "Filter by genre ID",
                        "sort": "Sort by: popularity, rating, release_date, title",
                        "year": "Filter by release year",
                        "min_rating": "Minimum rating filter",
                    },
                },
                "GET /api/v1/movies/<id>": {
                    "description": "Get detailed information about a specific movie"
                },
                "GET /api/v1/movies/search": {
                    "description": "Search for movies by title",
                    "parameters": {
                        "q": "Search query (required)",
                        "page": "Page number",
                        "per_page": "Results per page",
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
                        "limit": "Number of results (max: 100)",
                    },
                },
            },
            "actors": {
                "GET /api/v1/actors": {"description": "Get list of actors with pagination"},
                "GET /api/v1/actors/<id>": {
                    "description": "Get detailed information about an actor"
                },
            },
            "system": {
                "GET /api/v1/health": {"description": "Health check endpoint"},
                "GET /api/v1/docs": {"description": "API documentation"},
            },
        },
    }

    return jsonify(docs)


# ==========================================
# DECADE OVERVIEW ROUTES
# ==========================================

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


@app.route("/decades")
def decades():
    """Decade overview index page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)

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
            .filter(Movie.vote_count > 0)
            .group_by("year")
            .all()
        )

        # Bucket by decade
        decade_buckets = {}
        for row in year_raw:
            if not row.year:
                continue
            ds = (int(row.year) // 10) * 10
            if ds not in decade_buckets:
                decade_buckets[ds] = {"movie_count": 0, "ratings": [], "total_revenue": 0}
            decade_buckets[ds]["movie_count"] += row.movie_count
            if row.avg_rating:
                decade_buckets[ds]["ratings"].append((float(row.avg_rating), row.movie_count))
            decade_buckets[ds]["total_revenue"] += row.total_revenue or 0

        # Fetch one representative backdrop per decade (highest popularity)
        decades_list = []
        for decade_start in sorted(decade_buckets.keys()):
            bucket = decade_buckets[decade_start]
            decade_end = decade_start + 9

            # Weighted average rating across years in this decade
            total_weighted = sum(r * c for r, c in bucket["ratings"])
            total_count = sum(c for _, c in bucket["ratings"])
            avg_rating = total_weighted / total_count if total_count else 0

            # Pick the most popular movie with a backdrop for the card image
            hero = (
                session_db.query(Movie)
                .filter(
                    Movie.release_date.isnot(None),
                    extract("year", Movie.release_date) >= decade_start,
                    extract("year", Movie.release_date) <= decade_end,
                    Movie.backdrop_path.isnot(None),
                    Movie.vote_count > 50,
                )
                .order_by(desc(Movie.popularity))
                .first()
            )

            decades_list.append(
                {
                    "decade_start": decade_start,
                    "decade_end": decade_end,
                    "label": f"{decade_start}s",
                    "movie_count": bucket["movie_count"],
                    "avg_rating": round(avg_rating, 1),
                    "total_revenue": bucket["total_revenue"],
                    "description": _DECADE_DESCRIPTIONS.get(decade_start, ""),
                    "hero_backdrop": hero.backdrop_path if hero else None,
                }
            )

        return render_template(
            "decades.html",
            decades=decades_list,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/decade/<int:decade_start>")
def decade_detail(decade_start):
    """Individual decade detail page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        decade_end = decade_start + 9

        # Validate decade
        if decade_start < 1900 or decade_start > datetime.now().year:
            return "Decade not found", 404

        base_query = session_db.query(Movie).filter(
            Movie.release_date.isnot(None),
            extract("year", Movie.release_date) >= decade_start,
            extract("year", Movie.release_date) <= decade_end,
            Movie.vote_count > 0,
        )

        total_movies = base_query.count()
        if total_movies == 0:
            return "No movies found for this decade", 404

        # Top rated (min 20 votes for reliability)
        top_rated = (
            base_query.filter(Movie.vote_count >= 20)
            .order_by(desc(Movie.vote_average))
            .limit(12)
            .all()
        )

        # Most popular
        most_popular = base_query.order_by(desc(Movie.popularity)).limit(12).all()

        # Defining films: high rating AND high popularity — the cultural touchstones
        defining_films = (
            base_query.filter(Movie.vote_count >= 50)
            .order_by(desc(Movie.popularity * Movie.vote_average))
            .limit(6)
            .all()
        )

        # Genre breakdown
        genre_stats = (
            session_db.query(
                Genre.name,
                func.count(Movie.id).label("count"),
            )
            .join(Movie.genres)
            .filter(
                Movie.release_date.isnot(None),
                extract("year", Movie.release_date) >= decade_start,
                extract("year", Movie.release_date) <= decade_end,
            )
            .group_by(Genre.name)
            .order_by(desc("count"))
            .all()
        )

        # Stats
        avg_rating = (
            session_db.query(func.avg(Movie.vote_average))
            .filter(
                Movie.release_date.isnot(None),
                extract("year", Movie.release_date) >= decade_start,
                extract("year", Movie.release_date) <= decade_end,
                Movie.vote_count >= 20,
            )
            .scalar()
        )
        total_revenue = (
            session_db.query(func.sum(Movie.revenue))
            .filter(
                Movie.release_date.isnot(None),
                extract("year", Movie.release_date) >= decade_start,
                extract("year", Movie.release_date) <= decade_end,
                Movie.revenue > 0,
            )
            .scalar()
        )

        # Movies by year (for chart)
        by_year = (
            session_db.query(
                extract("year", Movie.release_date).label("year"),
                func.count(Movie.id).label("count"),
                func.avg(Movie.vote_average).label("avg_rating"),
            )
            .filter(
                Movie.release_date.isnot(None),
                extract("year", Movie.release_date) >= decade_start,
                extract("year", Movie.release_date) <= decade_end,
            )
            .group_by("year")
            .order_by("year")
            .all()
        )

        stats = {
            "total_movies": total_movies,
            "avg_rating": round(float(avg_rating), 2) if avg_rating else 0,
            "total_revenue": total_revenue or 0,
            "top_genre": genre_stats[0].name if genre_stats else "N/A",
        }

        chart_data = {
            "years": [int(r.year) for r in by_year],
            "counts": [r.count for r in by_year],
            "ratings": [round(float(r.avg_rating), 2) if r.avg_rating else 0 for r in by_year],
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


# ==========================================
# PRODUCTION COMPANIES ROUTES
# ==========================================


@app.route("/companies")
def companies():
    """Production companies listing page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        page = request.args.get("page", 1, type=int)
        per_page = 24

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
            .group_by(
                ProductionCompany.id,
                ProductionCompany.name,
                ProductionCompany.logo_path,
                ProductionCompany.origin_country,
            )
            .having(func.count(Movie.id) >= 3)
            .order_by(desc("movie_count"))
        )

        total = companies_query.count()
        total_pages = (total + per_page - 1) // per_page
        companies_data = companies_query.limit(per_page).offset((page - 1) * per_page).all()

        companies_list = []
        for row in companies_data:
            top_movies = (
                session_db.query(Movie)
                .join(Movie.companies)
                .filter(ProductionCompany.id == row.id)
                .order_by(desc(Movie.vote_average))
                .limit(3)
                .all()
            )
            companies_list.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "logo_path": row.logo_path,
                    "origin_country": row.origin_country,
                    "movie_count": row.movie_count,
                    "avg_rating": float(row.avg_rating) if row.avg_rating else 0,
                    "total_revenue": row.total_revenue or 0,
                    "top_movies": [
                        {
                            "id": m.id,
                            "title": m.title,
                            "year": m.release_date.year if m.release_date else None,
                            "vote_average": float(m.vote_average) if m.vote_average else 0,
                        }
                        for m in top_movies
                    ],
                }
            )

        return render_template(
            "companies.html",
            companies=companies_list,
            page=page,
            total_pages=total_pages,
            total=total,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/company/<int:company_id>")
def company_detail(company_id):
    """Individual production company detail page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)

        company = session_db.query(ProductionCompany).filter_by(id=company_id).first()
        if not company:
            return "Production company not found", 404

        movies = (
            session_db.query(Movie)
            .join(Movie.companies)
            .filter(ProductionCompany.id == company_id)
            .filter(Movie.vote_count > 0)
            .order_by(desc(Movie.release_date))
            .all()
        )

        total_movies = len(movies)
        avg_rating = (
            sum(float(m.vote_average) for m in movies if m.vote_average) / total_movies
            if total_movies > 0
            else 0
        )
        total_revenue = sum(m.revenue or 0 for m in movies)

        years = [m.release_date.year for m in movies if m.release_date]
        first_year = min(years) if years else None
        last_year = max(years) if years else None
        years_active = (last_year - first_year + 1) if first_year and last_year else 0

        # Genre distribution
        genre_counts = {}
        for movie in movies:
            for genre in movie.genres:
                genre_counts[genre.name] = genre_counts.get(genre.name, 0) + 1
        genres = [
            {"name": name, "count": count}
            for name, count in sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)
        ]

        # Chart data by year
        year_data = {}
        for movie in movies:
            if movie.release_date:
                year = movie.release_date.year
                if year not in year_data:
                    year_data[year] = {"ratings": [], "revenues": []}
                if movie.vote_average:
                    year_data[year]["ratings"].append(float(movie.vote_average))
                year_data[year]["revenues"].append((movie.revenue or 0) / 1_000_000)

        chart_years = sorted(year_data.keys())
        chart_ratings = [
            (
                round(sum(year_data[y]["ratings"]) / len(year_data[y]["ratings"]), 2)
                if year_data[y]["ratings"]
                else 0
            )
            for y in chart_years
        ]
        chart_revenues = [round(sum(year_data[y]["revenues"]), 1) for y in chart_years]

        stats = {
            "total_movies": total_movies,
            "avg_rating": avg_rating,
            "total_revenue": total_revenue,
            "years_active": years_active,
            "first_year": first_year,
            "last_year": last_year,
            "genres": genres,
        }

        chart_data = {
            "years": chart_years,
            "ratings": chart_ratings,
            "revenues": chart_revenues,
        }

        movies_list = [
            {
                "id": m.id,
                "title": m.title,
                "year": m.release_date.year if m.release_date else None,
                "poster_path": m.poster_path,
                "vote_average": float(m.vote_average) if m.vote_average else 0,
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
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


# ==========================================
# COLLECTIONS ROUTES
# ==========================================


@app.route("/collections")
def collections():
    """User's collections listing page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your collections", "warning")
            return redirect(url_for("login", next=request.url))

        user_collections = (
            session_db.query(Collection)
            .filter_by(user_id=user.id)
            .order_by(desc(Collection.updated_at))
            .all()
        )

        return render_template(
            "collections.html",
            collections=user_collections,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/collections/create", methods=["POST"])
def create_collection():
    """Create a new collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("Collection name is required", "danger")
            return redirect(url_for("collections"))

        if len(name) > 255:
            flash("Collection name must be 255 characters or fewer", "danger")
            return redirect(url_for("collections"))

        collection = Collection(
            user_id=user.id,
            name=name,
            description=description or None,
        )
        session_db.add(collection)
        session_db.commit()

        flash(f'Collection "{name}" created', "success")
        return redirect(url_for("collection_detail", collection_id=collection.id))
    finally:
        session_db.close()


@app.route("/collection/<int:collection_id>")
def collection_detail(collection_id):
    """Individual collection detail page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view collections", "warning")
            return redirect(url_for("login", next=request.url))

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            flash("Collection not found", "danger")
            return redirect(url_for("collections"))

        # Paginate the movies in this collection
        page = request.args.get("page", 1, type=int)
        per_page = 24
        all_movies = collection.movies
        total = len(all_movies)
        total_pages = (total + per_page - 1) // per_page if total else 1
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page
        paged_movies = all_movies[offset : offset + per_page]

        return render_template(
            "collection_detail.html",
            collection=collection,
            movies=paged_movies,
            total=total,
            page=page,
            total_pages=total_pages,
            per_page=per_page,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/collection/<int:collection_id>/delete", methods=["POST"])
def delete_collection(collection_id):
    """Delete a collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            return jsonify({"error": "Collection not found"}), 404

        name = collection.name
        session_db.delete(collection)
        session_db.commit()

        flash(f'Collection "{name}" deleted', "success")
        return redirect(url_for("collections"))
    finally:
        session_db.close()


@app.route("/collection/<int:collection_id>/add/<int:movie_id>", methods=["POST"])
def add_to_collection(collection_id, movie_id):
    """Add a movie to a collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            return jsonify({"error": "Collection not found"}), 404

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        if movie not in collection.movies:
            collection.movies.append(movie)
            collection.updated_at = datetime.utcnow()
            session_db.commit()
            return jsonify({"status": "added", "count": len(collection.movies)})

        return jsonify({"status": "already_added", "count": len(collection.movies)})
    finally:
        session_db.close()


@app.route("/collection/<int:collection_id>/remove/<int:movie_id>", methods=["POST"])
def remove_from_collection(collection_id, movie_id):
    """Remove a movie from a collection"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        collection = (
            session_db.query(Collection).filter_by(id=collection_id, user_id=user.id).first()
        )
        if not collection:
            return jsonify({"error": "Collection not found"}), 404

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        if movie in collection.movies:
            collection.movies.remove(movie)
            collection.updated_at = datetime.utcnow()
            session_db.commit()
            return jsonify({"status": "removed", "count": len(collection.movies)})

        return jsonify({"status": "not_found"})
    finally:
        session_db.close()


@app.route("/api/v1/collections", methods=["GET"])
@limiter.limit("100 per hour")
def api_get_collections():
    """Get current user's collections"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        user_collections = (
            session_db.query(Collection)
            .filter_by(user_id=user.id)
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
                        "movie_count": len(c.movies),
                        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                    }
                    for c in user_collections
                ]
            }
        )
    finally:
        session_db.close()


# ==========================================
# USER PROFILE ROUTE
# ==========================================


@app.route("/profile")
def profile():
    """User profile page showing stats, ratings, reviews, favorites and watchlist"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your profile", "warning")
            return redirect(url_for("login", next=request.url))

        # Favorites and watchlist
        favorites = user.favorites.all()
        watchlist = user.watchlist.all()

        # Ratings with associated movie
        ratings = (
            session_db.query(Rating, Movie)
            .join(Movie, Rating.movie_id == Movie.id)
            .filter(Rating.user_id == user.id)
            .order_by(desc(Rating.updated_at))
            .all()
        )

        # Reviews with associated movie
        reviews = (
            session_db.query(Review, Movie)
            .join(Movie, Review.movie_id == Movie.id)
            .filter(Review.user_id == user.id)
            .order_by(desc(Review.created_at))
            .all()
        )

        # Summary stats
        avg_user_rating = (
            session_db.query(func.avg(Rating.rating)).filter(Rating.user_id == user.id).scalar()
        )

        stats = {
            "favorites_count": len(favorites),
            "watchlist_count": len(watchlist),
            "ratings_count": len(ratings),
            "reviews_count": len(reviews),
            "avg_rating": round(float(avg_user_rating), 1) if avg_user_rating else None,
        }

        return render_template(
            "profile.html",
            current_user=user,
            favorites=favorites,
            watchlist=watchlist,
            ratings=ratings,
            reviews=reviews,
            stats=stats,
            config=Config,
        )
    finally:
        session_db.close()


@app.route("/compare")
def compare():
    """Movie comparison page"""
    session = get_db_session()
    try:
        user = get_current_user(session)
        ids = request.args.getlist("id", type=int)
        ids = ids[:4]  # cap at 4

        movies_list = []
        if ids:
            movies_list = session.query(Movie).filter(Movie.id.in_(ids)).all()
            # Preserve request order
            id_order = {mid: i for i, mid in enumerate(ids)}
            movies_list = sorted(movies_list, key=lambda m: id_order.get(m.id, 999))

        # For each movie, find the director
        directors = {}
        for movie in movies_list:
            director = (
                session.query(Person)
                .join(Crew, Person.id == Crew.person_id)
                .filter(Crew.movie_id == movie.id, Crew.job == "Director")
                .first()
            )
            directors[movie.id] = director

        return render_template(
            "compare.html",
            movies=movies_list,
            directors=directors,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


# ==========================================
# ACTOR COLLABORATION NETWORK ROUTE
# ==========================================


@app.route("/actor/<int:actor_id>/network")
def actor_network(actor_id):
    """Collaboration network for a given actor.

    Nodes  = the focal actor + everyone who has shared at least one movie with them.
    Edges  = (actor_a, actor_b, shared_movie_count) for every collaborating pair,
             including edges between collaborators themselves (second-ring links).
    Capped at 30 collaborators so the graph stays readable.
    """
    session = get_db_session()
    try:
        user = get_current_user(session)

        actor = session.query(Person).filter_by(id=actor_id).first()
        if not actor:
            return "Actor not found", 404

        # ── Step 1: movies the focal actor appeared in ──────────────────────
        focal_movie_ids = [
            row.movie_id
            for row in session.query(Cast.movie_id).filter(Cast.person_id == actor_id).all()
        ]

        if not focal_movie_ids:
            return render_template(
                "actor_network.html",
                actor=actor,
                graph_data={"nodes": [], "links": []},
                collaborator_count=0,
                current_user=user,
                config=Config,
            )

        # ── Step 2: direct collaborators (other actors in the same movies) ──
        from sqlalchemy.orm import aliased

        collaborators_raw = (
            session.query(
                Person.id,
                Person.name,
                Person.profile_path,
                func.count(func.distinct(Cast.movie_id)).label("shared_movies"),
            )
            .join(Cast, Person.id == Cast.person_id)
            .filter(
                Cast.movie_id.in_(focal_movie_ids),
                Person.id != actor_id,
            )
            .group_by(Person.id, Person.name, Person.profile_path)
            .order_by(desc("shared_movies"))
            .limit(30)
            .all()
        )

        if not collaborators_raw:
            return render_template(
                "actor_network.html",
                actor=actor,
                graph_data={"nodes": [], "links": []},
                collaborator_count=0,
                current_user=user,
                config=Config,
            )

        collab_ids = [r.id for r in collaborators_raw]

        # ── Step 3: edges between collaborators (second-ring links) ─────────
        # Find movies shared between any two collaborators (excluding focal actor)
        c1 = aliased(Cast)
        c2 = aliased(Cast)
        collab_edges_raw = (
            session.query(
                c1.person_id.label("actor_a"),
                c2.person_id.label("actor_b"),
                func.count(func.distinct(c1.movie_id)).label("shared"),
            )
            .join(c2, c1.movie_id == c2.movie_id)
            .filter(
                c1.person_id.in_(collab_ids),
                c2.person_id.in_(collab_ids),
                c1.person_id < c2.person_id,  # avoid duplicates
            )
            .group_by(c1.person_id, c2.person_id)
            .having(func.count(func.distinct(c1.movie_id)) >= 1)
            .all()
        )

        # ── Step 4: build D3-ready graph data ────────────────────────────────
        # Build a lookup: (person_id) -> set of movie_ids for focal actor
        focal_movie_set = set(focal_movie_ids)

        # Build movie title lookup
        all_relevant_ids = focal_movie_ids.copy()
        # Also gather movie ids for collab-collab edges
        collab_movie_ids = [
            row.movie_id
            for row in session.query(Cast.movie_id).filter(Cast.person_id.in_(collab_ids)).all()
        ]
        all_relevant_ids = list(set(all_relevant_ids + collab_movie_ids))

        movies_lookup = {
            m.id: m.title
            for m in session.query(Movie.id, Movie.title)
            .filter(Movie.id.in_(all_relevant_ids))
            .all()
        }

        # Build per-person movie_id sets for shared title resolution
        person_movie_sets = {}
        for row in (
            session.query(Cast.person_id, Cast.movie_id)
            .filter(Cast.person_id.in_(collab_ids + [actor_id]))
            .all()
        ):
            person_movie_sets.setdefault(row.person_id, set()).add(row.movie_id)

        nodes = [
            {
                "id": actor.id,
                "name": actor.name,
                "profile_path": actor.profile_path,
                "shared_movies": 0,
                "focal": True,
            }
        ]
        for r in collaborators_raw:
            nodes.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "profile_path": r.profile_path,
                    "shared_movies": r.shared_movies,
                    "focal": False,
                }
            )

        # Focal-actor → collaborator edges with movie titles
        links = []
        for r in collaborators_raw:
            shared_ids = focal_movie_set & person_movie_sets.get(r.id, set())
            links.append(
                {
                    "source": actor.id,
                    "target": r.id,
                    "value": r.shared_movies,
                    "movies": [movies_lookup[mid] for mid in shared_ids if mid in movies_lookup],
                }
            )

        # Collaborator → collaborator edges with movie titles
        for edge in collab_edges_raw:
            shared_ids = person_movie_sets.get(edge.actor_a, set()) & person_movie_sets.get(
                edge.actor_b, set()
            )
            links.append(
                {
                    "source": edge.actor_a,
                    "target": edge.actor_b,
                    "value": edge.shared,
                    "movies": [movies_lookup[mid] for mid in shared_ids if mid in movies_lookup],
                }
            )

        graph_data = {"nodes": nodes, "links": links}

        return render_template(
            "actor_network.html",
            actor=actor,
            graph_data=graph_data,
            collaborator_count=len(collaborators_raw),
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


# ==========================================
# ADVANCED SEARCH ROUTE
# ==========================================


@app.route("/advanced-search")
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
        page = request.args.get("page", default=1, type=int)
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
            query = session.query(Movie)

            # Text search across title and overview
            if q:
                query = query.filter(
                    (Movie.title.ilike(f"%{q}%")) | (Movie.overview.ilike(f"%{q}%"))
                )

            # Genre
            if genre_id:
                query = query.join(Movie.genres).filter(Genre.id == genre_id)

            # Decade takes precedence over single year when both are set
            if decade:
                query = query.filter(
                    extract("year", Movie.release_date) >= decade,
                    extract("year", Movie.release_date) <= decade + 9,
                )
            elif year:
                query = query.filter(extract("year", Movie.release_date) == year)

            # Rating range
            if rating_min is not None:
                query = query.filter(Movie.vote_average >= rating_min)
            if rating_max is not None:
                query = query.filter(Movie.vote_average <= rating_max)

            # Runtime range
            if runtime_min is not None:
                query = query.filter(Movie.runtime >= runtime_min)
            if runtime_max is not None:
                query = query.filter(Movie.runtime <= runtime_max)

            # Minimum vote count
            if min_votes is not None:
                query = query.filter(Movie.vote_count >= min_votes)

            # Sorting
            if sort_by == "rating":
                query = query.order_by(desc(Movie.vote_average))
            elif sort_by == "release_date":
                query = query.filter(Movie.release_date.isnot(None)).order_by(
                    desc(Movie.release_date)
                )
            elif sort_by == "title":
                query = query.order_by(Movie.title)
            elif sort_by == "runtime":
                query = query.filter(Movie.runtime.isnot(None)).order_by(Movie.runtime)
            else:  # relevance / popularity default
                query = query.order_by(desc(Movie.popularity))

            total = query.count()
            total_pages = (total + per_page - 1) // per_page
            movies_list = query.limit(per_page).offset((page - 1) * per_page).all()

        # Sidebar data
        all_genres = session.query(Genre).order_by(Genre.name).all()
        current_year = datetime.now().year
        available_decades = list(range(1920, current_year + 1, 10))

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


if __name__ == "__main__":
    app.run(debug=True)
