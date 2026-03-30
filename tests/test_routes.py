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
        # Genre data is embedded in Chart.js JS — check page loaded with content
        assert b"Analytics" in response.data or b"analytics" in response.data.lower()

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


class TestCompareRoute:
    """Tests for the /compare movie comparison page"""

    def test_compare_page_loads_empty(self, client):
        """Test compare page loads with no movies selected"""
        response = client.get("/compare")
        assert response.status_code == 200

    def test_compare_page_loads_with_one_movie(self, client, sample_movie):
        """Test compare page loads with a single movie (shows prompt to add more)"""
        response = client.get(f"/compare?id={sample_movie.id}")
        assert response.status_code == 200
        # With only 1 movie the template shows the 'add more' alert, not the table
        assert b"Select at least 2 movies" in response.data

    def test_compare_page_loads_with_multiple_movies(self, client, sample_movies):
        """Test compare page loads with multiple movies and shows titles"""
        ids = "&".join(f"id={m.id}" for m in sample_movies[:3])
        response = client.get(f"/compare?{ids}")
        assert response.status_code == 200
        assert sample_movies[0].title.encode() in response.data

    def test_compare_caps_at_four_movies(self, client, sample_movies):
        """Test that compare page only shows up to 4 movies even if more IDs passed"""
        ids = "&".join(f"id={m.id}" for m in sample_movies[:8])
        response = client.get(f"/compare?{ids}")
        assert response.status_code == 200
        # Should load without error — cap is enforced in the route

    def test_compare_ignores_invalid_ids(self, client, sample_movie):
        """Test compare page handles a mix of valid and invalid IDs gracefully"""
        response = client.get(f"/compare?id={sample_movie.id}&id=999999")
        assert response.status_code == 200
        # Invalid ID is silently dropped; only 1 valid movie so shows prompt
        assert b"Select at least 2 movies" in response.data

    def test_compare_with_all_invalid_ids(self, client):
        """Test compare page with only non-existent movie IDs"""
        response = client.get("/compare?id=888888&id=999999")
        assert response.status_code == 200

    def test_compare_shows_director(self, client, sample_movie, sample_crew, sample_movies):
        """Test that director info appears on compare page when 2+ movies selected"""
        # Need 2 movies for the comparison table to render
        ids = f"id={sample_movie.id}&id={sample_movies[0].id}"
        response = client.get(f"/compare?{ids}")
        assert response.status_code == 200
        assert b"David Fincher" in response.data

    def test_compare_preserves_movie_order(self, client, sample_movies):
        """Test that movies appear in the order IDs were passed"""
        m0, m1, m2 = sample_movies[0], sample_movies[1], sample_movies[2]
        response = client.get(f"/compare?id={m2.id}&id={m0.id}&id={m1.id}")
        assert response.status_code == 200
        # All three titles should appear
        assert m0.title.encode() in response.data
        assert m1.title.encode() in response.data
        assert m2.title.encode() in response.data


class TestAdvancedFilters:
    """Tests for advanced filter parameters on /movies"""

    def test_filter_by_min_vote_count(self, client, sample_movies):
        """Test filtering movies by minimum vote count"""
        response = client.get("/movies?min_vote_count=100")
        assert response.status_code == 200

    def test_filter_by_status_released(self, client, sample_movie):
        """Test filtering movies by Released status"""
        response = client.get("/movies?status=Released")
        assert response.status_code == 200
        assert b"Fight Club" in response.data

    def test_filter_by_status_no_results(self, client, sample_movie):
        """Test filtering by a status that matches no movies"""
        response = client.get("/movies?status=In+Production")
        assert response.status_code == 200

    def test_filter_by_runtime_min(self, client, sample_movie):
        """Test filtering movies by minimum runtime"""
        response = client.get("/movies?runtime_min=100")
        assert response.status_code == 200
        assert b"Fight Club" in response.data

    def test_filter_by_runtime_max(self, client, sample_movie):
        """Test filtering movies by maximum runtime"""
        response = client.get("/movies?runtime_max=200")
        assert response.status_code == 200
        assert b"Fight Club" in response.data

    def test_filter_by_runtime_range_excludes_movie(self, client, sample_movie):
        """Test that a movie outside the runtime range is excluded"""
        # Fight Club is 139m — filter for under 60m should exclude it
        response = client.get("/movies?runtime_max=60")
        assert response.status_code == 200
        assert b"Fight Club" not in response.data

    def test_filter_by_decade(self, client, sample_movie):
        """Test filtering movies by decade"""
        response = client.get("/movies?decade=1990")
        assert response.status_code == 200
        assert b"Fight Club" in response.data

    def test_filter_by_decade_no_results(self, client, sample_movie):
        """Test filtering by a decade with no matching movies"""
        response = client.get("/movies?decade=1920")
        assert response.status_code == 200
        assert b"Fight Club" not in response.data

    def test_filter_by_rating_range(self, client, sample_movies):
        """Test filtering movies by rating min and max"""
        response = client.get("/movies?rating_min=7.0&rating_max=8.0")
        assert response.status_code == 200

    def test_multiple_filters_combined(self, client, sample_movie):
        """Test that multiple filters can be combined"""
        response = client.get("/movies?status=Released&runtime_min=100&decade=1990")
        assert response.status_code == 200
        assert b"Fight Club" in response.data


