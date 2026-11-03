"""Saved lists, ratings, reviews, profile, the activity feed and year in review."""

from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import desc, extract, func, literal, select, union_all
from sqlalchemy.orm import selectinload

from config.config import Config
from src.featured import get_personalized_recommendations
from src.helpers import (
    MAX_REVIEW_LENGTH,
    _association_exists,
    _current_relative_url,
    _html_page_arg,
    _insert_association,
    _public_rating_stats,
    family_friendly_enabled,
    get_current_user,
    get_db_session,
)
from src.models import (
    Movie,
    Rating,
    Review,
    User,
    user_favorites_table,
    user_watchlist_table,
    utcnow,
)

bp = Blueprint("account", __name__)


def _user_list_movies(session_db, table, user_id):
    """A user's favorites or watchlist, newest additions first, genres preloaded."""
    return (
        session_db.query(Movie)
        .join(table, table.c.movie_id == Movie.id)
        .filter(table.c.user_id == user_id)
        .options(selectinload(Movie.genres))
        .order_by(desc(table.c.added_at).nulls_last(), Movie.title, Movie.id)
        .all()
    )


@bp.route("/favorites")
def favorites():
    """Display user's favorite movies"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your favorites", "warning")
            return redirect(url_for("auth.login", next=_current_relative_url()))

        favorites = _user_list_movies(session_db, user_favorites_table, user.id)

        return render_template(
            "favorites.html", favorites=favorites, current_user=user, config=Config
        )
    finally:
        session_db.close()


@bp.route("/watchlist")
def watchlist():
    """Display user's watchlist"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your watchlist", "warning")
            return redirect(url_for("auth.login", next=_current_relative_url()))

        watchlist = _user_list_movies(session_db, user_watchlist_table, user.id)

        return render_template(
            "watchlist.html", watchlist=watchlist, current_user=user, config=Config
        )
    finally:
        session_db.close()


def _toggle_user_list(movie_id, table, add):
    """Add a movie to, or remove it from, the user's favorites or watchlist."""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            return jsonify({"error": "Movie not found"}), 404

        present = _association_exists(session_db, table, user_id=user.id, movie_id=movie.id)
        if add:
            if not present and _insert_association(
                session_db, table, user_id=user.id, movie_id=movie.id
            ):
                return jsonify({"status": "added"})
            return jsonify({"status": "already_added"})

        if present:
            session_db.execute(
                table.delete().where(table.c.user_id == user.id, table.c.movie_id == movie.id)
            )
            session_db.commit()
            return jsonify({"status": "removed"})
        return jsonify({"status": "not_found"})
    finally:
        session_db.close()


@bp.route("/movie/<int:movie_id>/favorite", methods=["POST"])
def add_favorite(movie_id):
    return _toggle_user_list(movie_id, user_favorites_table, add=True)


@bp.route("/movie/<int:movie_id>/unfavorite", methods=["POST"])
def remove_favorite(movie_id):
    return _toggle_user_list(movie_id, user_favorites_table, add=False)


@bp.route("/movie/<int:movie_id>/watchlist", methods=["POST"])
def add_watchlist(movie_id):
    return _toggle_user_list(movie_id, user_watchlist_table, add=True)


@bp.route("/movie/<int:movie_id>/unwatchlist", methods=["POST"])
def remove_watchlist(movie_id):
    return _toggle_user_list(movie_id, user_watchlist_table, add=False)


@bp.route("/movie/<int:movie_id>/rate", methods=["POST"])
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

        # Check if user already rated this movie. Soft-deleted rows are
        # included: the unique (user, movie) index means a moderated rating
        # would otherwise be silently overwritten and stay hidden.
        existing_rating = (
            session_db.query(Rating).filter_by(user_id=user.id, movie_id=movie_id).first()
        )

        if existing_rating and existing_rating.is_deleted:
            return jsonify({"error": "This rating was removed by a moderator"}), 403

        if existing_rating:
            # Update existing rating
            existing_rating.rating = rating_value
            flash(f"Your rating has been updated to {rating_value} stars", "success")
        else:
            # Create new rating
            new_rating = Rating(user_id=user.id, movie_id=movie_id, rating=rating_value)
            session_db.add(new_rating)
            flash(f"You rated this movie {rating_value} stars", "success")

        session_db.commit()

        # Calculate new average rating (publicly visible ratings only)
        avg_rating, num_ratings = _public_rating_stats(session_db, movie_id)

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


