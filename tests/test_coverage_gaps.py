"""
Behavior that had no test before the 2026-11 scan (FS-16): collection
ownership on add and remove, advanced search, the actor network page, the
generic 500 handler, and admin listing details.
"""

import pytest

import src.app as app_module
from src.models import Cast, Collection, Movie, Person, User, collection_movies_table


@pytest.fixture
def two_users(db_session):
    owner, other = User(username="owner"), User(username="intruder")
    for user in (owner, other):
        user.set_password("password")
    db_session.add_all([owner, other])
    db_session.commit()
    return owner.id, other.id


@pytest.fixture
def owned_collection(db_session, two_users, sample_movie):
    owner_id, _ = two_users
    collection = Collection(user_id=owner_id, name="Mine")
    db_session.add(collection)
    db_session.commit()
    return {"id": collection.id, "movie_id": sample_movie.id}


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


class TestCollectionOwnership:
    def test_other_user_cannot_add(self, client, db_session, two_users, owned_collection):
        _login(client, two_users[1])

        response = client.post(
            f"/collection/{owned_collection['id']}/add/{owned_collection['movie_id']}"
        )

        assert response.status_code == 404
        assert db_session.query(collection_movies_table).count() == 0

    def test_other_user_cannot_remove(self, client, db_session, two_users, owned_collection):
        db_session.execute(
            collection_movies_table.insert().values(
                collection_id=owned_collection["id"], movie_id=owned_collection["movie_id"]
            )
        )
        db_session.commit()
        _login(client, two_users[1])

        response = client.post(
            f"/collection/{owned_collection['id']}/remove/{owned_collection['movie_id']}"
        )

        assert response.status_code == 404
        assert db_session.query(collection_movies_table).count() == 1

    def test_other_user_cannot_delete(self, client, db_session, two_users, owned_collection):
        _login(client, two_users[1])

        client.post(f"/collection/{owned_collection['id']}/delete")

        assert db_session.query(Collection).filter_by(id=owned_collection["id"]).count() == 1

    def test_names_over_255_characters_are_rejected(self, client, db_session, two_users):
        _login(client, two_users[0])

        client.post("/collections/create", data={"name": "x" * 256})

        assert db_session.query(Collection).count() == 0

    def test_owner_can_add_twice_without_error(
        self, client, db_session, two_users, owned_collection
    ):
        _login(client, two_users[0])
        url = f"/collection/{owned_collection['id']}/add/{owned_collection['movie_id']}"

        first = client.post(url).get_json()
        second = client.post(url).get_json()

        assert (first["status"], second["status"]) == ("added", "already_added")
        assert second["count"] == 1


class TestAdvancedSearch:
    def test_no_filters_runs_no_search(self, client, sample_movies):
        response = client.get("/advanced-search")

        assert response.status_code == 200
        assert b"Test Movie 0" not in response.data

    def test_text_and_rating_filters_combine(self, client, db_session):
        db_session.add_all(
            [
                Movie(
                    tmdb_id=1, title="Space Opera", vote_average=8.0, vote_count=900, popularity=5
                ),
                Movie(
                    tmdb_id=2, title="Space Junk", vote_average=4.0, vote_count=900, popularity=50
                ),
                Movie(
                    tmdb_id=3, title="Garden Party", vote_average=9.0, vote_count=900, popularity=9
                ),
            ]
        )
        db_session.commit()

        html = client.get("/advanced-search?q=space&rating_min=6").get_data(as_text=True)

        assert "Space Opera" in html
        assert "Space Junk" not in html
        assert "Garden Party" not in html

    def test_rating_sort_needs_enough_votes(self, client, db_session):
        db_session.add_all(
            [
                Movie(tmdb_id=4, title="One Vote Wonder", vote_average=10.0, vote_count=1),
                Movie(tmdb_id=5, title="Crowd Favorite", vote_average=8.5, vote_count=5000),
            ]
        )
        db_session.commit()

        html = client.get("/advanced-search?min_votes=0&sort=rating").get_data(as_text=True)

        assert "Crowd Favorite" in html
        assert "One Vote Wonder" not in html


class TestActorNetwork:
    def test_unknown_actor_is_404(self, client):
        assert client.get("/actor/999999/network").status_code == 404

    def test_graph_and_list_render(self, client, db_session):
        focal, friend = Person(tmdb_id=10, name="Focal Star"), Person(tmdb_id=11, name="Co Star")
        movie = Movie(tmdb_id=12, title="Shared Film", vote_count=10)
        db_session.add_all([focal, friend, movie])
        db_session.commit()
        db_session.add_all(
            [
                Cast(movie_id=movie.id, person_id=focal.id, character_name="A"),
                Cast(movie_id=movie.id, person_id=friend.id, character_name="B"),
            ]
        )
        db_session.commit()
        focal_id = focal.id

        html = client.get(f"/actor/{focal_id}/network").get_data(as_text=True)

        assert "Co Star" in html
        assert "Collaborators as a list" in html
        assert "Shared Film" in html  # edge tooltip data


class TestErrorHandling:
    def test_unhandled_exception_shows_the_error_page(self, app, client, monkeypatch):
        def explode(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(app_module, "_home_stats", explode)
        app.config["PROPAGATE_EXCEPTIONS"] = False

        response = client.get("/")

        assert response.status_code == 500
        assert b"Something went wrong" in response.data
        assert b"boom" not in response.data


class TestAdminListings:
    @pytest.fixture
    def admin_id(self, db_session):
        admin = User(username="chief", is_admin=True)
        admin.set_password("password")
        db_session.add(admin)
        db_session.commit()
        return admin.id

    def test_user_search_matches_underscore_literally(self, client, db_session, admin_id):
        for name in ("john_doe", "johnxdoe"):
            user = User(username=name)
            user.set_password("password")
            db_session.add(user)
        db_session.commit()
        _login(client, admin_id)

        html = client.get("/admin/users?q=john_doe").get_data(as_text=True)

        assert "john_doe" in html
        assert "johnxdoe" not in html

    def test_ban_unknown_user_flashes_not_found(self, client, admin_id):
        _login(client, admin_id)

        response = client.post("/admin/users/999999/ban", follow_redirects=True)

        assert b"User not found" in response.data

    def test_moderating_a_missing_review_flashes_not_found(self, client, admin_id):
        _login(client, admin_id)

        response = client.post("/admin/reviews/999999/soft-delete", follow_redirects=True)

        assert b"Review not found" in response.data

    def test_admin_next_redirect_rejects_external_urls(
        self, client, db_session, admin_id, sample_user
    ):
        target_id = sample_user.id
        _login(client, admin_id)

        response = client.post(
            f"/admin/users/{target_id}/ban", data={"next": "https://evil.example/"}
        )

        assert response.headers["Location"] == "/admin/users"
