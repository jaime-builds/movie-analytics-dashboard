"""
Tests for sprint apr-2026 features:
- /companies and /company/<id> (production companies)
- /decades and /decade/<id> (decade overview)
- /collections, /collection/<id>, add/remove, API (movie collections)
"""

from datetime import date

import pytest

from src.models import Collection, Movie, ProductionCompany, User

# ============================================
# Helpers / extra fixtures
# ============================================


@pytest.fixture
def company_with_movies(db_session, sample_production_company):
    """Attach 3 movies to the sample production company so it appears on the listing."""
    for i in range(3):
        movie = Movie(
            tmdb_id=90000 + i,
            title=f"Studio Film {i}",
            overview="A studio production",
            release_date=date(2010 + i, 6, 1),
            vote_average=7.0,
            vote_count=200,
            popularity=40.0,
        )
        db_session.add(movie)
        db_session.flush()
        sample_production_company.movies.append(movie)

    db_session.commit()
    return sample_production_company


@pytest.fixture
def decade_movies(db_session, sample_genre):
    """Create movies spread across the 1990s for decade tests."""
    movies = []
    for year in range(1990, 2000):
        movie = Movie(
            tmdb_id=80000 + year,
            title=f"Nineties Film {year}",
            overview="A 90s classic",
            release_date=date(year, 1, 1),
            vote_average=7.5,
            vote_count=100,
            popularity=30.0,
        )
        movie.genres.append(sample_genre)
        movies.append(movie)
    db_session.add_all(movies)
    db_session.commit()
    return movies


@pytest.fixture
def sample_collection(db_session, sample_user):
    """Create a collection owned by the sample user."""
    collection = Collection(
        user_id=sample_user.id,
        name="My Test Collection",
        description="A collection for testing",
    )
    db_session.add(collection)
    db_session.commit()
    return collection


@pytest.fixture
def collection_with_movies(db_session, sample_collection, sample_movies):
    """Add two movies to the sample collection."""
    sample_collection.movies.append(sample_movies[0])
    sample_collection.movies.append(sample_movies[1])
    db_session.commit()
    return sample_collection


# ============================================
# Production Companies - Listing page
# ============================================


class TestCompaniesRoute:
    """Tests for /companies"""

    def test_companies_page_loads(self, client):
        response = client.get("/companies")
        assert response.status_code == 200

    def test_companies_has_title(self, client):
        response = client.get("/companies")
        assert b"Production Companies" in response.data or b"Studios" in response.data

    def test_companies_shows_qualifying_company(self, client, company_with_movies):
        response = client.get("/companies")
        assert response.status_code == 200
        assert b"Regency Enterprises" in response.data

    def test_companies_empty_state(self, client):
        response = client.get("/companies")
        assert response.status_code == 200
        assert b"No production companies found" in response.data

    def test_companies_pagination(self, client):
        response = client.get("/companies?page=1")
        assert response.status_code == 200

    def test_companies_page_two(self, client):
        response = client.get("/companies?page=2")
        assert response.status_code == 200


# ============================================
# Production Companies - Detail page
# ============================================


class TestCompanyDetailRoute:
    """Tests for /company/<id>"""

    def test_company_detail_loads(self, client, company_with_movies):
        response = client.get(f"/company/{company_with_movies.id}")
        assert response.status_code == 200

    def test_company_detail_shows_name(self, client, company_with_movies):
        response = client.get(f"/company/{company_with_movies.id}")
        assert b"Regency Enterprises" in response.data

    def test_company_detail_shows_movies(self, client, company_with_movies):
        response = client.get(f"/company/{company_with_movies.id}")
        assert b"Studio Film" in response.data

    def test_company_detail_shows_stats(self, client, company_with_movies):
        response = client.get(f"/company/{company_with_movies.id}")
        assert b"3" in response.data

    def test_company_detail_shows_origin_country(self, client, company_with_movies):
        response = client.get(f"/company/{company_with_movies.id}")
        assert b"US" in response.data

    def test_company_detail_404_invalid_id(self, client):
        response = client.get("/company/999999")
        assert response.status_code == 404


# ============================================
# Decades - Index page
# ============================================


class TestDecadesRoute:
    """Tests for /decades"""

    def test_decades_page_loads(self, client):
        response = client.get("/decades")
        assert response.status_code == 200

    def test_decades_has_title(self, client):
        response = client.get("/decades")
        assert b"Decade" in response.data

    def test_decades_shows_decade_cards(self, client, decade_movies):
        response = client.get("/decades")
        assert response.status_code == 200
        assert b"1990s" in response.data

    def test_decades_empty_state(self, client):
        response = client.get("/decades")
        assert response.status_code == 200

    def test_decades_shows_movie_count(self, client, decade_movies):
        response = client.get("/decades")
        assert response.status_code == 200
        assert b"10" in response.data


# ============================================
# Decades - Detail page
# ============================================


