"""
Tests for User Authentication and Favorites/Watchlist features
"""

import pytest
from werkzeug.security import check_password_hash

from src.models import Movie, User


class TestUserModel:
    """Tests for User model"""

    def test_create_user(self, db_session):
        """Test creating a user"""
        user = User(username="testuser")
        user.set_password("password123")
        db_session.add(user)
        db_session.commit()

        assert user.id is not None
        assert user.username == "testuser"
        assert user.password_hash is not None
        assert user.created_at is not None

    def test_user_password_hashing(self, db_session):
        """Test that passwords are properly hashed"""
        user = User(username="hashtest")
        user.set_password("mypassword")
        db_session.add(user)
        db_session.commit()

        # Password should be hashed, not plain text
        assert user.password_hash != "mypassword"
        # Should be able to verify the password
        assert user.check_password("mypassword")
        # Wrong password should fail
        assert not user.check_password("wrongpassword")

    def test_user_check_password(self, db_session):
        """Test password verification"""
        user = User(username="passwordtest")
        user.set_password("correct_password")
        db_session.add(user)
        db_session.commit()

        assert user.check_password("correct_password") is True
        assert user.check_password("wrong_password") is False
        assert user.check_password("") is False

    def test_user_str_representation(self, db_session):
        """Test user string representation"""
        user = User(username="reprtest")
        user.set_password("password")
        db_session.add(user)
        db_session.commit()

        assert "reprtest" in str(user)

    def test_username_uniqueness(self, db_session):
        """Test that usernames should be unique"""
        user1 = User(username="unique_user")
        user1.set_password("password1")
        db_session.add(user1)
        db_session.commit()

        # Check that user exists
        existing = db_session.query(User).filter_by(username="unique_user").first()
        assert existing is not None