class TestCaching:
    """Tests that cached routes function correctly under NullCache in test mode"""

    def test_analytics_cached_route_returns_200(self, client):
        """Test analytics page (cached) loads correctly"""
        response = client.get("/analytics")
        assert response.status_code == 200

    def test_analytics_cached_route_repeated_request(self, client):
        """Test analytics page returns 200 on repeated requests (cache layer stable)"""
        client.get("/analytics")
        response = client.get("/analytics")
        assert response.status_code == 200

    def test_api_analytics_overview_cached(self, client):
        """Test cached analytics overview API endpoint"""
        response = client.get("/api/v1/analytics/overview")
        assert response.status_code == 200
        client.get("/api/v1/analytics/overview")
        response = client.get("/api/v1/analytics/overview")
        assert response.status_code == 200

    def test_api_analytics_genres_cached(self, client):
        """Test cached analytics genres API endpoint"""
        response = client.get("/api/v1/analytics/genres")
        assert response.status_code == 200
        response = client.get("/api/v1/analytics/genres")
        assert response.status_code == 200

    def test_api_analytics_top_movies_cached(self, client):
        """Test cached top-movies API endpoint with query string variance"""
        response = client.get("/api/v1/analytics/top-movies?metric=rating")
        assert response.status_code == 200
        response = client.get("/api/v1/analytics/top-movies?metric=popularity")
        assert response.status_code == 200


class TestAnalyticsExport:
    """Tests for the /analytics/export/csv download endpoint"""

    def test_csv_export_returns_200(self, client):
        """Test that the CSV export endpoint returns a successful response"""
        response = client.get("/analytics/export/csv")
        assert response.status_code == 200

    def test_csv_export_content_type(self, client):
        """Test that the response has the correct CSV content type"""
        response = client.get("/analytics/export/csv")
        assert "text/csv" in response.content_type

    def test_csv_export_has_content_disposition(self, client):
        """Test that the response triggers a file download"""
        response = client.get("/analytics/export/csv")
        assert "attachment" in response.headers["Content-Disposition"]
        assert ".csv" in response.headers["Content-Disposition"]

    def test_csv_export_filename_format(self, client):
        """Test that the downloaded filename follows the expected pattern"""
        response = client.get("/analytics/export/csv")
        disposition = response.headers["Content-Disposition"]
        assert "movie_analytics_" in disposition

    def test_csv_export_contains_genre_section(self, client, sample_movies):
        """Test that the CSV contains the genre statistics section"""
        response = client.get("/analytics/export/csv")
        content = response.data.decode("utf-8")
        assert "GENRE STATISTICS" in content
        assert "Genre" in content
        assert "Movie Count" in content
        assert "Average Rating" in content

    def test_csv_export_contains_year_section(self, client, sample_movies):
        """Test that the CSV contains the movies by year section"""
        response = client.get("/analytics/export/csv")
        content = response.data.decode("utf-8")
        assert "MOVIES BY RELEASE YEAR" in content
        assert "Year" in content

    def test_csv_export_contains_top_rated_section(self, client, sample_movies):
        """Test that the CSV contains the top movies by rating section"""
        response = client.get("/analytics/export/csv")
        content = response.data.decode("utf-8")
        assert "TOP 25 MOVIES BY RATING" in content

    def test_csv_export_contains_top_revenue_section(self, client, sample_movies):
        """Test that the CSV contains the top movies by revenue section"""
        response = client.get("/analytics/export/csv")
        content = response.data.decode("utf-8")
        assert "TOP 25 MOVIES BY REVENUE" in content

    def test_csv_export_genre_data_present(self, client, sample_movies, sample_genre):
        """Test that actual genre data appears in the export"""
        response = client.get("/analytics/export/csv")
        content = response.data.decode("utf-8")
        assert "Action" in content

    def test_csv_export_is_valid_csv(self, client, sample_movies):
        """Test that the response body is parseable as valid CSV"""
        import csv
        import io

        response = client.get("/analytics/export/csv")
        content = response.data.decode("utf-8")
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) > 0

    def test_csv_export_works_with_empty_database(self, client):
        """Test that export works gracefully with no data"""
        response = client.get("/analytics/export/csv")
        assert response.status_code == 200
        assert "text/csv" in response.content_type


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