@bp.route("/movie/<int:movie_id>/review", methods=["POST"])
def submit_review(movie_id):
    """Submit a review for a movie"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to submit a review", "warning")
            return redirect(url_for("auth.login", next=_current_relative_url()))

        review_content = request.form.get("review_content", "").strip()

        # Validate review content
        if not review_content:
            flash("Review cannot be empty", "danger")
            return redirect(url_for("main.movie_detail", movie_id=movie_id))

        if len(review_content) < 10:
            flash("Review must be at least 10 characters long", "danger")
            return redirect(url_for("main.movie_detail", movie_id=movie_id))

        if len(review_content) > MAX_REVIEW_LENGTH:
            flash(f"Review must be {MAX_REVIEW_LENGTH} characters or fewer", "danger")
            return redirect(url_for("main.movie_detail", movie_id=movie_id))

        movie = session_db.query(Movie).filter_by(id=movie_id).first()
        if not movie:
            flash("Movie not found", "danger")
            return redirect(url_for("main.index"))

        # Check if user already reviewed this movie. Soft-deleted rows are
        # included: the unique (user, movie) constraint means a moderated
        # review would otherwise be silently overwritten and stay hidden.
        existing_review = (
            session_db.query(Review).filter_by(user_id=user.id, movie_id=movie_id).first()
        )

        if existing_review and existing_review.is_deleted:
            flash("This review was removed by a moderator and cannot be edited.", "danger")
            return redirect(url_for("main.movie_detail", movie_id=movie_id))

        if existing_review:
            # Update existing review
            existing_review.content = review_content
            flash("Your review has been updated", "success")
        else:
            # Create new review
            new_review = Review(user_id=user.id, movie_id=movie_id, content=review_content)
            session_db.add(new_review)
            flash("Your review has been submitted", "success")

        session_db.commit()
        return redirect(url_for("main.movie_detail", movie_id=movie_id))
    finally:
        session_db.close()


@bp.route("/movie/<int:movie_id>/review/<int:review_id>/delete", methods=["POST"])
def delete_review(movie_id, review_id):
    """Delete a review"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        review = session_db.query(Review).filter_by(id=review_id, movie_id=movie_id).first()

        if not review:
            return jsonify({"error": "Review not found"}), 404

        # Check if user owns this review
        if review.user_id != user.id:
            return jsonify({"error": "Unauthorized"}), 403

        # A moderated review stays as the moderator left it; deleting it would
        # let the author wipe the record and post a fresh one
        if review.is_deleted:
            return jsonify({"error": "This review was removed by a moderator"}), 403

        session_db.delete(review)
        session_db.commit()

        flash("Review deleted successfully", "success")
        return jsonify({"status": "deleted"})
    finally:
        session_db.close()


