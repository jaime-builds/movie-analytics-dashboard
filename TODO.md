# Movie Analytics Dashboard - Roadmap

## 🎯 Current Sprint (Next 2 Weeks)

- [x] **Image optimization** (3h) - Responsive srcset on all poster grids (w185/w342/w500); Jinja2 macro for reuse
- [x] **Advanced multi-filter search** (4h) - Dedicated /advanced-search page; sticky sidebar with genre, decade/year, rating range, runtime range, min votes, sort; active filter pills; quick-search presets; responsive grid results
- [x] **Actor collaboration network** (6h) - D3.js force-directed graph at /actor/<id>/network; nodes are actor photos, edges weighted by shared films, hover reveals movie titles, click navigates to actor profile
- [x] **Streaming availability** (4h) - Where to Watch card on movie detail page; streams/rent/buy sections with provider logos; US region via TMDB/JustWatch; hidden when no data
- [x] **Pagination on collections** (2h) - 24 movies per page; showing X-Y of Z counter; pagination controls hidden for small collections
- [ ] **Architecture diagram** (2h) - Visual diagram of the full stack: browser, Flask, SQLAlchemy, PostgreSQL, Redis, Railway, GitHub Actions, TMDB API
- [ ] **Redis add-on** - Add Railway Redis service; swap SimpleCache for RedisCache in production
- [ ] **TMDB sync automation** - GitHub Actions cron job to keep Railway DB current

## 🚀 Next Up (This Month)

- [ ] **OAuth integration** (5h) - Google/GitHub login alongside existing username/password
- [ ] **Public collections** (3h) - Toggle to make user collections public; browseable by other users
- [ ] **Social features** (8h) - Follow users, see friend activity, share favorites
- [ ] **Movie trivia/quiz** (4h) - Interactive quiz based on the movie database; engaging demo feature
- [ ] **User activity feed** (3h) - Public feed of recent ratings and reviews across all users
- [ ] **Performance monitoring** (3h) - Sentry integration for error tracking and performance insights
- [ ] **SEO optimization** (2h) - Meta tags, og:image for social sharing, structured data
- [ ] **Year in review** (4h) - Personal stats page for movies watched, ratings given, genres explored

## 🔮 Future

- [ ] Migrate from Railway to Render + Supabase (after active dev month)
- [ ] UptimeRobot pinger for Render free tier keep-alive
- [ ] Keyboard shortcuts
- [ ] Breadcrumb navigation
- [ ] Dark mode improvements
- [ ] Progressive Web App (PWA)
- [ ] Social sharing features
- [ ] User-to-user recommendations
- [ ] Email digest - Weekly email of new movies in favorite genres
- [ ] Rating trends over time (window functions)
- [ ] Box office by genre (aggregations)
- [ ] Genre trending analysis
- [ ] User analytics dashboard
- [ ] Machine learning recommendations
- [ ] Documentation site
- [ ] Mobile app (React Native/Flutter)
- [ ] Achievement badges - Gamified milestones for user activity
- [ ] Shareable movie lists - Public URL for collections
- [ ] Movie of the day - Featured movie on the homepage
- [ ] Export profile data - Download ratings, reviews, collections as JSON or CSV
- [ ] "Not interested" dismissal on recommendations
- [ ] Runtime and content filters - Family-friendly toggle, language filter
- [ ] Watchlist streaming alert
- [ ] "Seen it" quick-log
- [ ] API key management page
- [ ] Admin dashboard
- [ ] Full-text search with SQLite FTS5 / PostgreSQL full-text
- [ ] Redis caching for multi-worker production
- [ ] Blind pick - Random movie from your watchlist
- [ ] Movie mood matcher
- [ ] Friends' ratings overlay

---

## ✅ Recently Completed (Last 30 Days)

<details>
<summary>Click to expand (51 items)</summary>

