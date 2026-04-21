# Movie Analytics Dashboard - Roadmap

## 🎯 Current Sprint (Next 2 Weeks)

### Main Goal 🚀
- [ ] **Deploy to production** (6h) - Railway deployment with PostgreSQL, custom domain `movies.jaime.build` via Cloudflare

### Pre-launch Polish ✨
- [ ] **Image optimization** (3h) - Serve WebP format posters for faster load times
- [ ] **Advanced multi-filter search** (4h) - Combine genre, year, rating, runtime in a single unified search UI

### Included in Deploy Work 🔧
- [ ] **SQLite → PostgreSQL migration** - Required for Railway; schema ports cleanly
- [ ] **CI/CD auto-deploy** - Wire GitHub Actions to deploy on push to main
- [ ] **Railway cron job** - Daily TMDB sync to keep movie data current

## 🚀 Next Up (This Month)

- [ ] **Actor collaboration network** (6h) - Graph of actors who've appeared together, showcasing complex SQL joins
- [ ] **OAuth integration** (5h) - Google/GitHub login alongside existing username/password
- [ ] **Public collections** (3h) - Toggle to make user collections public; browseable by other users
- [ ] **Social features** (8h) - Follow users, see friend activity, share favorites
- [ ] **Movie trivia/quiz** (4h) - Interactive quiz based on the movie database; engaging demo feature
- [ ] **Streaming availability** (4h) - Show where to watch each movie (Netflix, Hulu, etc.) via TMDB watch providers API
- [ ] **User activity feed** (3h) - Public feed of recent ratings and reviews across all users

## 🔮 Future (Next Quarter)

### Backend & Infrastructure

- [ ] Alembic database migrations
- [ ] Full CI/CD pipeline improvements
- [ ] Performance monitoring (Sentry or similar)
- [ ] Architecture diagram

### User Experience

- [ ] Keyboard shortcuts
- [ ] Breadcrumb navigation
- [ ] Dark mode improvements
- [ ] Progressive Web App (PWA)
- [ ] SEO optimization - meta tags, og:image for social sharing
- [ ] Pagination on collections

### Social & Engagement

- [ ] Social sharing features
- [ ] User-to-user recommendations
- [ ] Email digest - Weekly email of new movies in favorite genres (requires deployment)

### Advanced Analytics

- [ ] Rating trends over time (window functions)
- [ ] Box office by genre (aggregations)
- [ ] Genre trending analysis
- [ ] User analytics dashboard
- [ ] Machine learning recommendations

### Documentation

- [ ] Documentation site

## 📚 Backlog (Ideas)

- [ ] Mobile app (React Native/Flutter)

### Portfolio Enhancements
- [ ] Achievement badges - Gamified milestones for user activity (rate 10 movies, find 5 hidden gems, etc.)
- [ ] Shareable movie lists - Public URL for collections
- [ ] Movie of the day - Featured movie on the homepage
- [ ] Export profile data - Download ratings, reviews, collections as JSON or CSV

### User Experience
- [ ] "Not interested" dismissal on recommendations to improve suggestions over time
- [ ] Runtime and content filters - Family-friendly toggle, language filter
- [ ] Watchlist streaming alert - Notify when a watchlist movie becomes available to stream
- [ ] "Seen it" quick-log - Mark as watched without requiring a rating or review

### Technical
- [ ] API key management page - For opening the API publicly
- [ ] Admin dashboard - Monitor user activity and DB health
- [ ] Full-text search with SQLite FTS5 - Faster than ILIKE queries
- [ ] Redis caching - Replace SimpleCache for multi-worker production environments

### Fun & Engagement
- [ ] Blind pick - Random movie from your watchlist
- [ ] Year in review - Personal stats for movies watched that year
- [ ] Movie mood matcher - Pick a mood, get suggestions
- [ ] Friends' ratings overlay - See what friends rated on movie detail pages

---

## ✅ Recently Completed (Last 30 Days)

<details>
<summary>Click to expand (37 items)</summary>

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
- [✅] Pagination controls
- [✅] Search with results
- [✅] Movie detail pages with cast/crew
- [✅] Genre filtering

</details>

---

## 📊 Project Stats

- **Total Movies**: 8,000+
- **Features Completed**: 46
- **In Progress**: 0
- **Test Coverage**: 87% ✅
- **API Endpoints**: 13 ✅

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
- 📅 Production deployment (current sprint)

---

**Last Updated**: April 21, 2026