@bp.route("/recommendations")
def recommendations():
    """User's personalized recommendations page"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to see personalized recommendations", "warning")
            return redirect(url_for("auth.login", next=_current_relative_url()))

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


@bp.route("/profile")
def profile():
    """User profile page showing stats, ratings, reviews, favorites and watchlist"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to view your profile", "warning")
            return redirect(url_for("auth.login", next=_current_relative_url()))

        # Favorites and watchlist
        favorites = _user_list_movies(session_db, user_favorites_table, user.id)
        watchlist = _user_list_movies(session_db, user_watchlist_table, user.id)

        # Ratings with associated movie (moderated rows stay hidden)
        ratings = (
            session_db.query(Rating, Movie)
            .join(Movie, Rating.movie_id == Movie.id)
            .filter(Rating.user_id == user.id, Rating.is_deleted.is_(False))
            .order_by(desc(Rating.updated_at))
            .all()
        )

        # Reviews with associated movie (moderated rows stay hidden)
        reviews = (
            session_db.query(Review, Movie)
            .join(Movie, Review.movie_id == Movie.id)
            .filter(Review.user_id == user.id, Review.is_deleted.is_(False))
            .order_by(desc(Review.created_at))
            .all()
        )

        # Summary stats
        avg_user_rating = (
            session_db.query(func.avg(Rating.rating))
            .filter(Rating.user_id == user.id, Rating.is_deleted.is_(False))
            .scalar()
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


ACTIVITY_PER_PAGE = 30

ACTIVITY_REVIEW_PREVIEW_CHARS = 200


def _activity_page(session_db, page, per_page):
    """Recent public ratings and reviews, newest first, as (total, items).

    Leaves out moderated content, banned users, users who opted out, and
    movies flagged mature when the family-friendly toggle is on.
    """
    shared_filters = [User.is_banned.is_(False), User.hide_activity.is_(False)]
    if family_friendly_enabled():
        shared_filters.append(Movie.is_mature.is_(False))

    ratings = (
        select(
            literal("rating").label("kind"),
            Rating.id.label("item_id"),
            Rating.created_at.label("at"),
        )
        .join(User, Rating.user_id == User.id)
        .join(Movie, Rating.movie_id == Movie.id)
        .where(Rating.is_deleted.is_(False), *shared_filters)
    )
    reviews = (
        select(
            literal("review").label("kind"),
            Review.id.label("item_id"),
            Review.created_at.label("at"),
        )
        .join(User, Review.user_id == User.id)
        .join(Movie, Review.movie_id == Movie.id)
        .where(Review.is_deleted.is_(False), *shared_filters)
    )
    feed = union_all(ratings, reviews).subquery()

    total = session_db.execute(select(func.count()).select_from(feed)).scalar() or 0
    rows = session_db.execute(
        select(feed.c.kind, feed.c.item_id, feed.c.at)
        .order_by(desc(feed.c.at), feed.c.kind, desc(feed.c.item_id))
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).all()

    rating_ids = [r.item_id for r in rows if r.kind == "rating"]
    review_ids = [r.item_id for r in rows if r.kind == "review"]
    loaded = {}
    if rating_ids:
        for rating, user, movie in (
            session_db.query(Rating, User, Movie)
            .join(User, Rating.user_id == User.id)
            .join(Movie, Rating.movie_id == Movie.id)
            .filter(Rating.id.in_(rating_ids))
        ):
            loaded[("rating", rating.id)] = {
                "kind": "rating",
                "username": user.username,
                "movie": movie,
                "stars": rating.rating,
                "at": rating.created_at,
            }
    if review_ids:
        for review, user, movie in (
            session_db.query(Review, User, Movie)
            .join(User, Review.user_id == User.id)
            .join(Movie, Review.movie_id == Movie.id)
            .filter(Review.id.in_(review_ids))
        ):
            loaded[("review", review.id)] = {
                "kind": "review",
                "username": user.username,
                "movie": movie,
                "text": review.content,
                "at": review.created_at,
            }

    items = [loaded[(r.kind, r.item_id)] for r in rows if (r.kind, r.item_id) in loaded]
    return total, items


@bp.route("/activity")
def activity_feed():
    """Public feed of recent ratings and reviews across all users"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        page = _html_page_arg()
        total, items = _activity_page(session_db, page, ACTIVITY_PER_PAGE)
        total_pages = (total + ACTIVITY_PER_PAGE - 1) // ACTIVITY_PER_PAGE if total else 1

        return render_template(
            "activity_feed.html",
            items=items,
            page=min(page, total_pages),
            total_pages=total_pages,
            total=total,
            preview_chars=ACTIVITY_REVIEW_PREVIEW_CHARS,
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()


@bp.route("/profile/activity-visibility", methods=["POST"])
def set_activity_visibility():
    """Show or hide the logged-in user's ratings and reviews in the public feed"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to change this setting", "warning")
            return redirect(url_for("auth.login", next=url_for("account.profile")))

        requested = request.form.get("hidden", "").strip().lower()
        if requested in ("true", "false"):
            user.hide_activity = requested == "true"
            session_db.commit()
            if user.hide_activity:
                flash(
                    "Your ratings and reviews are now hidden from the activity feed.",
                    "success",
                )
            else:
                flash(
                    "Your ratings and reviews now appear in the activity feed.",
                    "success",
                )
        return redirect(url_for("account.profile"))
    finally:
        session_db.close()


@bp.route("/watchlist/blind-pick")
def blind_pick():
    """Jump to a random movie from the user's watchlist"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to use Blind Pick", "warning")
            return redirect(url_for("auth.login", next=url_for("account.watchlist")))

        movie_id = (
            session_db.query(user_watchlist_table.c.movie_id)
            .filter(user_watchlist_table.c.user_id == user.id)
            .order_by(func.random())
            .limit(1)
            .scalar()
        )
        if movie_id is None:
            flash(
                "Your watchlist is empty. Add a few movies first, then try Blind Pick.",
                "info",
            )
            return redirect(url_for("account.watchlist"))

        flash("Blind pick from your watchlist. Enjoy the movie!", "success")
        return redirect(url_for("main.movie_detail", movie_id=movie_id))
    finally:
        session_db.close()


def _year_bounds(year):
    return datetime(year, 1, 1), datetime(year + 1, 1, 1)


def _activity_years(session_db, user_id):
    """Years (newest first) in which the user rated, reviewed or saved anything."""
    years = set()
    for column, owner in (
        (Rating.created_at, Rating.user_id),
        (Review.created_at, Review.user_id),
        (user_favorites_table.c.added_at, user_favorites_table.c.user_id),
        (user_watchlist_table.c.added_at, user_watchlist_table.c.user_id),
    ):
        for (year,) in (
            session_db.query(extract("year", column))
            .filter(owner == user_id, column.isnot(None))
            .distinct()
            .all()
        ):
            if year:
                years.add(int(year))
    return sorted(years, reverse=True)


def _year_in_review_stats(session_db, user, year):
    start, end = _year_bounds(year)

    ratings = (
        session_db.query(Rating, Movie)
        .join(Movie, Rating.movie_id == Movie.id)
        .filter(
            Rating.user_id == user.id,
            Rating.is_deleted.is_(False),
            Rating.created_at >= start,
            Rating.created_at < end,
        )
        .options(selectinload(Movie.genres))
        .order_by(desc(Rating.rating), desc(Movie.vote_average), Movie.id)
        .all()
    )
    reviews_count = (
        session_db.query(func.count(Review.id))
        .filter(
            Review.user_id == user.id,
            Review.is_deleted.is_(False),
            Review.created_at >= start,
            Review.created_at < end,
        )
        .scalar()
        or 0
    )
    favorites = (
        session_db.query(Movie)
        .join(user_favorites_table, user_favorites_table.c.movie_id == Movie.id)
        .filter(
            user_favorites_table.c.user_id == user.id,
            user_favorites_table.c.added_at >= start,
            user_favorites_table.c.added_at < end,
        )
        .options(selectinload(Movie.genres))
        .all()
    )
    watchlist_added = (
        session_db.query(func.count())
        .select_from(user_watchlist_table)
        .filter(
            user_watchlist_table.c.user_id == user.id,
            user_watchlist_table.c.added_at >= start,
            user_watchlist_table.c.added_at < end,
        )
        .scalar()
        or 0
    )

    # Genres and decades across everything rated or favorited this year,
    # counting a movie once even if it was both
    unique_movies = {movie.id: movie for movie in [m for _, m in ratings] + favorites}
    genre_counts = {}
    decade_counts = {}
    for movie in unique_movies.values():
        for genre in movie.genres:
            genre_counts[genre.name] = genre_counts.get(genre.name, 0) + 1
        if movie.release_date:
            decade = (movie.release_date.year // 10) * 10
            decade_counts[decade] = decade_counts.get(decade, 0) + 1
    top_genres = sorted(genre_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    favorite_decade = (
        max(decade_counts.items(), key=lambda item: (item[1], item[0]))[0]
        if decade_counts
        else None
    )

    rating_values = [rating.rating for rating, _ in ratings]
    distribution = [rating_values.count(stars) for stars in range(1, 6)]
    months = [0] * 12
    for rating, _ in ratings:
        months[rating.created_at.month - 1] += 1

    return {
        "ratings_count": len(ratings),
        "reviews_count": reviews_count,
        "favorites_count": len(favorites),
        "watchlist_added": watchlist_added,
        "avg_given": round(sum(rating_values) / len(rating_values), 1) if rating_values else None,
        "rating_distribution": distribution,
        "monthly_ratings": months,
        "top_genres": top_genres,
        "favorite_decade": favorite_decade,
        "runtime_minutes": sum(movie.runtime or 0 for _, movie in ratings),
        "top_rated": [movie for rating, movie in ratings if rating.rating >= 4][:6],
        "has_activity": bool(ratings or reviews_count or favorites or watchlist_added),
    }


@bp.route("/year-in-review")
def year_in_review():
    """Personal stats for one calendar year: ratings, reviews, favorites, genres"""
    session_db = get_db_session()
    try:
        user = get_current_user(session_db)
        if not user:
            flash("Please log in to see your Year in Review", "warning")
            return redirect(url_for("auth.login", next=_current_relative_url()))

        years = _activity_years(session_db, user.id)
        current_year = utcnow().year
        year = request.args.get("year", type=int) or (years[0] if years else current_year)
        if year < 1900 or year > current_year:
            abort(404)

        return render_template(
            "year_in_review.html",
            year=year,
            years=sorted(set(years) | {current_year}, reverse=True),
            stats=_year_in_review_stats(session_db, user, year),
            current_user=user,
            config=Config,
        )
    finally:
        session_db.close()