- [✅] **Test suite unified** - Refactored test_favorites_ratings.py from unittest to standard pytest; removed --ignore from pytest.ini; CI workflow simplified to single pytest run (Apr 24)
- [✅] **Alembic migrations** - Added alembic==1.13.1; alembic.ini + migrations/env.py wired to project Config and Base; 001_initial_schema baseline captures full 15-table schema (Apr 24)
- [✅] **Railway deployment** - App live at https://movie-analytics-dashboard-production.up.railway.app with PostgreSQL; Docker multi-stage build; gunicorn on dynamic $PORT (Apr 24)
- [✅] **PostgreSQL migration** - Replaced all SQLite-specific func.strftime() with extract() for dual SQLite/PostgreSQL compatibility; config.py auto-fixes Railway's postgresql:// scheme to postgresql+psycopg2:// (Apr 24)
- [✅] **CI/CD auto-deploy** - Railway watches main branch; every push triggers build and deploy automatically (Apr 24)
- [✅] **Redis + rate limiter config** - Cache uses RedisCache when REDIS_URL set, SimpleCache otherwise; rate limiter uses Redis storage in production; ProxyFix middleware for correct client IPs behind Railway proxy (Apr 24)
- [✅] **load_dotenv fix** - Changed override=True to override=False so externally set env vars (Railway, CI, PowerShell) take precedence over .env file (Apr 24)
- [✅] **Navbar reorganization** - Explore and Discover dropdowns with hover open; reduced from 9 top-level items to 5 (Apr 21)
- [✅] **Movie collections** - User-created named lists with poster strip preview; add-to-collection dropdown on movie detail page; collection_movies table (Apr 21)
- [✅] **Decade overview pages** - Index card page with backdrop images + detail pages per decade with defining films, top rated, most popular, genre breakdown, and year charts (Apr 21)
- [✅] **Production companies page** - Studios listing with logo, stats, top films, and full filmography detail pages; sync script updated to backfill company data (Apr 21)
- [✅] **Error logging and monitoring** - JSON structured logging to logs/app.log with daily rotation; request lifecycle logging; WARNING on failed logins/4xx; ERROR on unhandled exceptions (Apr 21)
- [✅] **Docker containerization** - Dockerfile pinned to Python 3.11; docker-compose.yml with DB and log volume mounts and health check; .dockerignore for lean builds (Apr 21)
- [✅] **Restore run_tests.py** - Pytest convenience wrapper with --no-cov support; defers to pytest.ini for coverage config (Apr 21)
- [✅] **Home page redesign** - Two-column hero with live stats bar, jaime-builds branding, feature shortcut cards, and section headers with See All links (Mar 30)
- [✅] **Test isolation fix** - db_session fixture now uses in-memory SQLite; production DB safe from pytest runs (Mar 30)
- [✅] **Database path fix** - config.py loads .env via absolute path; DATABASE_URL resolves correctly regardless of launch directory (Mar 30)
- [✅] **API rate limiting** - Flask-Limiter on all API endpoints; per-route limits; health + movies list exempt (Mar 30)
- [✅] **Analytics CSV export** - Genre stats, top movies by rating/revenue, yearly trends; Export button on analytics page (Mar 30)
- [✅] **Loading animations** - Skeleton cards on infinite scroll; button spinners for favorite, watchlist, and rating actions (Mar 30)
- [✅] **Test coverage expansion** - TestCompareRoute, TestAdvancedFilters, TestCaching, TestAnalyticsExport; smoke_test.py moved to scripts/ (Mar 30)
- [✅] **Search autocomplete** - Live navbar dropdown with poster thumbnails, keyboard nav, and debounced `/api/v1/movies/search` calls (Mar 2)
- [✅] **Query caching** - Flask-Caching SimpleCache on analytics, genre, and top-movies routes; 1-hour TTL cuts repeat DB load (Mar 2)
- [✅] **Advanced filtering UI** - Collapsible filter panel with Min Vote Count and Status filters; honored by infinite scroll and URL state (Mar 2)
- [✅] **Movie comparison tool** - Select up to 4 movies via floating compare bar; side-by-side table with poster, stats, ROI, and Chart.js visuals on `/compare` (Mar 2)
- [✅] **Budget vs revenue analytics** - Scatter plot with break-even line and per-movie tooltips; Most Profitable Movies horizontal bar chart on analytics page (Mar 2)
- [✅] **Movie poster lazy loading** - Added `loading="lazy"` across all templates for faster page loads (Feb 24)
- [✅] **Infinite scroll** - Replaced pagination on /movies with IntersectionObserver-based infinite scroll (Feb 24)
- [✅] **Database indexing optimization** - Added indexes on vote_count, title, crew.person_id, movie_genres.genre_id, ratings.movie_id (Feb 24)
- [✅] **Homepage live movie count** - Fixed hardcoded "100 movies" to show real database count (Feb 24)
- [✅] **Toast notifications** - Replaced flash alerts with polished auto-dismissing toasts (Feb 24)
- [✅] **User profile pages** - Stats, ratings, reviews, favorites and watchlist in tabbed interface (Feb 24)
- [✅] **Comprehensive test suite expansion** - API route tests, new route tests, profile page tests (Feb 24)
- [✅] **Unit tests** - Test coverage for authentication, favorites, ratings, reviews (Feb 11)
- [✅] **Mobile responsive improvements** - Fixed layout issues on phone screens (Feb 11)
- [✅] **RESTful API endpoints** - JSON API for movies, analytics, actors, genres (Feb 11)
- [✅] Movie ratings and reviews system (Feb 11)
- [✅] Recommendations engine (Feb 11)
- [✅] Cast/crew detail pages (Feb 9)
- [✅] Director Spotlight with filmographies (Feb 9)
- [✅] Auto-refresh TMDB sync scheduler (Feb 9)
- [✅] User authentication & login (Feb 9)
- [✅] Favorites/watchlist system (Feb 9)
- [✅] Increased dataset to 5000 movies (Feb 9)
- [✅] Top Actors page
- [✅] Hidden Gems page
- [✅] Advanced filtering (year, decade, rating, runtime)
- [✅] Analytics Chart.js visualizations
- [✅] Dark mode toggle
- [✅] Movie trailer embeds
- [✅] Backdrop image banners
- [✅] Similar movies recommendations

</details>

---

## 📊 Project Stats

- **Total Movies**: 1,000 (Railway/PostgreSQL) | 8,000+ (local SQLite)
- **Features Completed**: 51
- **In Progress**: 0
- **Test Coverage**: 87% ✅
- **Tests Passing**: 339 ✅
- **API Endpoints**: 13 ✅
- **Live URL**: https://movie-analytics-dashboard-production.up.railway.app

## 🎓 Learning Goals

This project showcases:

- ✅ Flask web development
- ✅ SQLAlchemy ORM & complex queries
- ✅ TMDB API integration
- ✅ User authentication
- ✅ Database relationships (many-to-many)
- ✅ RESTful API design
- ✅ Testing (pytest/unittest)
- ✅ DevOps (Docker)
- ✅ Production deployment (Railway + PostgreSQL)
- ✅ Database migrations (Alembic)
- ✅ CI/CD pipeline (GitHub Actions)

---

**Last Updated**: April 24, 2026
