"""
Tests for REST API endpoints (/api/v1/*)
Replaces the manual test_api.py script with proper pytest coverage.
"""

import pytest


class TestHealthEndpoint:
    """Tests for /api/v1/health"""

    def test_health_returns_200(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_health_returns_json(self, client):
        response = client.get("/api/v1/health")
        data = response.get_json()
        assert data is not None

    def test_health_status_field(self, client):
        response = client.get("/api/v1/health")
        data = response.get_json()
        assert "status" in data
        assert data["status"] == "healthy"

    def test_health_includes_movie_count(self, client, sample_movies):
        response = client.get("/api/v1/health")
        data = response.get_json()
        assert "movie_count" in data
        assert data["movie_count"] >= 0


class TestDocsEndpoint:
    """Tests for /api/v1/docs"""

    def test_docs_returns_200(self, client):
        response = client.get("/api/v1/docs")
        assert response.status_code == 200

    def test_docs_returns_json(self, client):
        response = client.get("/api/v1/docs")
        data = response.get_json()
        assert data is not None

    def test_docs_has_version(self, client):
        response = client.get("/api/v1/docs")
        data = response.get_json()
        assert "version" in data

    def test_docs_has_endpoints(self, client):
        response = client.get("/api/v1/docs")
        data = response.get_json()
        assert "endpoints" in data
        assert "movies" in data["endpoints"]
        assert "genres" in data["endpoints"]
        assert "analytics" in data["endpoints"]
        assert "actors" in data["endpoints"]


class TestMoviesApiEndpoint:
    """Tests for /api/v1/movies"""

    def test_movies_returns_200(self, client):
        response = client.get("/api/v1/movies")
        assert response.status_code == 200

    def test_movies_returns_json(self, client, sample_movies):
        response = client.get("/api/v1/movies")
        data = response.get_json()
        assert data is not None
        assert "movies" in data

    def test_movies_pagination_fields(self, client, sample_movies):
        response = client.get("/api/v1/movies")
        data = response.get_json()
        assert "page" in data
        assert "per_page" in data
        assert "total" in data
        assert "total_pages" in data

    def test_movies_default_pagination(self, client, sample_movies):
        response = client.get("/api/v1/movies")
        data = response.get_json()
        assert data["page"] == 1
        assert data["per_page"] == 20

    def test_movies_custom_page(self, client, sample_movies):
        response = client.get("/api/v1/movies?page=2&per_page=5")
        data = response.get_json()
        assert data["page"] == 2
        assert data["per_page"] == 5

    def test_movies_per_page_capped_at_100(self, client, sample_movies):
        response = client.get("/api/v1/movies?per_page=999")
        data = response.get_json()
        assert data["per_page"] <= 100

    def test_movies_sort_by_rating(self, client, sample_movies):
        response = client.get("/api/v1/movies?sort=rating")
        assert response.status_code == 200

    def test_movies_sort_by_release_date(self, client, sample_movies):
        response = client.get("/api/v1/movies?sort=release_date")
        assert response.status_code == 200

    def test_movies_sort_by_title(self, client, sample_movies):
        response = client.get("/api/v1/movies?sort=title")
        assert response.status_code == 200

    def test_movies_filter_by_genre(self, client, sample_movies, sample_genre):
        response = client.get(f"/api/v1/movies?genre={sample_genre.id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total"] > 0

    def test_movies_filter_by_year(self, client, sample_movies):
        response = client.get("/api/v1/movies?year=2024")
        assert response.status_code == 200

    def test_movies_filter_by_min_rating(self, client, sample_movies):
        response = client.get("/api/v1/movies?min_rating=7.0")
        assert response.status_code == 200

    def test_movie_object_fields(self, client, sample_movies):
        response = client.get("/api/v1/movies?per_page=1")
        data = response.get_json()
        if data["movies"]:
            movie = data["movies"][0]
            assert "id" in movie
            assert "title" in movie
            assert "tmdb_id" in movie
            assert "genres" in movie


class TestMovieDetailApiEndpoint:
    """Tests for /api/v1/movies/<id>"""

    def test_movie_detail_returns_200(self, client, sample_movie):
        response = client.get(f"/api/v1/movies/{sample_movie.id}")
        assert response.status_code == 200

    def test_movie_detail_returns_correct_movie(self, client, sample_movie):
        response = client.get(f"/api/v1/movies/{sample_movie.id}")
        data = response.get_json()
        assert data["title"] == "Fight Club"
        assert data["tmdb_id"] == 550

    def test_movie_detail_has_required_fields(self, client, sample_movie):
        response = client.get(f"/api/v1/movies/{sample_movie.id}")
        data = response.get_json()
        for field in ["id", "title", "overview", "genres", "cast", "crew", "user_rating"]:
            assert field in data

    def test_movie_detail_404_for_invalid_id(self, client):
        response = client.get("/api/v1/movies/999999")
        assert response.status_code == 404

    def test_movie_detail_404_response_has_error_field(self, client):
        response = client.get("/api/v1/movies/999999")
        data = response.get_json()
        assert "error" in data

    def test_movie_detail_includes_cast(self, client, sample_movie, sample_cast):
        response = client.get(f"/api/v1/movies/{sample_movie.id}")
        data = response.get_json()
        assert len(data["cast"]) > 0
        cast_member = data["cast"][0]
        assert "name" in cast_member
        assert "character" in cast_member

    def test_movie_detail_includes_user_rating(self, client, sample_movie):
        response = client.get(f"/api/v1/movies/{sample_movie.id}")
        data = response.get_json()
        assert "user_rating" in data
        assert "average" in data["user_rating"]
        assert "count" in data["user_rating"]


class TestMovieSearchApiEndpoint:
    """Tests for /api/v1/movies/search"""

    def test_search_returns_200(self, client, sample_movie):
        response = client.get("/api/v1/movies/search?q=Fight")
        assert response.status_code == 200

    def test_search_finds_movie_by_title(self, client, sample_movie):
        response = client.get("/api/v1/movies/search?q=Fight")
        data = response.get_json()
        assert data["total"] > 0
        titles = [m["title"] for m in data["movies"]]
        assert "Fight Club" in titles

    def test_search_returns_query_field(self, client):
        response = client.get("/api/v1/movies/search?q=test")
        data = response.get_json()
        assert "query" in data
        assert data["query"] == "test"

    def test_search_missing_query_returns_400(self, client):
        response = client.get("/api/v1/movies/search")
        assert response.status_code == 400

    def test_search_empty_results(self, client, sample_movie):
        response = client.get("/api/v1/movies/search?q=zzznomatchxyz")
        data = response.get_json()
        assert data["total"] == 0
        assert data["movies"] == []

    def test_search_pagination(self, client, sample_movies):
        response = client.get("/api/v1/movies/search?q=Test&page=1&per_page=5")
        data = response.get_json()
        assert data["page"] == 1
        assert len(data["movies"]) <= 5


class TestGenresApiEndpoint:
    """Tests for /api/v1/genres"""

    def test_genres_returns_200(self, client):
        response = client.get("/api/v1/genres")
        assert response.status_code == 200

    def test_genres_returns_list(self, client, sample_genre):
        response = client.get("/api/v1/genres")
        data = response.get_json()
        assert "genres" in data
        assert isinstance(data["genres"], list)

    def test_genres_includes_sample_genre(self, client, sample_genre):
        response = client.get("/api/v1/genres")
        data = response.get_json()
        names = [g["name"] for g in data["genres"]]
        assert "Action" in names

    def test_genre_object_fields(self, client, sample_genre):
        response = client.get("/api/v1/genres")
        data = response.get_json()
        if data["genres"]:
            genre = data["genres"][0]
            assert "id" in genre
            assert "name" in genre
            assert "tmdb_id" in genre


class TestAnalyticsApiEndpoints:
    """Tests for /api/v1/analytics/*"""

    def test_overview_returns_200(self, client):
        response = client.get("/api/v1/analytics/overview")
        assert response.status_code == 200

    def test_overview_has_required_fields(self, client, sample_movies):
        response = client.get("/api/v1/analytics/overview")
        data = response.get_json()
        assert "total_movies" in data
        assert "movies_by_year" in data

    def test_overview_total_movies_count(self, client, sample_movies):
        response = client.get("/api/v1/analytics/overview")
        data = response.get_json()
        assert data["total_movies"] >= len(sample_movies)

    def test_genres_analytics_returns_200(self, client):
        response = client.get("/api/v1/analytics/genres")
        assert response.status_code == 200

    def test_genres_analytics_has_genres_list(self, client, sample_movies):
        response = client.get("/api/v1/analytics/genres")
        data = response.get_json()
        assert "genres" in data
        assert isinstance(data["genres"], list)

    def test_top_movies_rating_metric(self, client, sample_movies):
        response = client.get("/api/v1/analytics/top-movies?metric=rating")
        assert response.status_code == 200
        data = response.get_json()
        assert data["metric"] == "rating"
        assert "movies" in data

    def test_top_movies_revenue_metric(self, client, sample_movies):
        response = client.get("/api/v1/analytics/top-movies?metric=revenue")
        assert response.status_code == 200

    def test_top_movies_popularity_metric(self, client, sample_movies):
        response = client.get("/api/v1/analytics/top-movies?metric=popularity")
        assert response.status_code == 200

    def test_top_movies_invalid_metric_returns_400(self, client):
        response = client.get("/api/v1/analytics/top-movies?metric=invalid")
        assert response.status_code == 400

    def test_top_movies_limit_param(self, client, sample_movies):
        response = client.get("/api/v1/analytics/top-movies?metric=popularity&limit=5")
        data = response.get_json()
        assert len(data["movies"]) <= 5


class TestActorsApiEndpoints:
    """Tests for /api/v1/actors"""

    def test_actors_returns_200(self, client):
        response = client.get("/api/v1/actors")
        assert response.status_code == 200

    def test_actors_returns_pagination_fields(self, client):
        response = client.get("/api/v1/actors")
        data = response.get_json()
        assert "page" in data
        assert "total" in data
        assert "actors" in data

    def test_actors_with_cast_data(self, client, sample_cast):
        response = client.get("/api/v1/actors")
        data = response.get_json()
        assert isinstance(data["actors"], list)

    def test_actor_detail_returns_200(self, client, sample_person, sample_cast):
        response = client.get(f"/api/v1/actors/{sample_person.id}")
        assert response.status_code == 200

    def test_actor_detail_correct_name(self, client, sample_person, sample_cast):
        response = client.get(f"/api/v1/actors/{sample_person.id}")
        data = response.get_json()
        assert data["name"] == "Brad Pitt"

    def test_actor_detail_has_filmography(self, client, sample_person, sample_cast):
        response = client.get(f"/api/v1/actors/{sample_person.id}")
        data = response.get_json()
        assert "filmography" in data
        assert len(data["filmography"]) > 0

    def test_actor_detail_404_for_invalid_id(self, client):
        response = client.get("/api/v1/actors/999999")
        assert response.status_code == 404
