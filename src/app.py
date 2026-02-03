from flask import Flask, render_template, request, jsonify
from sqlalchemy import func, desc
from src.models import Session, Movie, Genre, Person, Cast, Crew, ProductionCompany
from src.tmdb_api import TMDBClient
from config.config import Config
from datetime import datetime
from typing import Optional, Dict

app = Flask(__name__, 
            template_folder='../templates',
            static_folder='../static')
app.config.from_object(Config)

def get_db_session():
    """Get a new database session"""
    return Session()

def get_trailer_for_movie(tmdb_id: int) -> Optional[Dict]:
    """Fetch the best YouTube trailer for a movie from TMDB API."""
    client = TMDBClient()
    videos_data = client.get_movie_videos(tmdb_id)
    results = videos_data.get('results', [])

    youtube_videos = [v for v in results if v.get('site') == 'YouTube']
    if not youtube_videos:
        return None

    # Priority: official trailers > any trailer > teasers > any video
    for filter_fn in [
        lambda v: v.get('type') == 'Trailer' and v.get('official'),
        lambda v: v.get('type') == 'Trailer',
        lambda v: v.get('type') == 'Teaser',
    ]:
        matches = [v for v in youtube_videos if filter_fn(v)]
        if matches:
            return matches[0]

    return youtube_videos[0]

@app.route('/')
def index():
    """Homepage with featured movies"""
    session = get_db_session()
    
    try:
        # Get top rated movies
        top_movies = session.query(Movie)\
            .filter(Movie.vote_count > 100)\
            .order_by(desc(Movie.vote_average))\
            .limit(12)\
            .all()
        
        # Get recent movies
        recent_movies = session.query(Movie)\
            .filter(Movie.release_date.isnot(None))\
            .order_by(desc(Movie.release_date))\
            .limit(12)\
            .all()
        
        # Get popular movies
        popular_movies = session.query(Movie)\
            .order_by(desc(Movie.popularity))\
            .limit(12)\
            .all()
        
        return render_template('index.html',
                             top_movies=top_movies,
                             recent_movies=recent_movies,
                             popular_movies=popular_movies,
                             config=Config)
    finally:
        session.close()

@app.route('/movies')
def movies():
    """All movies page with filters"""
    session = get_db_session()
    
    try:
        # Get filter parameters
        genre_id = request.args.get('genre', type=int)
        sort_by = request.args.get('sort', default='popularity')
        page = request.args.get('page', default=1, type=int)
        
        # Base query
        query = session.query(Movie)
        
        # Apply genre filter
        if genre_id:
            query = query.join(Movie.genres).filter(Genre.id == genre_id)
        
        # Apply sorting
        if sort_by == 'rating':
            query = query.filter(Movie.vote_count > 50).order_by(desc(Movie.vote_average))
        elif sort_by == 'release_date':
            query = query.filter(Movie.release_date.isnot(None)).order_by(desc(Movie.release_date))
        elif sort_by == 'title':
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
        
        # Calculate pagination info
        total_pages = (total_movies + per_page - 1) // per_page
        
        return render_template('movies.html',
                             movies=movies_list,
                             genres=all_genres,
                             current_genre=genre_id,
                             current_sort=sort_by,
                             page=page,
                             total_pages=total_pages,
                             total_movies=total_movies,
                             config=Config)
    finally:
        session.close()

@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    """Movie detail page"""
    session = get_db_session()
    
    try:
        movie = session.query(Movie).filter_by(id=movie_id).first()
        
        if not movie:
            return "Movie not found", 404
        
        # Get cast (top 10)
        cast = session.query(Cast, Person)\
            .join(Person)\
            .filter(Cast.movie_id == movie_id)\
            .order_by(Cast.cast_order)\
            .limit(10)\
            .all()
        
        # Get directors
        directors = session.query(Crew, Person)\
            .join(Person)\
            .filter(Crew.movie_id == movie_id, Crew.job == 'Director')\
            .all()
        
        # Get similar movies (same genres)
        if movie.genres:
            genre_ids = [g.id for g in movie.genres]
            similar_movies = session.query(Movie)\
                .join(Movie.genres)\
                .filter(Genre.id.in_(genre_ids))\
                .filter(Movie.id != movie_id)\
                .order_by(desc(Movie.popularity))\
                .limit(6)\
                .all()
        else:
            similar_movies = []

        # Get trailer from TMDB API
        trailer = get_trailer_for_movie(movie.tmdb_id)

        return render_template('movie_detail.html',
                             movie=movie,
                             cast=cast,
                             directors=directors,
                             similar_movies=similar_movies,
                             trailer=trailer,
                             config=Config)
    finally:
        session.close()

