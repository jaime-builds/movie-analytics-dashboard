# Movie Analytics Dashboard - Roadmap

## 🎯 Current Sprint (Next 2 Weeks)

- [ ] **SEO optimization** (2h) - Meta tags, og:image for social sharing, structured data markup
- [ ] **Performance monitoring** (3h) - Sentry integration for error tracking and performance insights
- [ ] **Year in review** (4h) - Personal stats page for movies watched, ratings given, genres explored
- [ ] **User activity feed** (3h) - Public feed of recent ratings and reviews across all users
- [ ] **Public collections** (3h) - Toggle to make user collections public; browseable by other users
- [ ] **Movie of the day** (1h) - Featured movie on the homepage, refreshes daily
- [ ] **Box office by genre** (2h) - Aggregation chart on analytics page showing total revenue per genre
- [ ] **Breadcrumb navigation** (1h) - Breadcrumbs on detail pages (movie, actor, director, studio, decade, collection)

## 🚀 Next Up (This Month)

- [ ] **OAuth integration** (5h) - Google/GitHub login alongside existing username/password
- [ ] **User analytics dashboard** (4h) - Personal stats with charts: ratings over time, favorite genres, watch patterns
- [ ] **Movie mood matcher** (4h) - Filter recommendations by mood/vibe (funny, tense, feel-good, etc.)
- [ ] **Dark mode improvements** - Audit and polish dark mode across all templates
- [ ] **Social features** (8h) - Follow users, see friend activity, share favorites
- [ ] **Movie trivia/quiz** (4h) - Interactive quiz based on the movie database; engaging demo feature
- [ ] **Public collections** (3h) - Toggle to make user collections public; browseable by other users

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
- [ ] Blind pick - Random movie from your watchlist
- [ ] Movie mood matcher
- [ ] Friends' ratings overlay

---

## ✅ Recently Completed (April 25, 2026)

- [x] **Redis add-on** - Railway Redis provisioned; redis>=5.0.0 added to requirements.txt; app auto-switches to RedisCache + Redis rate limiter storage when REDIS_URL is set
- [x] **Common Films page** - /common-films; actor search with smart autocomplete (filters to actors who share films with already-selected actors); up to 5 actors; movie grid narrows on each addition; added to Discover dropdown
- [x] **Image optimization** (3h) - Responsive srcset on all poster grids (w185/w342/w500); Jinja2 macro for reuse
- [x] **Advanced multi-filter search** (4h) - Dedicated /advanced-search page; sticky sidebar with genre, decade/year, rating range, runtime range, min votes, sort; active filter pills; quick-search presets; responsive grid results
- [x] **Actor collaboration network** (6h) - D3.js force-directed graph at /actor/<id>/network; nodes are actor photos, edges weighted by shared films, hover reveals movie titles, click navigates to actor profile
- [x] **Streaming availability** (4h) - Where to Watch card on movie detail page; streams/rent/buy sections with provider logos; US region via TMDB/JustWatch; hidden when no data
- [x] **Pagination on collections** (2h) - 24 movies per page; showing X-Y of Z counter; pagination controls hidden for small collections
- [x] **Architecture diagram** (2h) - Mermaid flowchart in README covering browser, Flask, SQLAlchemy, PostgreSQL, Redis, Railway, GitHub Actions, TMDB API
- [x] **TMDB sync automation** - GitHub Actions cron job; runs every Sunday 2am UTC; 5,000 movies; manual trigger with configurable limit
- [x] **PostgreSQL registration fix** - Alembic migration 002 expands password_hash to String(256); fixes 500 on user registration in production

<details>
<summary>Earlier completions (click to expand)</summary>

