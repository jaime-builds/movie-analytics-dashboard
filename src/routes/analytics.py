"""Analytics dashboard and its CSV export."""

import csv
import io

from flask import Blueprint, Response, render_template
from sqlalchemy import case, desc, extract, func

from config.config import Config
from src.extensions import limiter
from src.helpers import _cached, get_current_user, get_db_session
from src.models import Genre, Movie, ProductionCompany, utcnow

bp = Blueprint("analytics", __name__)


# A movie counts toward a rating average once it has this many votes
ANALYTICS_MIN_VOTES = 50


def _number(value, digits=None):
    """Plain float (rounded) or None, so cached data and JSON never carry Decimal."""
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if digits is not None else value


def _analytics_data(session):
    """Every aggregate on /analytics, as plain data, cached between syncs."""

    def compute():
        genre_stats = [
            {"name": name, "count": count}
            for name, count in session.query(Genre.name, func.count(Movie.id).label("count"))
            .join(Movie.genres)
            .group_by(Genre.name)
            .order_by(desc("count"), Genre.name)
            .all()
        ]

        year_stats = [
            {"year": int(year), "count": count}
            for year, count in session.query(
                extract("year", Movie.release_date).label("year"),
                func.count(Movie.id).label("count"),
            )
            .filter(Movie.release_date.isnot(None))
            .group_by("year")
            .order_by("year")
            .all()
        ]

        genre_ratings = [
            {"name": name, "avg_rating": _number(avg, 2), "count": count}
            for name, avg, count in session.query(
                Genre.name,
                func.avg(Movie.vote_average).label("avg_rating"),
                func.count(Movie.id).label("count"),
            )
            .join(Movie.genres)
            .filter(Movie.vote_count > ANALYTICS_MIN_VOTES)
            .group_by(Genre.name)
            .having(func.count(Movie.id) >= 3)
            .order_by(desc("avg_rating"), Genre.name)
            .all()
        ]

        # Box office by genre: a movie with several genres counts toward each
        box_office_by_genre = [
            {
                "name": name,
                "total_revenue": int(total or 0),
                "avg_revenue": int(avg or 0),
                "count": count,
            }
            for name, total, avg, count in session.query(
                Genre.name,
                func.sum(Movie.revenue).label("total_revenue"),
                func.avg(Movie.revenue).label("avg_revenue"),
                func.count(Movie.id).label("count"),
            )
            .join(Movie.genres)
            .filter(Movie.revenue > 0)
            .group_by(Genre.name)
            .order_by(desc("total_revenue"), Genre.name)
            .all()
        ]

        # Budget vs revenue scatter data (up to 300 movies with known budget)
        budget_revenue_scatter = [
            [title, budget, revenue, _number(rating)]
            for title, budget, revenue, rating in session.query(
                Movie.title, Movie.budget, Movie.revenue, Movie.vote_average
            )
            .filter(Movie.budget > 1_000_000, Movie.revenue > 0)
            .order_by(desc(Movie.revenue), Movie.id)
            .limit(300)
            .all()
        ]

        # Most profitable movies (revenue - budget), top 15
        most_profitable = [
            [title, budget, revenue]
            for title, budget, revenue in session.query(Movie.title, Movie.budget, Movie.revenue)
            .filter(Movie.budget > 1_000_000, Movie.revenue > 0)
            .order_by(desc(Movie.revenue - Movie.budget), Movie.id)
            .limit(15)
            .all()
        ]

        # Top production companies (grouped by id: names aren't unique)
        top_companies = [
            {"name": name, "movie_count": count, "avg_rating": _number(avg, 2)}
            for _, name, count, avg in session.query(
                ProductionCompany.id,
                ProductionCompany.name,
                func.count(Movie.id).label("movie_count"),
                func.avg(Movie.vote_average).label("avg_rating"),
            )
            .join(ProductionCompany.movies)
            .filter(Movie.vote_count > ANALYTICS_MIN_VOTES)
            .group_by(ProductionCompany.id, ProductionCompany.name)
            .having(func.count(Movie.id) >= 2)
            .order_by(desc("movie_count"), ProductionCompany.id)
            .limit(10)
            .all()
        ]

        total_movies = session.query(func.count(Movie.id)).scalar()
        avg_rating = (
            session.query(func.avg(Movie.vote_average))
            .filter(Movie.vote_count > ANALYTICS_MIN_VOTES)
            .scalar()
        )
        total_revenue = session.query(func.sum(Movie.revenue)).filter(Movie.revenue > 0).scalar()

        return {
            "genre_stats": genre_stats,
            "year_stats": year_stats,
            "genre_ratings": genre_ratings,
            "box_office_by_genre": box_office_by_genre,
            "budget_revenue_scatter": budget_revenue_scatter,
            "most_profitable": most_profitable,
            "top_companies": top_companies,
            "total_movies": total_movies,
            "avg_rating": _number(avg_rating, 1) or 0,
            "total_revenue": int(total_revenue or 0),
        }

    return _cached("analytics:page", compute)


@bp.route("/analytics")
def index():
    """Analytics dashboard"""
    session = get_db_session()

    try:
        user = get_current_user(session)

        data = _analytics_data(session)
        return render_template(
            "analytics.html",
            **data,
            current_user=user,
            config=Config,
        )
    finally:
        session.close()


@bp.route("/analytics/export/csv")
@limiter.limit("20 per hour")
def export_csv():
    """Export analytics data as a CSV file download"""
    session = get_db_session()
    try:
        # Genre statistics
        genre_stats = (
            session.query(
                Genre.name,
                func.count(Movie.id).label("count"),
                # Same rule as /analytics: only movies with enough votes count
                # toward the average (unrated movies are stored as 0.0)
                func.avg(
                    case(
                        (Movie.vote_count > ANALYTICS_MIN_VOTES, Movie.vote_average),
                        else_=None,
                    )
                ).label("avg_rating"),
            )
            .join(Movie.genres)
            .group_by(Genre.name)
            .order_by(desc("count"), Genre.name)
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
                Movie.title,
                Movie.vote_average,
                Movie.vote_count,
                Movie.revenue,
                Movie.release_date,
            )
            .filter(Movie.vote_count > 100)
            .order_by(desc(Movie.vote_average), desc(Movie.vote_count), Movie.id)
            .limit(25)
            .all()
        )

        # Top 25 movies by revenue
        top_revenue = (
            session.query(
                Movie.title,
                Movie.budget,
                Movie.revenue,
                Movie.vote_average,
                Movie.release_date,
            )
            .filter(Movie.revenue > 0)
            .order_by(desc(Movie.revenue), Movie.id)
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
        filename = f"movie_analytics_{utcnow().strftime('%Y%m%d')}.csv"

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        session.close()
