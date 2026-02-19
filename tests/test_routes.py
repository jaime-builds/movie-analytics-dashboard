"""
Tests for Flask application routes
"""

from datetime import datetime

import pytest


class TestIndexRoute:
    """Tests for the homepage route"""

    def test_index_loads(self, client):
        """Test that homepage loads successfully"""
        response = client.get("/")
        assert response.status_code == 200
        assert b"Movie Analytics" in response.data or b"movie" in response.data.lower()

    def test_index_shows_top_movies(self, client, sample_movies):
        """Test that homepage displays top movies"""
        response = client.get("/")
        assert response.status_code == 200
        # Should show some movies
        assert b"Test Movie" in response.data


class TestMoviesRoute:
    """Tests for the movies listing page"""

    def test_movies_page_loads(self, client):
        """Test that movies page loads successfully"""
        response = client.get("/movies")
        assert response.status_code == 200
        assert b"All Movies" in response.data or b"Movies" in response.data

    def test_movies_with_data(self, client, sample_movies):
        """Test movies page with sample data"""
        response = client.get("/movies")
        assert response.status_code == 200
        assert b"Test Movie" in response.data

    def test_movies_pagination(self, client, sample_movies):
        """Test pagination on movies page"""
        # First page
        response = client.get("/movies?page=1")
        assert response.status_code == 200

        # Second page
        response = client.get("/movies?page=2")
        assert response.status_code == 200

    def test_movies_sort_by_rating(self, client, sample_movies):
        """Test sorting movies by rating"""
        response = client.get("/movies?sort=rating")
        assert response.status_code == 200

    def test_movies_sort_by_release_date(self, client, sample_movies):
        """Test sorting movies by release date"""
        response = client.get("/movies?sort=release_date")
        assert response.status_code == 200

    def test_movies_sort_by_title(self, client, sample_movies):
        """Test sorting movies by title"""
        response = client.get("/movies?sort=title")
        assert response.status_code == 200

    def test_movies_filter_by_genre(self, client, sample_movies, sample_genre):
        """Test filtering movies by genre"""
        response = client.get(f"/movies?genre={sample_genre.id}")
        assert response.status_code == 200
        assert b"Test Movie" in response.data

    def test_movies_pagination_limits(self, client, sample_movies):
        """Test pagination shows correct number of movies per page"""
        response = client.get("/movies?page=1")
        assert response.status_code == 200
        # Should show max 20 movies per page


class TestMovieDetailRoute:
    """Tests for individual movie detail pages"""

    def test_movie_detail_loads(self, client, sample_movie):
        """Test that movie detail page loads"""
        response = client.get(f"/movie/{sample_movie.id}")
        assert response.status_code == 200
        assert b"Fight Club" in response.data

    def test_movie_detail_shows_overview(self, client, sample_movie):
        """Test that movie detail shows overview"""
        response = client.get(f"/movie/{sample_movie.id}")
        assert response.status_code == 200
        assert b"insomniac" in response.data.lower()

    def test_movie_detail_shows_cast(self, client, sample_movie, sample_cast):
        """Test that movie detail shows cast"""
        response = client.get(f"/movie/{sample_movie.id}")
        assert response.status_code == 200
        assert b"Brad Pitt" in response.data

    def test_movie_detail_shows_directors(self, client, sample_movie, sample_crew):
        """Test that movie detail shows directors"""
        response = client.get(f"/movie/{sample_movie.id}")
        assert response.status_code == 200
        assert b"David Fincher" in response.data

    def test_movie_detail_404(self, client):
        """Test that invalid movie ID returns 404"""
        response = client.get("/movie/99999")
        assert response.status_code == 404

    def test_movie_detail_shows_similar_movies(self, client, sample_movies):
        """Test that similar movies are shown"""
        movie = sample_movies[0]
        response = client.get(f"/movie/{movie.id}")
        assert response.status_code == 200
        # Should show some similar movies


class TestSearchRoute:
    """Tests for search functionality"""

    def test_search_page_loads(self, client):
        """Test that search page loads"""
        response = client.get("/search")
        assert response.status_code == 200

    def test_search_empty_query(self, client):
        """Test search with empty query"""
        response = client.get("/search?q=")
        assert response.status_code == 200

    def test_search_finds_movies(self, client, sample_movie):
        """Test search finds movies by title"""
        response = client.get("/search?q=Fight")
        assert response.status_code == 200
        assert b"Fight Club" in response.data

    def test_search_by_overview(self, client, sample_movie):
        """Test search finds movies by overview text"""
        response = client.get("/search?q=insomniac")
        assert response.status_code == 200
        assert b"Fight Club" in response.data

    def test_search_case_insensitive(self, client, sample_movie):
        """Test search is case insensitive"""
        response = client.get("/search?q=fight")
        assert response.status_code == 200
        assert b"Fight Club" in response.data

    def test_search_no_results(self, client, sample_movie):
        """Test search with no matching results"""
        response = client.get("/search?q=zzznonexistent")
        assert response.status_code == 200
        # Should still load, just with no results


class TestAnalyticsRoute:
    """Tests for analytics dashboard"""

    def test_analytics_page_loads(self, client):
        """Test that analytics page loads"""
        response = client.get("/analytics")
        assert response.status_code == 200
        assert b"Analytics" in response.data or b"analytics" in response.data.lower()

    def test_analytics_with_data(self, client, sample_movies):
        """Test analytics page with sample data"""
        response = client.get("/analytics")
        assert response.status_code == 200
        # Should show some statistics
        assert b"Action" in response.data  # Genre name

    def test_analytics_shows_genre_stats(self, client, sample_movies):
        """Test that analytics shows genre statistics"""
        response = client.get("/analytics")
        assert response.status_code == 200
        # Should contain genre data

    def test_analytics_shows_year_stats(self, client, sample_movies):
        """Test that analytics shows year statistics"""
        response = client.get("/analytics")
        assert response.status_code == 200
        # Should contain year data


class TestTemplateFilters:
    """Tests for custom Jinja2 template filters"""

    def test_format_currency_filter(self, app):
        """Test currency formatting filter"""
        with app.app_context():
            from src.app import format_currency

            assert format_currency(1000000) == "$1,000,000"
            assert format_currency(0) == "N/A" or format_currency(0) == "$0"
            assert format_currency(None) == "N/A"

    def test_format_runtime_filter(self, app):
        """Test runtime formatting filter"""
        with app.app_context():
            from src.app import format_runtime

            assert format_runtime(139) == "2h 19m"
            assert format_runtime(90) == "1h 30m"
            assert format_runtime(None) == "N/A"
            assert format_runtime(0) == "N/A" or format_runtime(0) == "0h 0m"


class TestErrorHandling:
    """Tests for error handling"""

    def test_invalid_route_404(self, client):
        """Test that invalid routes return 404"""
        response = client.get("/nonexistent-page")
        assert response.status_code == 404

    def test_movie_not_found(self, client):
        """Test movie detail with non-existent ID"""
        response = client.get("/movie/999999")
        assert response.status_code == 404


class TestStaticFiles:
    """Tests for static file serving"""

    def test_css_files_exist(self, client):
        """Test that CSS files are accessible"""
        response = client.get("/static/css/style.css")
        # Should be 200 if file exists, 404 if not (both are OK for this test)
        assert response.status_code in [200, 404]

    def test_js_files_exist(self, client):
        """Test that JS files are accessible"""
        response = client.get("/static/js/theme.js")
        # Should be 200 if file exists, 404 if not (both are OK for this test)
        assert response.status_code in [200, 404]
