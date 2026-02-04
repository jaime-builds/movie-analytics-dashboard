# Testing Guide for Movie Analytics Dashboard

This guide covers everything you need to know about testing in this project.

## Quick Start

### 1. Install Testing Dependencies

```bash
pip install pytest pytest-flask pytest-cov coverage
```

Or update your `requirements.txt`:
```txt
pytest>=7.4.0
pytest-flask>=1.2.0
pytest-cov>=4.1.0
coverage>=7.2.0
```

### 2. Run Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_routes.py

# Run specific test class
pytest tests/test_routes.py::TestIndexRoute

# Run specific test function
pytest tests/test_routes.py::TestIndexRoute::test_index_loads

# Run with coverage report
pytest --cov=src --cov-report=html

# Run and show print statements
pytest -s

# Run tests in parallel (faster)
pytest -n auto  # requires pytest-xdist
```

## Test Structure

```
tests/
├── __init__.py
├── conftest.py           # Shared fixtures and configuration
├── test_routes.py        # Tests for Flask routes
├── test_models.py        # Tests for database models
└── test_tmdb_api.py      # Tests for TMDB API client
```

## Writing Tests

### Test Naming Convention

- Test files: `test_*.py` or `*_test.py`
- Test classes: `Test*`
- Test functions: `test_*`

### Using Fixtures

Fixtures are reusable test components defined in `conftest.py`:

```python
def test_movie_detail(client, sample_movie):
    """Test uses client and sample_movie fixtures"""
    response = client.get(f'/movie/{sample_movie.id}')
    assert response.status_code == 200
```

Available fixtures:
- `app` - Flask application
- `client` - Test client for making requests
- `db_session` - Database session
- `sample_movie` - Pre-created movie
- `sample_movies` - List of 25 movies
- `sample_genre` - Pre-created genre
- `sample_person` - Pre-created actor
- `sample_cast` - Pre-created cast member
- `sample_crew` - Pre-created crew member
- `sample_production_company` - Pre-created company

### Example Test

```python
def test_search_finds_movies(client, sample_movie):
    """Test that search finds movies by title"""
    # Make request to search endpoint
    response = client.get('/search?q=Fight')

    # Assert response is successful
    assert response.status_code == 200

    # Assert movie title is in response
    assert b'Fight Club' in response.data
```

## Test Coverage

### Generate Coverage Report

```bash
# Terminal report
pytest --cov=src --cov-report=term-missing

# HTML report (opens in browser)
pytest --cov=src --cov-report=html
open htmlcov/index.html

# XML report (for CI/CD)
pytest --cov=src --cov-report=xml
```

### Coverage Goals

- **Overall**: Aim for 80%+ coverage
- **Critical paths**: 100% coverage for routes, models
- **API client**: 70%+ (some parts are hard to test)

## GitHub Actions CI/CD

### Setting Up

1. **Add TMDB API Key to GitHub Secrets**
   - Go to repo Settings → Secrets and variables → Actions
   - Click "New repository secret"
   - Name: `TMDB_API_KEY`
   - Value: Your TMDB API key

2. **Commit the workflow file**
   ```bash
   git add .github/workflows/tests.yml
   git commit -m "Add GitHub Actions testing workflow"
   git push
   ```

3. **Tests run automatically on every push and PR!**

### Viewing Test Results

- Go to your GitHub repo → Actions tab
- Click on the latest workflow run
- See test results, coverage, and any failures

### Branch Protection

Set up branch protection to require tests to pass:

1. Go to Settings → Branches
2. Click "Add rule"
3. Branch name pattern: `main`
4. Check ✅ "Require status checks to pass before merging"
5. Select: `test` (your workflow job)
6. Save

Now PRs will require all tests to pass before merging!

## Pre-commit Hooks (Optional)

Run tests automatically before every commit:

```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Now tests run automatically on git commit!

# Run manually on all files
pre-commit run --all-files

# Skip pre-commit hooks (not recommended)
git commit --no-verify
```

## Common Testing Patterns

### Testing Flask Routes

```python
def test_route(client):
    response = client.get('/endpoint')
    assert response.status_code == 200
    assert b'expected text' in response.data
```

### Testing Database Models

```python
def test_create_model(db_session):
    model = Movie(title="Test", tmdb_id=123)
    db_session.add(model)
    db_session.commit()

    assert model.id is not None
    assert model.title == "Test"
```

### Testing with Mock Data

```python
from unittest.mock import patch, Mock

@patch('src.tmdb_api.requests.get')
def test_api_call(mock_get):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'results': []}
    mock_get.return_value = mock_response

    # Your test code here
```

### Testing Relationships

```python
def test_relationship(db_session):
    movie = Movie(title="Test", tmdb_id=1)
    genre = Genre(name="Action", tmdb_id=28)
    movie.genres.append(genre)

    db_session.add(movie)
    db_session.commit()

    assert len(movie.genres) == 1
    assert genre in movie.genres
```

## Debugging Failing Tests

### Run with verbose output
```bash
pytest -vv
```

### Show print statements
```bash
pytest -s
```

### Stop on first failure
```bash
pytest -x
```

### Drop into debugger on failure
```bash
pytest --pdb
```

### Run only failed tests from last run
```bash
pytest --lf  # last failed
pytest --ff  # failed first
```

## Test Organization Tips

1. **One assertion per test** (when possible)
   ```python
   # Good
   def test_movie_title(sample_movie):
       assert sample_movie.title == "Fight Club"

   def test_movie_rating(sample_movie):
       assert sample_movie.vote_average == 8.4
   ```

2. **Use descriptive test names**
   ```python
   # Good
   def test_search_finds_movies_by_title()

   # Bad
   def test_search()
   ```

3. **Arrange-Act-Assert pattern**
   ```python
   def test_example():
       # Arrange - set up test data
       movie = Movie(title="Test")

       # Act - perform the action
       result = movie.title.upper()

       # Assert - verify the result
       assert result == "TEST"
   ```

## Common Issues

### Issue: Tests can't find modules
**Solution**: Make sure you're running pytest from the project root directory

### Issue: Database errors
**Solution**: Check that fixtures are properly cleaning up (see `conftest.py`)

### Issue: API tests failing
**Solution**: Make sure TMDB_API_KEY is set in environment or use mocks

### Issue: Tests pass locally but fail in CI
**Solution**: Check that all dependencies are in `requirements.txt`

## Adding New Tests

When adding a new feature:

1. Write tests FIRST (Test-Driven Development)
2. Run tests to see them fail
3. Implement the feature
4. Run tests to see them pass
5. Refactor if needed

Example workflow:
```bash
# 1. Create test
echo "def test_new_feature(): assert False" >> tests/test_new.py

# 2. Run test (should fail)
pytest tests/test_new.py

# 3. Implement feature in src/

# 4. Run test again (should pass)
pytest tests/test_new.py

# 5. Run all tests
pytest
```

## Performance Testing

For testing with many movies:

```python
def test_performance(db_session):
    import time

    # Create 1000 movies
    start = time.time()
    movies = [Movie(title=f"Movie {i}", tmdb_id=i) for i in range(1000)]
    db_session.add_all(movies)
    db_session.commit()
    duration = time.time() - start

    # Should complete in reasonable time
    assert duration < 5.0  # 5 seconds
```

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Flask Testing Documentation](https://flask.palletsprojects.com/en/latest/testing/)
- [SQLAlchemy Testing Documentation](https://docs.sqlalchemy.org/en/latest/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites)

## Questions?

If you run into issues:
1. Check this guide
2. Look at existing tests for examples
3. Read error messages carefully
4. Check test output with `pytest -vv`

Happy testing! 🧪
