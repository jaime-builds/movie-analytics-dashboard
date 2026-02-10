from datetime import datetime
from typing import Dict, Optional

from flask import Flask, flash, jsonify, redirect, render_template, request
from flask import session as flask_session
from flask import url_for
from sqlalchemy import and_, desc, extract, func, select

from config.config import Config
from src.models import (
    Cast,
    Crew,
    Genre,
    Movie,
    Person,
    ProductionCompany,
    Session,
    User,
    movie_genres_table,
)
from src.tmdb_api import TMDBClient

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY


def get_db_session():
    """Get a new database session"""
    return Session()


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
                flash(f"Welcome back, {username}!", "success")

                # Redirect to 'next' page if it exists, otherwise home
                next_page = request.args.get("next")
                return redirect(next_page if next_page else url_for("index"))

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
# DIRECTOR ROUTES (NEW!)
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
# EXISTING ROUTES (UPDATED WITH current_user)
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

        return render_template(
            "index.html",
            top_movies=top_movies,
            recent_movies=recent_movies,
            popular_movies=popular_movies,
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
    """Movie detail page"""
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

        # Check if movie is in user's favorites/watchlist
        is_favorited = False
        is_in_watchlist = False
        if user:
            is_favorited = movie in user.favorites.all()
            is_in_watchlist = movie in user.watchlist.all()

        return render_template(
            "movie_detail.html",
            movie=movie,
            cast=cast,
            directors=directors,
            similar_movies=similar_movies,
            trailer=trailer,
            current_user=user,
            is_favorited=is_favorited,
            is_in_watchlist=is_in_watchlist,
            config=Config,
        )
    finally:
        session.close()


@app.route("/analytics")
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

        # Get top 10 movies with budget/revenue data
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
            current_user=user,
            config=Config,
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


if __name__ == "__main__":
    app.run(debug=True)