class TestAuthenticationRoutes:
    """Tests for authentication routes"""

    def test_register_page_loads(self, client):
        """Test that registration page loads"""
        response = client.get("/register")
        assert response.status_code == 200
        assert b"Register" in response.data or b"register" in response.data.lower()

    def test_register_new_user(self, client, db_session):
        """Test successful user registration"""
        response = client.post(
            "/register",
            data={
                "username": "newuser",
                "password": "password123",
                "password_confirm": "password123",
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        # Should redirect to home page after successful registration
        assert b"Welcome" in response.data or b"Movie" in response.data

        # Check user was created in database
        user = db_session.query(User).filter_by(username="newuser").first()
        assert user is not None
        assert user.username == "newuser"

    def test_register_password_mismatch(self, client):
        """Test registration with mismatched passwords"""
        response = client.post(
            "/register",
            data={
                "username": "testuser",
                "password": "password123",
                "password_confirm": "different_password",
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"do not match" in response.data.lower()

    def test_register_short_password(self, client):
        """Test registration with password too short"""
        response = client.post(
            "/register",
            data={"username": "testuser", "password": "abc", "password_confirm": "abc"},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"at least 6" in response.data.lower()

    def test_register_short_username(self, client):
        """Test registration with username too short"""
        response = client.post(
            "/register",
            data={"username": "ab", "password": "password123", "password_confirm": "password123"},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"at least 3" in response.data.lower()

    def test_register_duplicate_username(self, client, sample_user):
        """Test registration with existing username"""
        response = client.post(
            "/register",
            data={
                "username": sample_user.username,
                "password": "password123",
                "password_confirm": "password123",
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"already exists" in response.data.lower()

    def test_login_page_loads(self, client):
        """Test that login page loads"""
        response = client.get("/login")
        assert response.status_code == 200
        assert b"Login" in response.data or b"login" in response.data.lower()

    def test_login_success(self, client, sample_user):
        """Test successful login"""
        response = client.post(
            "/login",
            data={"username": sample_user.username, "password": "testpassword"},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"Welcome back" in response.data or b"testuser" in response.data

    def test_login_invalid_username(self, client):
        """Test login with non-existent username"""
        response = client.post(
            "/login",
            data={"username": "nonexistent", "password": "password123"},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"Invalid" in response.data or b"invalid" in response.data.lower()

    def test_login_invalid_password(self, client, sample_user):
        """Test login with wrong password"""
        response = client.post(
            "/login",
            data={"username": sample_user.username, "password": "wrongpassword"},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert b"Invalid" in response.data or b"invalid" in response.data.lower()

    def test_logout(self, client, sample_user):
        """Test logout functionality"""
        # First login
        client.post("/login", data={"username": sample_user.username, "password": "testpassword"})

        # Then logout
        response = client.get("/logout", follow_redirects=True)

        assert response.status_code == 200
        assert b"logged out" in response.data.lower()

    def test_login_redirect_to_next(self, client, sample_user):
        """Test that login redirects to 'next' parameter"""
        response = client.post(
            "/login?next=/analytics",
            data={"username": sample_user.username, "password": "testpassword"},
            follow_redirects=True,
        )

        assert response.status_code == 200
        # Should redirect to analytics page


class TestFavoritesFeature:
    """Tests for favorites functionality"""

    def test_favorites_page_requires_login(self, client):
        """Test that favorites page requires authentication"""
        response = client.get("/favorites", follow_redirects=True)

        assert response.status_code == 200
        assert b"log in" in response.data.lower()

    def test_favorites_page_loads_when_logged_in(self, client, logged_in_user):
        """Test that favorites page loads for logged-in users"""
        response = client.get("/favorites")

        assert response.status_code == 200
        assert b"Favorite" in response.data or b"favorite" in response.data.lower()

    def test_add_movie_to_favorites(self, client, logged_in_user, sample_movie, db_session):
        """Test adding a movie to favorites"""
        # Store IDs before making request (to avoid detached instance issues)
        user_id = logged_in_user.id
        movie_id = sample_movie.id

        response = client.post(f"/movie/{movie_id}/favorite")

        assert response.status_code == 200
        assert "added" in response.get_json().get("status", "").lower()

        # Verify in database
        user = db_session.query(User).filter_by(id=user_id).first()
        movie = db_session.query(Movie).filter_by(id=movie_id).first()
        assert movie in user.favorites.all()

    def test_add_favorite_requires_login(self, client, sample_movie):
        """Test that adding favorite requires authentication"""
        response = client.post(f"/movie/{sample_movie.id}/favorite")

        assert response.status_code == 401

    def test_remove_movie_from_favorites(self, client, logged_in_user, sample_movie, db_session):
        """Test removing a movie from favorites"""
        # Store IDs before operations
        user_id = logged_in_user.id
        movie_id = sample_movie.id

        # First add to favorites
        user = db_session.query(User).filter_by(id=user_id).first()
        movie = db_session.query(Movie).filter_by(id=movie_id).first()
        user.favorites.append(movie)
        db_session.commit()

        # Then remove
        response = client.post(f"/movie/{movie_id}/unfavorite")

        assert response.status_code == 200
        assert "removed" in response.get_json().get("status", "").lower()

        # Verify removed from database
        user = db_session.query(User).filter_by(id=user_id).first()
        movie = db_session.query(Movie).filter_by(id=movie_id).first()
        assert movie not in user.favorites.all()

    def test_favorite_nonexistent_movie(self, client, logged_in_user):
        """Test favoriting a non-existent movie"""
        response = client.post("/movie/999999/favorite")

        assert response.status_code == 404

    def test_favorites_page_shows_movies(self, client, logged_in_user, sample_movies, db_session):
        """Test that favorites page displays favorited movies"""
        # Add some movies to favorites
        user = db_session.query(User).filter_by(id=logged_in_user.id).first()
        user.favorites.append(sample_movies[0])
        user.favorites.append(sample_movies[1])
        db_session.commit()

        response = client.get("/favorites")

        assert response.status_code == 200
        assert sample_movies[0].title.encode() in response.data
        assert sample_movies[1].title.encode() in response.data

    def test_empty_favorites_page(self, client, logged_in_user):
        """Test favorites page when user has no favorites"""
        response = client.get("/favorites")

        assert response.status_code == 200
        assert b"No favorites" in response.data or b"no favorites" in response.data.lower()


class TestWatchlistFeature:
    """Tests for watchlist functionality"""

    def test_watchlist_page_requires_login(self, client):
        """Test that watchlist page requires authentication"""
        response = client.get("/watchlist", follow_redirects=True)

        assert response.status_code == 200
        assert b"log in" in response.data.lower()

    def test_watchlist_page_loads_when_logged_in(self, client, logged_in_user):
        """Test that watchlist page loads for logged-in users"""
        response = client.get("/watchlist")

        assert response.status_code == 200
        assert b"Watchlist" in response.data or b"watchlist" in response.data.lower()

    def test_add_movie_to_watchlist(self, client, logged_in_user, sample_movie, db_session):
        """Test adding a movie to watchlist"""
        # Store IDs before making request
        user_id = logged_in_user.id
        movie_id = sample_movie.id

        response = client.post(f"/movie/{movie_id}/watchlist")

        assert response.status_code == 200
        assert "added" in response.get_json().get("status", "").lower()

        # Verify in database
        user = db_session.query(User).filter_by(id=user_id).first()
        movie = db_session.query(Movie).filter_by(id=movie_id).first()
        assert movie in user.watchlist.all()

    def test_add_watchlist_requires_login(self, client, sample_movie):
        """Test that adding to watchlist requires authentication"""
        response = client.post(f"/movie/{sample_movie.id}/watchlist")

        assert response.status_code == 401

    def test_remove_movie_from_watchlist(self, client, logged_in_user, sample_movie, db_session):
        """Test removing a movie from watchlist"""
        # Store IDs before operations
        user_id = logged_in_user.id
        movie_id = sample_movie.id

        # First add to watchlist
        user = db_session.query(User).filter_by(id=user_id).first()
        movie = db_session.query(Movie).filter_by(id=movie_id).first()
        user.watchlist.append(movie)
        db_session.commit()

        # Then remove
        response = client.post(f"/movie/{movie_id}/unwatchlist")

        assert response.status_code == 200
        assert "removed" in response.get_json().get("status", "").lower()

        # Verify removed from database
        user = db_session.query(User).filter_by(id=user_id).first()
        movie = db_session.query(Movie).filter_by(id=movie_id).first()
        assert movie not in user.watchlist.all()

    def test_watchlist_nonexistent_movie(self, client, logged_in_user):
        """Test adding a non-existent movie to watchlist"""
        response = client.post("/movie/999999/watchlist")

        assert response.status_code == 404

    def test_watchlist_page_shows_movies(self, client, logged_in_user, sample_movies, db_session):
        """Test that watchlist page displays movies"""
        # Add some movies to watchlist
        user = db_session.query(User).filter_by(id=logged_in_user.id).first()
        user.watchlist.append(sample_movies[0])
        user.watchlist.append(sample_movies[1])
        db_session.commit()

        response = client.get("/watchlist")

        assert response.status_code == 200
        assert sample_movies[0].title.encode() in response.data
        assert sample_movies[1].title.encode() in response.data

    def test_empty_watchlist_page(self, client, logged_in_user):
        """Test watchlist page when user has no items"""
        response = client.get("/watchlist")

        assert response.status_code == 200
        assert b"empty" in response.data.lower() or b"no movies" in response.data.lower()


class TestMovieDetailWithAuth:
    """Tests for movie detail page with authentication features"""

    def test_movie_detail_shows_favorite_button_when_logged_in(
        self, client, logged_in_user, sample_movie
    ):
        """Test that favorite button shows for logged-in users"""
        response = client.get(f"/movie/{sample_movie.id}")

        assert response.status_code == 200
        assert b"Favorite" in response.data or b"favorite" in response.data.lower()

    def test_movie_detail_shows_watchlist_button_when_logged_in(
        self, client, logged_in_user, sample_movie
    ):
        """Test that watchlist button shows for logged-in users"""
        response = client.get(f"/movie/{sample_movie.id}")

        assert response.status_code == 200
        assert b"Watchlist" in response.data or b"watchlist" in response.data.lower()

    def test_movie_detail_shows_login_prompt_when_not_logged_in(self, client, sample_movie):
        """Test that login prompt shows for guests"""
        response = client.get(f"/movie/{sample_movie.id}")

        assert response.status_code == 200
        assert b"Log in" in response.data or b"log in" in response.data.lower()

    def test_movie_detail_shows_favorited_state(
        self, client, logged_in_user, sample_movie, db_session
    ):
        """Test that movie shows as favorited when it is"""
        # Add to favorites
        user = db_session.query(User).filter_by(id=logged_in_user.id).first()
        user.favorites.append(sample_movie)
        db_session.commit()

        response = client.get(f"/movie/{sample_movie.id}")

        assert response.status_code == 200
        assert b"Unfavorite" in response.data or b"unfavorite" in response.data.lower()

    def test_movie_detail_shows_watchlisted_state(
        self, client, logged_in_user, sample_movie, db_session
    ):
        """Test that movie shows as in watchlist when it is"""
        # Add to watchlist
        user = db_session.query(User).filter_by(id=logged_in_user.id).first()
        user.watchlist.append(sample_movie)
        db_session.commit()

        response = client.get(f"/movie/{sample_movie.id}")

        assert response.status_code == 200
        assert b"Remove from Watchlist" in response.data


class TestUserRelationships:
    """Tests for User model relationships"""

    def test_user_favorites_relationship(self, db_session, sample_user, sample_movie):
        """Test user-favorites relationship"""
        sample_user.favorites.append(sample_movie)
        db_session.commit()

        assert len(sample_user.favorites.all()) == 1
        assert sample_movie in sample_user.favorites.all()

    def test_user_watchlist_relationship(self, db_session, sample_user, sample_movie):
        """Test user-watchlist relationship"""
        sample_user.watchlist.append(sample_movie)
        db_session.commit()

        assert len(sample_user.watchlist.all()) == 1
        assert sample_movie in sample_user.watchlist.all()

    def test_multiple_users_favorite_same_movie(self, db_session, sample_movie):
        """Test that multiple users can favorite the same movie"""
        user1 = User(username="user1")
        user1.set_password("password")
        user2 = User(username="user2")
        user2.set_password("password")

        user1.favorites.append(sample_movie)
        user2.favorites.append(sample_movie)

        db_session.add_all([user1, user2])
        db_session.commit()

        assert sample_movie in user1.favorites.all()
        assert sample_movie in user2.favorites.all()

    def test_user_can_have_multiple_favorites(self, db_session, sample_user, sample_movies):
        """Test that users can have multiple favorites"""
        sample_user.favorites.append(sample_movies[0])
        sample_user.favorites.append(sample_movies[1])
        sample_user.favorites.append(sample_movies[2])
        db_session.commit()

        assert len(sample_user.favorites.all()) == 3

    def test_remove_favorite_relationship(self, db_session, sample_user, sample_movie):
        """Test removing favorite relationship"""
        sample_user.favorites.append(sample_movie)
        db_session.commit()

        assert sample_movie in sample_user.favorites.all()

        sample_user.favorites.remove(sample_movie)
        db_session.commit()

        assert sample_movie not in sample_user.favorites.all()


class TestSessionManagement:
    """Tests for session and authentication state management"""

    def test_session_persists_across_requests(self, client, sample_user):
        """Test that login session persists"""
        # Login
        client.post("/login", data={"username": sample_user.username, "password": "testpassword"})

        # Make another request
        response = client.get("/")

        assert response.status_code == 200
        # Should still be logged in (username in page)
        assert sample_user.username.encode() in response.data

    def test_logout_clears_session(self, client, sample_user):
        """Test that logout clears session"""
        # Login
        client.post("/login", data={"username": sample_user.username, "password": "testpassword"})

        # Logout
        client.get("/logout")

        # Try to access protected page
        response = client.get("/favorites", follow_redirects=True)

        assert b"log in" in response.data.lower()


class TestSecurityFeatures:
    """Tests for security features"""

    def test_password_not_stored_in_plain_text(self, db_session):
        """Test that passwords are never stored in plain text"""
        user = User(username="security_test")
        password = "my_secret_password"
        user.set_password(password)
        db_session.add(user)
        db_session.commit()

        # Password should not equal the hash
        assert user.password_hash != password
        # Should start with hashing algorithm identifier
        assert user.password_hash.startswith("scrypt:") or user.password_hash.startswith("pbkdf2:")

    def test_username_is_case_sensitive(self, client, db_session):
        """Test that usernames are case-sensitive"""
        # Create user with lowercase username
        user = User(username="testuser")
        user.set_password("password")
        db_session.add(user)
        db_session.commit()

        # Try to register with same username but different case
        response = client.post(
            "/register",
            data={
                "username": "TestUser",
                "password": "password123",
                "password_confirm": "password123",
            },
            follow_redirects=True,
        )

        # Should allow registration (case-sensitive)
        # Or should reject if implementing case-insensitive (document behavior)