- [x] **Test suite unified** - Refactored test_favorites_ratings.py from unittest to standard pytest; removed --ignore from pytest.ini; CI workflow simplified to single pytest run (Apr 24)
- [x] **Alembic migrations** - Added alembic==1.13.1; alembic.ini + migrations/env.py wired to project Config and Base; 001_initial_schema baseline captures full 15-table schema (Apr 24)
- [x] **Railway deployment** - App live at https://movie-analytics-dashboard-production.up.railway.app with PostgreSQL; Docker multi-stage build; gunicorn on dynamic $PORT (Apr 24)
- [x] **PostgreSQL migration** - Replaced all SQLite-specific func.strftime() with extract() for dual SQLite/PostgreSQL compatibility; config.py auto-fixes Railway's postgresql:// scheme to postgresql+psycopg2:// (Apr 24)
- [x] **CI/CD auto-deploy** - Railway watches main branch; every push triggers build and deploy automatically (Apr 24)
- [x] **Redis + rate limiter config** - Cache uses RedisCache when REDIS_URL set, SimpleCache otherwise; rate limiter uses Redis storage in production; ProxyFix middleware for correct client IPs behind Railway proxy (Apr 24)
- [x] **load_dotenv fix** - Changed override=True to override=False so externally set env vars take precedence over .env file (Apr 24)
- [x] **Navbar reorganization** - Explore and Discover dropdowns with hover open; reduced from 9 top-level items to 5 (Apr 21)
- [x] **Movie collections** - User-created named lists with poster strip preview; add-to-collection dropdown on movie detail page (Apr 21)
- [x] **Decade overview pages** - Index card page with backdrop images + detail pages per decade with defining films, top rated, most popular, genre breakdown, and year charts (Apr 21)
- [x] **Production companies page** - Studios listing with logo, stats, top films, and full filmography detail pages (Apr 21)
- [x] **Error logging and monitoring** - JSON structured logging to logs/app.log with daily rotation (Apr 21)
- [x] **Docker containerization** - Dockerfile pinned to Python 3.11; docker-compose.yml with DB and log volume mounts and health check (Apr 21)
- [x] **Home page redesign** - Two-column hero with live stats bar, jaime-builds branding, feature shortcut cards (Mar 30)
- [x] **Search autocomplete** - Live navbar dropdown with poster thumbnails, keyboard nav, debounced API calls (Mar 2)
- [x] **Query caching** - Flask-Caching on analytics, genre, and top-movies routes; 1-hour TTL (Mar 2)
- [x] **Movie comparison tool** - Up to 4 movies, floating compare bar, side-by-side table with Chart.js visuals at /compare (Mar 2)
- [x] **Infinite scroll** - Replaced pagination on /movies with IntersectionObserver (Feb 24)
- [x] **Toast notifications** - Replaced flash alerts with auto-dismissing toasts (Feb 24)
- [x] **User profile pages** - Stats row, tabbed interface for ratings, reviews, favorites, watchlist (Feb 24)
- [x] **RESTful API endpoints** - JSON API for movies, analytics, actors, genres (Feb 11)
- [x] Movie ratings and reviews system (Feb 11)
- [x] Recommendations engine (Feb 11)
- [x] Director Spotlight with filmographies (Feb 9)
- [x] User authentication & login (Feb 9)
- [x] Favorites/watchlist system (Feb 9)
- [x] Top Actors page
- [x] Hidden Gems page
- [x] Advanced filtering (year, decade, rating, runtime)
- [x] Analytics Chart.js visualizations
- [x] Dark mode toggle
- [x] Movie trailer embeds
- [x] Similar movies recommendations

</details>

---

## 📊 Project Stats

- **Total Movies**: 5,000+ (Railway/PostgreSQL) | 8,000+ (local SQLite)
- **Features Completed**: 62
- **Test Coverage**: 87% ✅
- **Tests Passing**: 339 ✅
- **API Endpoints**: 14 ✅
- **Jinja2 Templates**: 29 ✅
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
- ✅ Redis caching + rate limiting in production
- ✅ D3.js data visualization
- ✅ GitHub Actions automation (cron jobs)

---

**Last Updated**: April 25, 2026
