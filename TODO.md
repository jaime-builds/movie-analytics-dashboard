# Movie Analytics Dashboard - Roadmap

## 🎯 Current Sprint (Next 2 Weeks)

### Improvements 🔧
- [ ] **Error logging and monitoring** (4h) - Structured logging with request tracking and error alerting
- [ ] **Docker containerization** (5h) - Dockerfile and docker-compose for consistent local and prod environments
- [ ] **restore run_tests.py** (1h) - Repurposed as db check script during debugging; restore to original test runner

### Enhancements ✨
- [ ] **Production companies page** (5h) - Browse studios with full filmographies and stats
- [ ] **Decade overview pages** (6h) - Curated landing pages per decade with top movies and trends

### Features 🎬
- [ ] **Movie collections** (5h) - User-created named lists beyond favorites/watchlist
- [ ] **Email digest** (5h) - Weekly email of new movies in user's favorite genres

## 🚀 Next Up (This Month)

- [ ] **Actor collaboration network** (6h) - Graph of actors who've appeared together, showcasing complex SQL joins
- [ ] **Image optimization** (3h) - Serve WebP format posters for faster load times
- [ ] **OAuth integration** (5h) - Google/GitHub login alongside existing username/password
- [ ] **Social features** (8h) - Follow users, see friend activity, share favorites
- [ ] **Deploy to production** (6h) - Railway or Render deployment with PostgreSQL
- [ ] **Advanced multi-filter search** (4h) - Combine genre, year, rating, runtime in a single search UI

## 🔮 Future (Next Quarter)

### Backend & Infrastructure

- [ ] Migrate SQLite → PostgreSQL
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Background job queue for imports
- [ ] Database migrations with Alembic

### User Experience

- [ ] Keyboard shortcuts
- [ ] Advanced multi-filter search
- [ ] Breadcrumb navigation
- [ ] Dark mode improvements
- [ ] Progressive Web App (PWA)
- [ ] Image optimization - WebP format (3h)
- [ ] Production companies page (5h)
- [ ] Decade overview pages (6h)
- [ ] Movie collections (5h) - User-created lists

### Social & Engagement

- [ ] Social sharing features
- [ ] User-to-user recommendations
- [ ] Movie quiz/trivia
- [ ] Streaming availability integration
- [ ] OAuth integration (Google/GitHub login)
- [ ] Email notifications (5h) - Weekly digest of new movies in favorite genres
- [ ] Social features (8h) - Follow users, see friend activity, share favorites

### Advanced Analytics

- [ ] Rating trends over time (window functions)
- [ ] Box office by genre (aggregations)
- [ ] Actor collaboration network (complex joins)
- [ ] Genre trending analysis
- [ ] User analytics dashboard

## 📚 Backlog (Ideas)

- [ ] Mobile app (React Native/Flutter)
- [ ] Deploy to production (Heroku/Railway)
- [ ] Documentation site
- [ ] Contribution guidelines
- [ ] Architecture diagram
- [ ] GraphQL API
- [ ] WebSocket support for real-time updates
- [ ] Machine learning recommendations

---

## ✅ Recently Completed (Last 30 Days)

<details>
<summary>Click to expand (31 items)</summary>

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
- **Features Completed**: 39
- **In Progress**: 0
- **Test Coverage**: 80%+ ✅
- **API Endpoints**: 12 ✅

## 🎓 Learning Goals

This project showcases:

- ✅ Flask web development
- ✅ SQLAlchemy ORM & complex queries
- ✅ TMDB API integration
- ✅ User authentication
- ✅ Database relationships (many-to-many)
- ✅ RESTful API design
- ✅ Testing (pytest/unittest)
- 📅 DevOps (Docker, CI/CD)
- 📅 Production deployment

---

**Last Updated**: March 30, 2026
