# 🎬 Movie Analytics Dashboard

> A full-stack movie discovery platform with user authentication, personalized collections, and comprehensive analytics — built to showcase modern web development skills.

![Tests](https://github.com/jaime-builds/movie-analytics-dashboard/actions/workflows/tests.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![Flask](https://img.shields.io/badge/flask-3.1-green)
![SQLAlchemy](https://img.shields.io/badge/sqlalchemy-2.0-orange)

📺 **[Live Demo](https://movie-dashboard.jaime.build)**

![Movie Analytics Dashboard](docs/screenshot.png)

## 🚀 Quick Start

```bash
# Clone and setup
git clone https://github.com/jaime-builds/movie-analytics-dashboard.git
cd movie-analytics-dashboard
python -m venv venv && source venv/bin/activate  # or .\venv\Scripts\activate on Windows

# Install and configure
pip install -r requirements.txt -r requirements-dev.txt  # app + test/lint tools
echo "TMDB_API_KEY=your_key_here" > config/.env
echo "SECRET_KEY=your_secret_here" >> config/.env

# Initialize and run
alembic upgrade head  # Create or upgrade database schema
python scripts/sync_tmdb_data.py --limit 1000  # Quick initial data (5 min)
python -m src.app  # Start server at http://127.0.0.1:5000
```

Get your [TMDB API key here](https://www.themoviedb.org/settings/api) (free, takes 2 minutes).

**Make yourself an admin** (after registering in the browser):

```bash
flask --app src.app set-admin your_username          # local
docker exec dashboard-app flask --app src.app set-admin your_username   # production
flask --app src.app set-admin your_username --revoke # remove admin rights
```

## 💡 What Makes This Special

This isn't just another movie app. It's a **portfolio-grade full-stack application** that demonstrates:

### 🎯 Core Features

| Feature | Description |
|---------|-------------|
| 🔐 **Authentication** | Secure login/registration with password hashing |
| 🔒 **CSRF Protection** | Flask-WTF token validation on all state-changing routes and JavaScript fetch requests |
| 💖 **Personalization** | Favorites & watchlist collections per user |
| ⭐ **Ratings & Reviews** | 1-5 star ratings and text reviews for movies |
| 🎯 **Recommendations** | Personalized suggestions based on your favorites |
| 🎬 **Director Spotlight** | Explore 300+ directors with complete filmographies |
| 🏢 **Studios** | Browse production companies with filmographies and box office stats |
| 🗓️ **Decade Overview** | Curated pages per decade with defining films, top rated, genre breakdown |
| 🗂️ **Movie Collections** | Create and manage named lists of your favorite movies |
| 📊 **Analytics Dashboard** | Interactive Chart.js visualizations including budget/revenue scatter and profitability charts |
| 🔄 **Auto-Sync** | Weekly scheduled job syncing 5,000 movies from TMDB |
| 🎭 **Actor Profiles** | Top actors with photos, filmography, and collaboration network |
| 🕸️ **Collaboration Network** | D3.js force graph showing actor connections weighted by shared films |
| 🎞️ **Common Films** | Find movies shared by any combination of up to 5 actors |
| 💎 **Hidden Gems** | Smart algorithm discovers underrated films |
| 🌙 **Dark Mode** | Full theme support with localStorage |
| 📱 **Mobile Responsive** | Optimized layouts for all screen sizes |
| 🔌 **RESTful API** | JSON endpoints for movies, analytics, actors, and collections |
| 👤 **User Profile** | Activity dashboard with ratings, reviews, favorites, watchlist, and collections |
| ⚡ **Infinite Scroll** | Seamless movie browsing without pagination |
| 🔍 **Search Autocomplete** | Live dropdown with poster thumbnails and keyboard navigation |
| 🔎 **Advanced Search** | Combine title, genre, era, rating, and runtime filters in one unified UI |
| ⚖️ **Movie Comparison** | Select up to 4 movies for side-by-side stats and visual charts |
| 📺 **Streaming Availability** | Where to Watch card showing stream/rent/buy options via TMDB/JustWatch |
| 🚀 **Query Caching** | Flask-Caching on analytics and genre routes (1-hour TTL) |
| 🎛️ **Advanced Filters** | Min vote count and status filters with collapsible panel |
| 🏠 **Home Page Hero** | Two-column hero with live stats bar, jaime-builds branding, and feature shortcut cards |
| 🎬 **Movie of the Day** | Featured pick on the homepage from the Hidden Gems pool, deterministic per day with a 30-day anti-repeat window |
| 🍞 **Breadcrumb Navigation** | Bootstrap 5 breadcrumb trail on every page except home |
| 📤 **CSV Export** | Download full analytics data as a CSV file |
| 🚦 **Rate Limiting** | Flask-Limiter protecting all API and analytics endpoints |
| 📋 **Structured Logging** | JSON request logging with daily rotation, failed login tracking, and error alerting |
| 🐳 **Docker** | Dockerfile + docker-compose with volume mounts and health check |
| 🛡️ **Admin Dashboard** | Site analytics, user ban/unban with content hidden site-wide, registration toggle, soft/hard-delete moderation for ratings and reviews |

### 🎨 User Experience

<div align="center">

| Favorites Collection | Watchlist Tracking | User Profile |
|:-------------------:|:-----------------:|:-----------:|
| ![Favorites](docs/favorites.png) | ![Watchlist](docs/watchlist.png) | ![Profile](docs/profile.png) |

</div>

**Personal movie collections** that persist across sessions, beautifully designed with responsive grid layouts. The **User Profile** page provides a full activity dashboard — ratings, reviews, favorites, and watchlist all in one tabbed view.

## 🛠️ Technical Highlights

### Architecture & Design Patterns

```mermaid
flowchart TB
    subgraph Client["🌐 Browser"]
        UI["Bootstrap 5 + Jinja2\nChart.js · D3.js · Vanilla JS"]
    end

    subgraph GH["⚙️ GitHub"]
        direction LR
        CI["Actions: CI\nTests · Lint · Security\n(3 Python versions)"]
    end

    subgraph Unraid["🖥️ Unraid (Production)"]
        direction TB
        CF["Cloudflare Tunnel\nTLS · Public ingress"]
        subgraph Stackd["📦 Compose stack: dashboard"]
            direction TB
            APP["dashboard-app\nFlask · gunicorn · 1 process, 8 threads\nSimpleCache · in-memory limiter"]
            PG[("dashboard-db\nPostgreSQL · 5,000+ movies")]
            APP -- SQLAlchemy ORM --> PG
        end
        SYNC["User Script: Sync-TMDB-Dashboard\nSundays 3am"]
        CF --> APP
        SYNC -- sync_tmdb_data.py --> PG
    end

    subgraph Local["💻 Local Dev"]
        direction TB
        FLASK["Flask dev server"]
        SQLITE[("SQLite\n8,000+ movies")]
        FLASK -- SQLAlchemy ORM --> SQLITE
    end

    subgraph External["🔌 External APIs"]
        TMDB["TMDB API\nMovies · Cast · Trailers\nWatch Providers"]
    end

    UI -- HTTPS --> CF
    UI -- HTTP --> FLASK
    APP -- get_movie_videos\nget_watch_providers --> TMDB
    FLASK -- sync_tmdb_data.py --> TMDB
    SYNC -- TMDB API --> TMDB

    subgraph Stack["🛠️ Key Libraries"]
        direction LR
        S1["SQLAlchemy 2.0\nAlembic"]
        S2["Flask-Caching\nFlask-Limiter\nWerkzeug"]
        S3["pytest\npre-commit\nDocker"]
    end
```

### Code Layout

| Path | Holds |
|---|---|
| `src/app.py` | App setup, request hooks, error pages, CLI |
| `src/extensions.py` | Cache, CSRF, rate limiter |
| `src/helpers.py` | Shared query and request helpers |
| `src/featured.py` | Movie of the Day, recommendations |
| `src/routes/` | One blueprint per area (below) |
| `src/models.py` | SQLAlchemy models |
| `src/tmdb_api.py` | TMDB client |

Blueprints in `src/routes/`: `main` (home, movies, search, decades, studios), `people` (actors, directors), `account` (saved lists, ratings, reviews, profile, activity), `collections`, `analytics`, `auth`, `api` (`/api/v1`) and `admin`. Endpoint names include the blueprint: `url_for('main.movie_detail', movie_id=550)`.

### RESTful API

**Available Endpoints**

```bash
# Movies
GET  /api/v1/movies              # List movies (pagination, filtering, sorting)
GET  /api/v1/movies/<id>         # Movie details with cast/crew
GET  /api/v1/movies/search       # Search movies by title

# Analytics
GET  /api/v1/analytics/overview  # Total movies, avg rating, revenue
GET  /api/v1/analytics/genres    # Genre statistics
GET  /api/v1/analytics/top-movies # Top by rating/revenue/popularity

# Actors
GET  /api/v1/actors              # List actors with pagination
GET  /api/v1/actors/<id>         # Actor details with filmography
GET  /api/v1/actors/search       # Search actors by name (autocomplete)

# System
GET  /api/v1/genres              # All genres
GET  /api/v1/health              # Health check
GET  /api/v1/docs                # API documentation
GET  /api/v1/collections         # User's collections (authenticated)
```

**Example Usage**

```bash
# Get top rated movies
curl http://localhost:5000/api/v1/movies?sort=rating&per_page=10

# Search movies
curl http://localhost:5000/api/v1/movies/search?q=inception

# Get analytics
curl http://localhost:5000/api/v1/analytics/overview
```

### Advanced SQL Showcase

This project demonstrates **professional-grade SQL** including:

**Complex Joins & Aggregations**

```sql
-- Top actors with statistics
SELECT p.name, COUNT(c.movie_id) as movies, AVG(m.vote_average) as avg_rating
FROM people p
JOIN cast c ON p.id = c.person_id
JOIN movies m ON c.movie_id = m.id
WHERE m.vote_count > 20
GROUP BY p.id HAVING COUNT(c.movie_id) >= 2
ORDER BY movies DESC;
```

**Subqueries & Window Functions**

```sql
-- Similar movies using genre matching
SELECT m.*, COUNT(mg.genre_id) as genre_matches
FROM movies m
JOIN movie_genres mg ON m.id = mg.movie_id
WHERE mg.genre_id IN (SELECT genre_id FROM movie_genres WHERE movie_id = ?)
GROUP BY m.id
ORDER BY genre_matches DESC, m.vote_average DESC;
```

**Custom Algorithms**

```sql
-- Hidden gems formula: high rating, low popularity
SELECT * FROM movies
WHERE vote_average >= 7.0 AND popularity <= 20.0 AND vote_count >= 50
ORDER BY (vote_average / LOG(popularity + 2)) DESC;
```

### Tech Stack

**Backend**

- Python 3.13+ with Flask
- SQLAlchemy ORM
- Flask-Caching (SimpleCache by default; RedisCache when `REDIS_URL` is set)
- Flask-Limiter (login/register limits per IP and per username; API limits)
- Security headers (CSP, frame denial, HSTS on HTTPS) and revocable sessions
- Flask-WTF (CSRF protection)
- Structured JSON logging with daily rotation (logs/app.log)
- Werkzeug password hashing
- pytest for testing

**Frontend**

- Bootstrap 5 (responsive design)
- Chart.js (data visualization)
- D3.js (actor collaboration network force graph)
- Vanilla JavaScript (DOM manipulation, infinite scroll, toast notifications)
- Jinja2 templating
- Native lazy loading (`loading="lazy"`)

**Database**

- SQLite (development)
- PostgreSQL (production, self-hosted on Unraid)
- Normalized schema with 18 tables
- Many-to-many relationships
- Compound indexes
- Alembic migrations

**DevOps**

- Docker (multi-stage Dockerfile with HEALTHCHECK; dev-only docker-compose)
- Self-hosted on Unraid: `dashboard` Compose stack (`dashboard-app` + `dashboard-db`)
- Cloudflare Tunnel for public ingress (no ports forwarded)
- No Redis: one Gunicorn process with 8 threads shares the SimpleCache and in-memory rate limiter (set `REDIS_URL` to use Redis instead)
- Weekly TMDB sync via Unraid User Script (`Sync-TMDB-Dashboard`, Sundays 3am)
- Structured JSON logging
- GitHub Actions CI (tests on 3 Python versions plus a Postgres 16 job, lint, Bandit); the Docker Hub image is pushed only after tests pass
- Pinned dependencies (`requirements.in` -> `requirements.txt` via pip-tools; dev tools in `requirements-dev.txt`)
- Environment-based config

## 📊 Project Stats

- **8,000+** movies with complete metadata (local) | **10,000+** on the live instance
- **300+** directors with filmographies
- **1,000+** actors with profiles
- **95%** test coverage with 609 tests passing (measured 2026-11-02; the suite also runs against Postgres 16 in CI)
- **18** database tables with optimized indexes
- **74** Flask routes (34 page · 27 action · 13 API)
- **13** RESTful API endpoints
- **38** Jinja2 templates

## 🎓 Skills Demonstrated

### Full-Stack Development

✅ Flask web framework & routing
✅ SQLAlchemy ORM with complex queries
✅ RESTful API design & implementation
✅ Session management & authentication
✅ Template inheritance & Jinja2
✅ Responsive UI with Bootstrap
✅ Mobile-first design principles

### Database & SQL

✅ Schema design & normalization
✅ Complex JOINs & subqueries
✅ Aggregations & window functions
✅ Query optimization & indexing
✅ Many-to-many relationships
✅ Data modeling best practices

### Python & Best Practices

✅ Object-oriented programming
✅ API integration (TMDB)
✅ Error handling & logging
✅ Virtual environments
✅ Automated testing (unittest/pytest)
✅ Environment-aware configuration & fail-fast production validation

### DevOps & Tools

✅ Git version control
✅ Docker containerization
✅ Environment configuration
✅ Automated data pipelines
✅ CI/CD with GitHub Actions
✅ Structured logging
✅ Comprehensive documentation
✅ Self-hosted production deployment (Unraid + Docker Compose)
✅ PostgreSQL in production
✅ Database migrations (Alembic)
✅ Cloudflare Tunnel ingress
✅ D3.js interactive data visualization
✅ Scheduled data-sync automation

## 📚 Detailed Documentation

<details>
<summary><b>📖 Full Installation Guide</b></summary>

### Prerequisites

- Python 3.13+
- pip package manager
- Git
- TMDB API key ([get free key](https://www.themoviedb.org/settings/api))

### Step-by-Step Setup

1. **Clone repository**

   ```bash
   git clone https://github.com/jaime-builds/movie-analytics-dashboard.git
   cd movie-analytics-dashboard
   ```

2. **Create virtual environment**

   ```bash
   python -m venv venv

   # Windows
   .\venv\Scripts\activate

   # macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt -r requirements-dev.txt
   ```

   `requirements.txt` is fully pinned. To change a dependency, edit
   `requirements.in` (or `requirements-dev.in`) and regenerate with
   `pip-compile --strip-extras requirements.in`.

4. **Configure environment**

   Create `config/.env`:

   ```env
   TMDB_API_KEY=your_api_key_here
   DATABASE_URL=sqlite:///movies.db
   SECRET_KEY=your_secret_key_here
   ```

5. **Initialize database**

   ```bash
   alembic upgrade head
   ```

   Alembic is the supported schema initialization path for local and deployed
   databases. `python -m src.models` no longer creates tables.

6. **Import movie data**

   ```bash
   # Quick start (1,000 movies, ~5 minutes)
   python scripts/sync_tmdb_data.py --limit 1000

   # Full dataset (5,000 movies, ~30 minutes)
   python scripts/sync_tmdb_data.py --limit 5000
   ```

7. **Run application**

   ```bash
   python -m src.app
   ```

   Visit: <http://127.0.0.1:5000>

8. **Make an admin account** (optional)

   Register in the browser, then run `flask --app src.app set-admin <username>`.
   Admins get `/admin` (analytics, user bans, moderation, registration
   on/off) and a "Hide from home page" control on each movie page.

</details>

<details>
<summary><b>🗂️ Database Schema</b></summary>

### Tables

**Core Tables**

- `movies` - 10,000+ films with metadata, ratings, financial data
- `genres` - 19 movie genres
- `people` - Actors, directors, crew (with profile images)
- `production_companies` - Studios and production companies

**Relationships**

- `movie_genres` - Many-to-many (movies ↔ genres)
- `movie_companies` - Many-to-many (movies ↔ companies)
- `cast` - Movie cast with character names
- `crew` - Movie crew with job titles

**User System**

- `users` - Authentication with hashed passwords
- `user_favorites` - Many-to-many (users ↔ favorite movies)
- `user_watchlist` - Many-to-many (users ↔ watchlist movies)
- `ratings` - User ratings (1-5 stars) for movies
- `reviews` - User text reviews for movies
- `collections` - User-created named movie lists
- `collection_movies` - Many-to-many (collections ↔ movies, with `added_at`)

**Featured Content**

- `movie_of_the_day` - Daily featured pick with 30-day anti-repeat history

**Admin Dashboard**

- `page_views` - Per-path daily view counters for site analytics
- `site_settings` - Key/value store for site-wide toggles (e.g. registration on/off)
- `users.is_admin` / `is_banned` / `banned_at` - Admin access and ban state
- `users.session_version` - Bumped on logout and ban so older session cookies stop working
- `users.hide_activity` - Opt out of the public activity feed
- `movies.is_mature` / `hide_from_featured` - Keyword-based mature flag and an admin's "keep off the home page"
- `ratings.is_deleted` / `deleted_at`, `reviews.is_deleted` / `deleted_at` - Soft-delete moderation flags

### ER Diagram

```text
users ─┬─< user_favorites >─┬─ movies ─┬─< movie_genres >─┬─ genres
       │                     │          │                   │
       ├─< user_watchlist >──┤          ├─< movie_companies >─ production_companies
       │                     │          │
       ├─< ratings >─────────┤          ├─< cast >──── people
       │                     │          │
       └─< reviews >─────────┘          └─< crew >──── people
```

</details>

<details>
<summary><b>🧪 Testing</b></summary>

### Run Tests

```bash
# Run with pytest
pytest

# With coverage
pytest --cov=src --cov-report=html

# Specific test file
pytest tests/test_auth.py -v
```

### Test Coverage

- ✅ User authentication (registration, login, logout)
- ✅ Password validation
- ✅ Favorites add/remove
- ✅ Watchlist add/remove
- ✅ Ratings submit/update
- ✅ Reviews create/delete
- ✅ Session management
- ✅ Database relationships
- ✅ Security (password hashing)

**Current Coverage**: 95% (609 tests passing, measured 2026-11-02)

The suite is offline: `tests/conftest.py` stubs TMDB and fails any real HTTP
request, so no API key is needed. To run it against Postgres, point
`TEST_DATABASE_URL` at an empty database whose name contains `test`:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost/dashboard_test pytest
```

After a deploy, `python scripts/smoke_test.py https://movie-dashboard.jaime.build`
checks the live API and home page and exits 1 on any failure.

</details>

<details>
<summary><b>🔄 Data Synchronization</b></summary>

### Manual Sync

```bash
# Sync 5000 movies
python scripts/sync_tmdb_data.py --limit 5000

# Update existing movies
python scripts/sync_tmdb_data.py --limit 5000 --update-existing

# Tune parallel workers for local syncs
python scripts/sync_tmdb_data.py --limit 1000 --workers 20

# Exit 1 on any failed movie (default tolerates up to 5%)
python scripts/sync_tmdb_data.py --limit 5000 --strict

# Classify movies already in the database as mature or not (run once after migration 009)
python scripts/backfill_mature_flags.py --dry-run
python scripts/backfill_mature_flags.py
```

The sync makes one TMDB call per movie (details, credits and keywords together),
retries HTTP 429 with backoff, writes each movie in its own savepoint so one bad
movie never discards others, and refreshes vote counts and popularity for movies
it already has. Exit codes: 0 done, 1 failed (see the summary's `Errors:` line),
2 another sync holds the lock, 130 interrupted.

### Automated Sync

Automated TMDB sync runs on the Unraid host as a User Script (`Sync-TMDB-Dashboard`):

- **Weekly sync** every Sunday at 3:00 AM local time
- Runs against the `dashboard-db` Postgres container on the LAN

`.github/workflows/sync_tmdb.yml` is manual-only: GitHub's cloud runners can't
reach a LAN-only database, so it needs a `SYNC_DATABASE_URL` secret pointing at
some other, reachable database.

For local or ad hoc updates, run `python scripts/sync_tmdb_data.py` manually.

### What Gets Synced

- ✅ Movie metadata (title, overview, release date)
- ✅ Ratings and popularity (refreshed weekly for movies already stored)
- ✅ Keywords, used only to flag mature movies (`movies.is_mature`)
- ✅ Cast and crew (top 10 actors)
- ✅ Director information
- ✅ Production companies
- ✅ Genres
- ✅ Poster and backdrop images
- ✅ Actor profile photos

</details>

<details>
<summary><b>🎨 Features Deep Dive</b></summary>

### Ratings & Reviews System

- **Star Ratings**: 1-5 stars per movie
- **Text Reviews**: Write detailed reviews (minimum 10 characters)
- **Edit/Delete**: Manage your own reviews
- **Average Ratings**: See community ratings
- **Pagination**: Browse all reviews efficiently

### Personalized Recommendations

Algorithm uses:

- User's favorite movies
- Genre preferences extraction
- Weighted genre matching
- Popularity and rating scores

```python
# Recommendation formula
matches = count_shared_genres(user_favorites, candidate_movie)
score = matches * vote_average * log(popularity)
```

### Director Spotlight

- Browse 300+ directors
- Complete filmographies with statistics
- Career timeline charts (ratings over time, box office)
- Genre distribution analysis
- Grid and list view options
- Filter by movie count

### Hidden Gems Algorithm

```python
gem_score = vote_average / (log(popularity + 2) * 2)
```

Finds high-quality, underappreciated films by balancing:

- High rating (≥7.0)
- Low popularity (≤20.0)
- Sufficient votes (≥50)

### Analytics Dashboard

- **Genre Distribution** - Pie chart
- **Release Timeline** - Bar chart by year
- **Ratings by Genre** - Horizontal bar chart
- **Budget vs Revenue Scatter** - Each movie plotted with a break-even reference line and ROI tooltips
- **Most Profitable Movies** - Horizontal bar chart of top 15 films by net profit
- **Top Studios** - Production company rankings

All charts are:

- Interactive (hover for details)
- Responsive (mobile-friendly)
- Dark mode compatible

### User Profile Page

A dedicated activity hub showing:

- **Stats row** — favorites count, watchlist count, ratings count, reviews count, and personal average rating
- **Ratings tab** — all movies rated with star display and timestamps
- **Reviews tab** — all written reviews with links back to each movie
- **Favorites tab** — full poster grid of favorited movies
- **Watchlist tab** — full poster grid of watchlisted movies

### RESTful API

13 endpoints providing:

- Movie search and filtering
- Analytics and statistics
- Actor/director information
- System health monitoring
- Complete API documentation at `/api/v1/docs`

</details>

## 🚀 Future Roadmap

See [TODO.md](TODO.md) for the complete roadmap.

### Recently Shipped

- [x] **Family-friendly mode, Box office by genre, Blind Pick, Activity Feed, Year in Review** (2026-11-02) - a navbar toggle hides movies flagged mature by their TMDB keywords; a revenue-by-genre chart on /analytics; a random pick from your watchlist; a public feed of recent ratings and reviews with a per-user opt-out; personal stats for any year
- [x] **Blueprints** (2026-11-02) - `src/app.py` split into eight Flask blueprints under `src/routes/`; URLs unchanged
- [x] **Full code review fixes** (2026-11-02) - security hardening (rate limits, headers, revocable sessions, safer confirms), Postgres-correct queries, stable pagination, caching, sync reliability, accessibility and front-end fixes (see `TODO.md`)
- [x] **Admin dashboard** - `/admin` panel: site analytics (page views, account growth), user access control (ban/unban, content hidden site-wide, registration toggle), and moderation (soft/hard-delete on ratings and reviews)
- [x] **Unraid migration prep** - Docs and config moved off Railway: architecture diagram now shows the `dashboard` Compose stack (Postgres, no Redis) behind a Cloudflare Tunnel; GitHub Actions TMDB sync disabled in favor of an Unraid User Script
- [x] **Python 3.13** - Dockerfile, CI workflows, and dependencies upgraded; test matrix trimmed to 3.11/3.12/3.13
- [x] **Movie of the Day** - Homepage feature drawn from the Hidden Gems pool, deterministic per day with a 30-day anti-repeat window
- [x] **Breadcrumb navigation** - Bootstrap 5 breadcrumb trail on every page except home, via a shared Jinja2 macro
- [x] **Collection ordering fix** - collections now track when each movie was added (added_at) and display in that order instead of by internal ID
- [x] **Redis** - Railway Redis add-on (historical: production on Unraid runs without Redis)
- [x] **Common Films** - `/common-films`; find movies shared by up to 5 actors with smart autocomplete
- [x] **Responsive image optimization** - srcset on all poster grids (w185/w342/w500); Jinja2 macro for reuse
- [x] **Advanced search** - Dedicated `/advanced-search` with genre, era, rating, runtime filters; active filter pills
- [x] **Actor collaboration network** - D3.js force graph at `/actor/<id>/network`; photo nodes, weighted edges, shared film tooltips
- [x] **Streaming availability** - Where to Watch card on movie detail; stream/rent/buy via TMDB/JustWatch
- [x] **Collection pagination** - 24 movies per page with page counter
- [x] **Weekly TMDB sync** - GitHub Actions cron job; 5,000 movies; manual trigger available
- [x] **Architecture diagram** - Mermaid flowchart in README covering full stack
- [x] **PostgreSQL registration fix** - Alembic migration 002 expands password_hash to String(256)
- [x] Error logging and monitoring (JSON structured, daily rotation)
- [x] Docker containerization (Dockerfile + docker-compose)
- [x] ~~Restored run_tests.py as pytest convenience wrapper~~ (removed 2026-11-02; run `pytest`)
- [x] Production companies (Studios) page with detail pages
- [x] Decade overview pages with defining films and charts
- [x] Movie collections (user-created named lists)
- [x] Navbar reorganized into Explore and Discover dropdowns
- [x] Search autocomplete with keyboard navigation
- [x] Query caching with Flask-Caching (1-hour TTL)
- [x] Movie comparison tool (up to 4 movies, `/compare` page)
- [x] **Railway deployment** - Historical: hosted on Railway until the 2026-07-29 move to Unraid
- [x] **PostgreSQL** - Migrated from SQLite; dual-database compatible
- [x] **Alembic migrations** - Full schema versioning with baseline migration
- [x] **CI/CD auto-deploy** - Historical (Railway); production now rebuilds from its Unraid checkout
- [x] **Test suite unified** - Main test suite runs in a single pytest pass; 418 passing

### Up Next

See [TODO.md](TODO.md) for the full roadmap.

## 📝 License

This project is open source and available under the [MIT License](LICENSE).

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!

1. Fork the project
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📬 Contact

**Jaime De La Paz**

[![GitHub](https://img.shields.io/badge/GitHub-jaime--builds-181717?style=for-the-badge&logo=github)](https://github.com/jaime-builds)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0077B5?style=for-the-badge&logo=linkedin)](https://www.linkedin.com/in/jaimedelapaz)

⭐ **Star this repo** if you found it helpful!

## 🙏 Acknowledgments

- [The Movie Database (TMDB)](https://www.themoviedb.org/) for movie data
- [Bootstrap](https://getbootstrap.com/) for UI components
- [Chart.js](https://www.chartjs.org/) for data visualization
- [UI Avatars](https://ui-avatars.com/) for generated profile images

<div align="center">

**Built with ❤️ as a portfolio project**

*Showcasing full-stack development with Python, Flask, SQL, and modern web technologies*

</div>