@app.route('/analytics')
def analytics():
    """Analytics dashboard"""
    session = get_db_session()
    
    try:
        # Genre distribution
        genre_stats = session.query(
            Genre.name,
            func.count(Movie.id).label('count')
        ).join(Movie.genres)\
         .group_by(Genre.name)\
         .order_by(desc('count'))\
         .all()
        
        # Movies by year
        year_stats = session.query(
            func.strftime('%Y', Movie.release_date).label('year'),
            func.count(Movie.id).label('count')
        ).filter(Movie.release_date.isnot(None))\
         .group_by('year')\
         .order_by('year')\
         .all()
        
        # Average ratings by genre
        genre_ratings = session.query(
            Genre.name,
            func.avg(Movie.vote_average).label('avg_rating'),
            func.count(Movie.id).label('count')
        ).join(Movie.genres)\
         .filter(Movie.vote_count > 50)\
         .group_by(Genre.name)\
         .having(func.count(Movie.id) >= 3)\
         .order_by(desc('avg_rating'))\
         .all()
        
        # Budget vs Revenue (top 20 movies with both)
        budget_revenue = session.query(Movie)\
            .filter(Movie.budget > 0, Movie.revenue > 0)\
            .order_by(desc(Movie.revenue))\
            .limit(20)\
            .all()
        
        # Top production companies
        top_companies = session.query(
            ProductionCompany.name,
            func.count(Movie.id).label('movie_count'),
            func.avg(Movie.vote_average).label('avg_rating')
        ).join(ProductionCompany.movies)\
         .filter(Movie.vote_count > 50)\
         .group_by(ProductionCompany.name)\
         .having(func.count(Movie.id) >= 2)\
         .order_by(desc('movie_count'))\
         .limit(10)\
         .all()
        
        # Overall statistics
        total_movies = session.query(func.count(Movie.id)).scalar()
        avg_rating = session.query(func.avg(Movie.vote_average))\
            .filter(Movie.vote_count > 50).scalar()
        total_revenue = session.query(func.sum(Movie.revenue))\
            .filter(Movie.revenue > 0).scalar()
        
        return render_template('analytics.html',
                             genre_stats=genre_stats,
                             year_stats=year_stats,
                             genre_ratings=genre_ratings,
                             budget_revenue=budget_revenue,
                             top_companies=top_companies,
                             total_movies=total_movies,
                             avg_rating=round(avg_rating, 1) if avg_rating else 0,
                             total_revenue=total_revenue or 0,
                             config=Config)
    finally:
        session.close()

@app.route('/search')
def search():
    """Search movies"""
    session = get_db_session()
    
    try:
        query = request.args.get('q', '')
        
        if not query:
            return render_template('search.html', movies=[], query='', config=Config)
        
        # Search in title and overview
        movies_list = session.query(Movie)\
            .filter(
                (Movie.title.ilike(f'%{query}%')) |
                (Movie.overview.ilike(f'%{query}%'))
            )\
            .order_by(desc(Movie.popularity))\
            .limit(50)\
            .all()
        
        return render_template('search.html',
                             movies=movies_list,
                             query=query,
                             config=Config)
    finally:
        session.close()

@app.template_filter('format_currency')
def format_currency(value):
    """Format number as currency"""
    if not value:
        return 'N/A'
    return f'${value:,.0f}'

@app.template_filter('format_runtime')
def format_runtime(minutes):
    """Format runtime in minutes to hours and minutes"""
    if not minutes:
        return 'N/A'
    hours = minutes // 60
    mins = minutes % 60
    return f'{hours}h {mins}m'

if __name__ == '__main__':
    app.run(debug=True)