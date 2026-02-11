import unittest
from datetime import datetime

from src.app import app
from src.models import Base, Genre, Movie, Rating, Review, Session, User, engine

# Initialize database tables before running tests
Base.metadata.create_all(engine)


class TestAuthentication(unittest.TestCase):
    """Test user authentication functionality"""

    @classmethod
    def setUpClass(cls):
        """Set up test database"""
        cls.app = app
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        """Create test data before each test"""
        self.session = Session()

        # Create test user
        self.test_user = User(username="testuser")
        self.test_user.set_password("password123")
        self.session.add(self.test_user)
        self.session.commit()

    def tearDown(self):
        """Clean up after each test"""
        self.session.query(User).filter_by(username="testuser").delete()
        self.session.query(User).filter_by(username="newuser").delete()
        self.session.commit()
        self.session.close()

    def test_register_success(self):
        """Test successful user registration"""
        response = self.client.post(
            "/register",
            data={
                "username": "newuser",
                "password": "password123",
                "password_confirm": "password123",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        user = self.session.query(User).filter_by(username="newuser").first()
        self.assertIsNotNone(user)

    def test_register_duplicate_username(self):
        """Test registration with existing username"""
        response = self.client.post(
            "/register",
            data={
                "username": "testuser",
                "password": "password123",
                "password_confirm": "password123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Username already exists", response.data)

    def test_register_password_mismatch(self):
        """Test registration with mismatched passwords"""
        response = self.client.post(
            "/register",
            data={
                "username": "newuser",
                "password": "password123",
                "password_confirm": "different",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Passwords do not match", response.data)

    def test_register_short_username(self):
        """Test registration with username too short"""
        response = self.client.post(
            "/register",
            data={"username": "ab", "password": "password123", "password_confirm": "password123"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Username must be at least 3 characters", response.data)

    def test_register_short_password(self):
        """Test registration with password too short"""
        response = self.client.post(
            "/register",
            data={"username": "newuser", "password": "12345", "password_confirm": "12345"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Password must be at least 6 characters", response.data)

    def test_login_success(self):
        """Test successful login"""
        response = self.client.post(
            "/login",
            data={"username": "testuser", "password": "password123"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)

        with self.client.session_transaction() as session:
            self.assertIn("user_id", session)

    def test_login_wrong_password(self):
        """Test login with incorrect password"""
        response = self.client.post(
            "/login", data={"username": "testuser", "password": "wrongpassword"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid username or password", response.data)

    def test_login_nonexistent_user(self):
        """Test login with non-existent username"""
        response = self.client.post(
            "/login", data={"username": "nonexistent", "password": "password123"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid username or password", response.data)

    def test_logout(self):
        """Test logout functionality"""
        # Login first
        self.client.post("/login", data={"username": "testuser", "password": "password123"})

        # Then logout
        response = self.client.get("/logout", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_login_redirect_next(self):
        """Test login redirect to 'next' parameter"""
        response = self.client.post(
            "/login?next=/favorites",
            data={"username": "testuser", "password": "password123"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/favorites", response.location)


class TestFavorites(unittest.TestCase):
    """Test favorites functionality"""

    @classmethod
    def setUpClass(cls):
        """Set up test application"""
        cls.app = app
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        """Create test data before each test"""
        self.session = Session()

        # Create test user
        self.test_user = User(username="testuser_fav")
        self.test_user.set_password("password123")
        self.session.add(self.test_user)

        # Get or create test genre
        self.test_genre = self.session.query(Genre).filter_by(tmdb_id=28).first()
        if not self.test_genre:
            self.test_genre = Genre(tmdb_id=28, name="Action")
            self.session.add(self.test_genre)

        # Create test movie with unique tmdb_id
        self.test_movie = Movie(
            tmdb_id=999912345,
            title="Test Movie Favorites",
            overview="A test movie",
            release_date=datetime(2020, 1, 1).date(),
            vote_average=7.5,
            vote_count=100,
            popularity=50.0,
        )
        self.session.add(self.test_movie)
        self.session.commit()

        # Login
        self.client.post("/login", data={"username": "testuser_fav", "password": "password123"})

    def tearDown(self):
        """Clean up after each test"""
        self.session.query(Movie).filter_by(tmdb_id=999912345).delete()
        self.session.query(User).filter_by(username="testuser_fav").delete()
        self.session.commit()
        self.session.close()

    def test_add_favorite_success(self):
        """Test adding movie to favorites"""
        response = self.client.post(f"/movie/{self.test_movie.id}/favorite")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn(data["status"], ["added", "already_added"])

    def test_add_favorite_already_exists(self):
        """Test adding already favorited movie"""
        # Add to favorites first
        self.client.post(f"/movie/{self.test_movie.id}/favorite")

        # Try to add again
        response = self.client.post(f"/movie/{self.test_movie.id}/favorite")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "already_added")

    def test_add_favorite_unauthorized(self):
        """Test adding favorite without login"""
        # Logout first
        self.client.get("/logout")

        response = self.client.post(f"/movie/{self.test_movie.id}/favorite")

        self.assertEqual(response.status_code, 401)

    def test_add_favorite_nonexistent_movie(self):
        """Test adding non-existent movie to favorites"""
        response = self.client.post("/movie/99999999/favorite")

        self.assertEqual(response.status_code, 404)

    def test_remove_favorite_success(self):
        """Test removing movie from favorites"""
        # Add to favorites first
        self.client.post(f"/movie/{self.test_movie.id}/favorite")

        # Remove from favorites
        response = self.client.post(f"/movie/{self.test_movie.id}/unfavorite")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "removed")

    def test_remove_favorite_not_in_list(self):
        """Test removing movie not in favorites"""
        # Ensure movie is not in favorites
        user = self.session.query(User).filter_by(username="testuser_fav").first()
        if self.test_movie in user.favorites.all():
            user.favorites.remove(self.test_movie)
            self.session.commit()

        response = self.client.post(f"/movie/{self.test_movie.id}/unfavorite")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "not_found")

    def test_view_favorites_page(self):
        """Test viewing favorites page"""
        # Add movie to favorites
        self.client.post(f"/movie/{self.test_movie.id}/favorite")

        # View favorites page
        response = self.client.get("/favorites")

        self.assertEqual(response.status_code, 200)

    def test_view_favorites_unauthorized(self):
        """Test viewing favorites page without login"""
        # Logout
        self.client.get("/logout")

        response = self.client.get("/favorites", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)


class TestWatchlist(unittest.TestCase):
    """Test watchlist functionality"""

    @classmethod
    def setUpClass(cls):
        """Set up test application"""
        cls.app = app
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        """Create test data before each test"""
        self.session = Session()

        # Create test user
        self.test_user = User(username="testuser_watch")
        self.test_user.set_password("password123")
        self.session.add(self.test_user)

        # Create test movie with unique tmdb_id
        self.test_movie = Movie(
            tmdb_id=999954321,
            title="Watchlist Movie Test",
            overview="A test movie",
            release_date=datetime(2020, 1, 1).date(),
            vote_average=7.5,
            vote_count=100,
            popularity=50.0,
        )
        self.session.add(self.test_movie)
        self.session.commit()

        # Login
        self.client.post("/login", data={"username": "testuser_watch", "password": "password123"})

    def tearDown(self):
        """Clean up after each test"""
        self.session.query(Movie).filter_by(tmdb_id=999954321).delete()
        self.session.query(User).filter_by(username="testuser_watch").delete()
        self.session.commit()
        self.session.close()

    def test_add_watchlist_success(self):
        """Test adding movie to watchlist"""
        response = self.client.post(f"/movie/{self.test_movie.id}/watchlist")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn(data["status"], ["added", "already_added"])

    def test_add_watchlist_already_exists(self):
        """Test adding already watchlisted movie"""
        self.client.post(f"/movie/{self.test_movie.id}/watchlist")
        response = self.client.post(f"/movie/{self.test_movie.id}/watchlist")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "already_added")

    def test_remove_watchlist_success(self):
        """Test removing movie from watchlist"""
        self.client.post(f"/movie/{self.test_movie.id}/watchlist")
        response = self.client.post(f"/movie/{self.test_movie.id}/unwatchlist")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "removed")

    def test_view_watchlist_page(self):
        """Test viewing watchlist page"""
        self.client.post(f"/movie/{self.test_movie.id}/watchlist")
        response = self.client.get("/watchlist")

        self.assertEqual(response.status_code, 200)


class TestRatingsAndReviews(unittest.TestCase):
    """Test ratings and reviews functionality"""

    @classmethod
    def setUpClass(cls):
        """Set up test application"""
        cls.app = app
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        """Create test data before each test"""
        self.session = Session()

        # Create test user
        self.test_user = User(username="testuser_rating")
        self.test_user.set_password("password123")
        self.session.add(self.test_user)

        # Create test movie with unique tmdb_id
        self.test_movie = Movie(
            tmdb_id=999999999,
            title="Rating Test Movie",
            overview="A test movie",
            release_date=datetime(2020, 1, 1).date(),
            vote_average=7.5,
            vote_count=100,
            popularity=50.0,
        )
        self.session.add(self.test_movie)
        self.session.commit()

        # Login
        self.client.post("/login", data={"username": "testuser_rating", "password": "password123"})

    def tearDown(self):
        """Clean up after each test"""
        self.session.query(Rating).filter_by(movie_id=self.test_movie.id).delete()
        self.session.query(Review).filter_by(movie_id=self.test_movie.id).delete()
        self.session.query(Movie).filter_by(tmdb_id=999999999).delete()
        self.session.query(User).filter_by(username="testuser_rating").delete()
        self.session.commit()
        self.session.close()

    def test_submit_rating_success(self):
        """Test submitting a rating"""
        response = self.client.post(f"/movie/{self.test_movie.id}/rate", data={"rating": 4})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["rating"], 4)

    def test_submit_rating_invalid_value(self):
        """Test submitting invalid rating"""
        response = self.client.post(f"/movie/{self.test_movie.id}/rate", data={"rating": 6})

        self.assertEqual(response.status_code, 400)

    def test_update_rating(self):
        """Test updating existing rating"""
        self.client.post(f"/movie/{self.test_movie.id}/rate", data={"rating": 3})
        response = self.client.post(f"/movie/{self.test_movie.id}/rate", data={"rating": 5})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["rating"], 5)

    def test_submit_review_success(self):
        """Test submitting a review"""
        response = self.client.post(
            f"/movie/{self.test_movie.id}/review",
            data={"review_content": "This is a great test movie with excellent testing."},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"review has been submitted", response.data)

    def test_submit_review_too_short(self):
        """Test submitting review that's too short"""
        response = self.client.post(
            f"/movie/{self.test_movie.id}/review",
            data={"review_content": "Short"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"at least 10 characters", response.data)


if __name__ == "__main__":
    unittest.main()