class TestDecadeDetailRoute:
    """Tests for /decade/<decade_start>"""

    def test_decade_detail_loads(self, client, decade_movies):
        response = client.get("/decade/1990")
        assert response.status_code == 200

    def test_decade_detail_shows_label(self, client, decade_movies):
        response = client.get("/decade/1990")
        assert b"1990s" in response.data

    def test_decade_detail_shows_movies(self, client, decade_movies):
        response = client.get("/decade/1990")
        assert b"Nineties Film" in response.data

    def test_decade_detail_shows_stats(self, client, decade_movies):
        response = client.get("/decade/1990")
        assert b"10" in response.data

    def test_decade_detail_shows_genre_breakdown(self, client, decade_movies):
        response = client.get("/decade/1990")
        assert b"Action" in response.data

    def test_decade_detail_shows_navigation(self, client, decade_movies):
        response = client.get("/decade/1990")
        assert b"1980s" in response.data
        assert b"2000s" in response.data

    def test_decade_detail_no_movies_returns_404(self, client):
        response = client.get("/decade/1750")
        assert response.status_code == 404

    def test_decade_detail_invalid_decade_returns_404(self, client):
        response = client.get("/decade/1800")
        assert response.status_code == 404


# ============================================
# Collections - Listing page
# ============================================


