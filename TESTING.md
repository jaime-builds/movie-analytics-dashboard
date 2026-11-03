# Testing Guide for Movie Analytics Dashboard

How the test suite is set up, how to run it, and how to add to it.

## Quick Start

```bash
pip install -r requirements.txt -r requirements-dev.txt

pytest                                  # whole suite, with coverage (see pytest.ini)
pytest -o addopts="" -q                 # quick run, no coverage
pytest tests/test_security.py -v        # one file
pytest tests/test_auth.py::TestAuthenticationRoutes::test_login_success
pytest -x                               # stop at the first failure
pytest --lf                             # rerun only last run's failures
```

The suite is **offline and needs no secrets**. `tests/conftest.py` sets a fake
`TMDB_API_KEY`, answers TMDB calls with an empty reply unless a test patches
`requests.get`, and fails any other real HTTP request. A local `config/.env` is
never needed for tests.

## Databases

- **Default:** each test gets a fresh in-memory SQLite database built from the
  models. Commits and rollbacks inside app code become savepoints, so a test can
  never leak data into the next one.
- **Postgres:** production runs Postgres 16, which enforces things SQLite
  doesn't (VARCHAR lengths, NULL sort order, numeric types). Point
  `TEST_DATABASE_URL` at an empty database whose name contains `test`:

  ```bash
  TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/dashboard_test \
  MIGRATION_TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/dashboard_migration_test \
  pytest -o addopts=""
  ```

  `MIGRATION_TEST_DATABASE_URL` enables the test that runs every Alembic
  migration on a fresh Postgres database (it drops and recreates that
  database's `public` schema). CI's `postgres` job sets both.

Never point either variable at the production database.

## Test Files

| File | Covers |
|---|---|
| `test_auth.py` | Registration, login, logout, favorites, watchlist, sessions, CSRF |
| `test_security.py` | Username rules, rate limits, revocable sessions, review deletion, security headers, HTTPS redirect, error pages, TMDB key redaction |
| `test_admin.py` | Admin access control, bans, registration setting, moderation, page views, `set-admin` command |
| `test_ratings_reviews.py` | Ratings and reviews, checked in the database |
| `test_routes.py` | Home, movies, movie detail, search, analytics, template filters |
| `test_route_fixes.py` | Pagination stability, filters, search ranking, API numbers, caching, page-view keys, Box Office by Genre |
| `test_discovery_and_profile_pages.py` | Hidden gems, top actors, actors, directors, recommendations, profile |
| `test_studios_decades_collections.py` | Studios, decades, collections and the collections API |
| `test_featured_content.py` | Home page and Movie of the Day content rules (mature flag, admin hide, vote minimum) |
| `test_features.py` | Family-friendly toggle, Blind Pick, Activity Feed, Year in Review, robots.txt, page-level checks |
| `test_coverage_gaps.py` | Collection ownership, advanced search, actor network, 500 page, admin edge cases |
| `test_api_routes.py` | JSON API |
| `test_movie_of_the_day.py` | Movie of the Day selection |
| `test_models.py` | Models, constraints and cascades |
| `test_migrations.py` | Alembic upgrade on SQLite (and Postgres when configured) |
| `test_config.py` | Production config checks |
| `test_tmdb_api.py` | TMDB client, including error and retry paths |
| `test_data_import.py` | `src/data_import.py` |
| `test_sync_script.py` | `scripts/sync_tmdb_data.py` and `scripts/backfill_mature_flags.py` |

## Fixtures (`tests/conftest.py`)

- `app`, `client`: the Flask app and a test client. App config changes made in
  a test are rolled back afterwards.
- `db_session`: the test database session. It replaces `src.helpers.session_factory`,
  so every route and request hook uses it too.
- `capture_sql`: records SQL statements, for query-shape tests.
- Data: `sample_genre`, `sample_person`, `sample_movie`, `sample_movies` (25),
  `sample_cast`, `sample_crew`, `sample_production_company`, `sample_user`,
  `logged_in_user`, `user_with_favorites`, `user_with_watchlist`, `multiple_users`.
- Automatic: `no_real_network` (see Quick Start).

Two habits keep tests reliable:

- Routes close the shared session, which detaches ORM objects loaded before the
  request. Read the ids you need (`movie_id = sample_movie.id`) **before** the
  request.
- Rate limiting is off by default. Tests that need it turn it on for a block and
  reset it afterwards (see `rate_limits_on` in `test_security.py`).

## Writing Tests

- Assert the behavior, not just the status code: check the database row, the
  redirect target, or the exact element on the page.
- Never loosen an assertion to make a test pass.
- Mock TMDB by patching `src.tmdb_api.requests.get` (or `src.tmdb_api.TMDBClient`
  methods for route-level tests).
- Patch a helper in the module that calls it, not where it is defined. For
  example, the home page calls `get_movie_of_the_day` through
  `src.routes.main`, so patch `src.routes.main.get_movie_of_the_day`.

```python
def test_search_finds_movies(client, sample_movie):
    response = client.get("/search?q=Fight")

    assert response.status_code == 200
    assert b"Fight Club" in response.data
```

## Coverage

```bash
pytest --cov=src --cov-report=term-missing
pytest --cov=src --cov-report=html   # then open htmlcov/index.html
```

Coverage settings live in `.coveragerc`. CI fails below 85%; the suite was at
95% on 2026-11-02.

## Lint and Security Checks

CI runs these on `src scripts migrations config tests`, with the versions pinned
in `requirements-dev.txt`:

```bash
flake8 src scripts migrations config tests
black --check src scripts migrations config tests --line-length 100
isort --check-only --profile black src scripts migrations config tests
bandit -r src scripts migrations config -ll
```

`pre-commit install` runs black, isort and whitespace checks on each commit.

## CI (`.github/workflows/tests.yml`)

- `test`: the suite on Python 3.11, 3.12 and 3.13 (no secrets needed).
- `postgres`: the suite and the migration test against a `postgres:16` service.
- `lint`, `security`: the checks above; both fail the build on problems.

`ci.yml` builds and pushes the Docker Hub image only after `Tests` passes on main.

## Smoke Test Against a Running Server

```bash
python scripts/smoke_test.py                                   # http://127.0.0.1:5000
python scripts/smoke_test.py https://movie-dashboard.jaime.build
```

Exits 0 when every check passes, 1 otherwise.