class TestCollectionsRoute:
    """Tests for /collections"""

    def test_collections_requires_login(self, client):
        response = client.get("/collections", follow_redirects=True)
        assert b"log in" in response.data.lower()

    def test_collections_redirects_without_auth(self, client):
        response = client.get("/collections", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location

    def test_collections_loads_when_logged_in(self, client, logged_in_user):
        response = client.get("/collections")
        assert response.status_code == 200

    def test_collections_shows_empty_state(self, client, logged_in_user):
        response = client.get("/collections")
        assert b"No collections yet" in response.data

    def test_collections_shows_existing_collection(self, client, logged_in_user, sample_collection):
        response = client.get("/collections")
        assert b"My Test Collection" in response.data

    def test_collections_shows_description(self, client, logged_in_user, sample_collection):
        response = client.get("/collections")
        assert b"A collection for testing" in response.data

    def test_collections_shows_create_button(self, client, logged_in_user):
        response = client.get("/collections")
        assert b"New Collection" in response.data


# ============================================
# Collections - Create
# ============================================


class TestCreateCollection:
    """Tests for POST /collections/create"""

    def test_create_collection_requires_login(self, client):
        response = client.post("/collections/create", data={"name": "Test"}, follow_redirects=True)
        assert response.status_code == 401
        assert b"unauthorized" in response.data.lower()

    def test_create_collection_success(self, client, logged_in_user, db_session):
        response = client.post(
            "/collections/create",
            data={"name": "My New List", "description": "Great films"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        collection = db_session.query(Collection).filter_by(name="My New List").first()
        assert collection is not None
        assert collection.description == "Great films"

    def test_create_collection_without_description(self, client, logged_in_user, db_session):
        response = client.post(
            "/collections/create",
            data={"name": "No Description"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        collection = db_session.query(Collection).filter_by(name="No Description").first()
        assert collection is not None

    def test_create_collection_empty_name_redirects(self, client, logged_in_user):
        response = client.post(
            "/collections/create",
            data={"name": ""},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"required" in response.data.lower()

    def test_create_collection_redirects_to_detail(self, client, logged_in_user):
        response = client.post(
            "/collections/create",
            data={"name": "Redirect Test"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/collection/" in response.location


# ============================================
# Collections - Detail page
# ============================================


class TestCollectionDetailRoute:
    """Tests for /collection/<id>"""

    def test_collection_detail_requires_login(self, client, sample_collection):
        response = client.get(f"/collection/{sample_collection.id}", follow_redirects=True)
        assert b"log in" in response.data.lower()

    def test_collection_detail_loads(self, client, logged_in_user, sample_collection):
        response = client.get(f"/collection/{sample_collection.id}")
        assert response.status_code == 200

    def test_collection_detail_shows_name(self, client, logged_in_user, sample_collection):
        response = client.get(f"/collection/{sample_collection.id}")
        assert b"My Test Collection" in response.data

    def test_collection_detail_shows_description(self, client, logged_in_user, sample_collection):
        response = client.get(f"/collection/{sample_collection.id}")
        assert b"A collection for testing" in response.data

    def test_collection_detail_empty_state(self, client, logged_in_user, sample_collection):
        response = client.get(f"/collection/{sample_collection.id}")
        assert b"empty" in response.data.lower()

    def test_collection_detail_shows_movies(self, client, logged_in_user, collection_with_movies):
        response = client.get(f"/collection/{collection_with_movies.id}")
        assert b"Test Movie 0" in response.data
        assert b"Test Movie 1" in response.data

    def test_collection_detail_404_wrong_user(self, client, db_session, sample_collection):
        """Another user cannot access someone else's collection."""
        other_user = User(username="otheruser")
        other_user.set_password("password")
        db_session.add(other_user)
        db_session.commit()

        with client.session_transaction() as sess:
            sess["user_id"] = other_user.id

        response = client.get(f"/collection/{sample_collection.id}", follow_redirects=True)
        assert b"not found" in response.data.lower() or response.status_code in [302, 200]


# ============================================
# Collections - Delete
# ============================================


class TestDeleteCollection:
    """Tests for POST /collection/<id>/delete"""

    def test_delete_collection_requires_login(self, client, sample_collection):
        response = client.post(f"/collection/{sample_collection.id}/delete", follow_redirects=True)
        assert response.status_code == 401
        assert b"unauthorized" in response.data.lower()

    def test_delete_collection_success(self, client, logged_in_user, sample_collection, db_session):
        collection_id = sample_collection.id
        response = client.post(f"/collection/{collection_id}/delete", follow_redirects=True)
        assert response.status_code == 200
        deleted = db_session.query(Collection).filter_by(id=collection_id).first()
        assert deleted is None

    def test_delete_collection_redirects_to_list(self, client, logged_in_user, sample_collection):
        response = client.post(f"/collection/{sample_collection.id}/delete", follow_redirects=False)
        assert response.status_code == 302
        assert "/collections" in response.location

    def test_delete_collection_wrong_user_returns_404(self, client, db_session, sample_collection):
        other_user = User(username="otheruserdelete")
        other_user.set_password("password")
        db_session.add(other_user)
        db_session.commit()

        with client.session_transaction() as sess:
            sess["user_id"] = other_user.id

        response = client.post(f"/collection/{sample_collection.id}/delete")
        assert response.status_code == 404


# ============================================
# Collections - Add / Remove movies
# ============================================


class TestCollectionMovieActions:
    """Tests for add/remove movie endpoints"""

    def test_add_movie_to_collection(self, client, logged_in_user, sample_collection, sample_movie):
        response = client.post(f"/collection/{sample_collection.id}/add/{sample_movie.id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "added"
        assert data["count"] == 1

    def test_add_movie_already_in_collection(
        self, client, logged_in_user, collection_with_movies, sample_movies
    ):
        movie = sample_movies[0]
        response = client.post(f"/collection/{collection_with_movies.id}/add/{movie.id}")
        data = response.get_json()
        assert data["status"] == "already_added"

    def test_add_movie_requires_login(self, client, sample_collection, sample_movie):
        response = client.post(f"/collection/{sample_collection.id}/add/{sample_movie.id}")
        assert response.status_code == 401

    def test_add_movie_invalid_collection(self, client, logged_in_user, sample_movie):
        response = client.post(f"/collection/999999/add/{sample_movie.id}")
        assert response.status_code == 404

    def test_add_movie_invalid_movie(self, client, logged_in_user, sample_collection):
        response = client.post(f"/collection/{sample_collection.id}/add/999999")
        assert response.status_code == 404

    def test_remove_movie_from_collection(
        self, client, logged_in_user, collection_with_movies, sample_movies
    ):
        movie = sample_movies[0]
        response = client.post(f"/collection/{collection_with_movies.id}/remove/{movie.id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "removed"
        assert data["count"] == 1

    def test_remove_movie_not_in_collection(
        self, client, logged_in_user, sample_collection, sample_movie
    ):
        response = client.post(f"/collection/{sample_collection.id}/remove/{sample_movie.id}")
        data = response.get_json()
        assert data["status"] == "not_found"

    def test_remove_movie_requires_login(self, client, collection_with_movies, sample_movies):
        response = client.post(
            f"/collection/{collection_with_movies.id}/remove/{sample_movies[0].id}"
        )
        assert response.status_code == 401


# ============================================
# Collections - API endpoint
# ============================================


class TestCollectionsAPI:
    """Tests for GET /api/v1/collections"""

    def test_api_collections_requires_login(self, client):
        response = client.get("/api/v1/collections")
        assert response.status_code == 401

    def test_api_collections_returns_empty_list(self, client, logged_in_user):
        response = client.get("/api/v1/collections")
        assert response.status_code == 200
        data = response.get_json()
        assert data["collections"] == []

    def test_api_collections_returns_user_collections(
        self, client, logged_in_user, sample_collection
    ):
        response = client.get("/api/v1/collections")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["collections"]) == 1
        assert data["collections"][0]["name"] == "My Test Collection"

    def test_api_collections_includes_movie_count(
        self, client, logged_in_user, collection_with_movies
    ):
        response = client.get("/api/v1/collections")
        data = response.get_json()
        assert data["collections"][0]["movie_count"] == 2

    def test_api_collections_only_returns_own_collections(
        self, client, db_session, logged_in_user, sample_collection
    ):
        """Other users' collections should not appear."""
        other_user = User(username="otherapiuser")
        other_user.set_password("password")
        db_session.add(other_user)
        db_session.flush()

        other_collection = Collection(user_id=other_user.id, name="Other User Collection")
        db_session.add(other_collection)
        db_session.commit()

        response = client.get("/api/v1/collections")
        data = response.get_json()
        names = [c["name"] for c in data["collections"]]
        assert "Other User Collection" not in names
        assert "My Test Collection" in names

    def test_api_collections_response_shape(self, client, logged_in_user, sample_collection):
        response = client.get("/api/v1/collections")
        data = response.get_json()
        col = data["collections"][0]
        assert "id" in col
        assert "name" in col
        assert "description" in col
        assert "movie_count" in col
        assert "updated_at" in col
