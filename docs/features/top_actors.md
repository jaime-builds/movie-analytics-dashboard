# Top Actors Feature

## Overview
This feature adds a "Top Actors" page that showcases the most frequently appearing actors in your movie database, along with detailed actor profile pages showing their complete filmography.

## What's New

### 1. Top Actors Page (`/top-actors`)
- **Grid display** of actors with profile images
- **Movie count** for each actor
- **Average rating** across their films
- **Sorting options**: Most Movies, Highest Rated, Most Popular, Name (A-Z)
- **Pagination** (24 actors per page)
- **Clickable cards** leading to actor detail pages

### 2. Actor Detail Page (`/actor/<actor_id>`)
- **Profile information**: Photo, birth date, birthplace
- **Biography** from TMDB
- **Career statistics**: Total movies, average rating, popularity
- **Top genres** the actor appears in
- **Complete filmography** with character names
- **Movie posters** linking to movie detail pages

## Files Added/Modified

### Backend (app.py)
Two new routes added:

1. **`@app.route("/top-actors")`**
   - Queries actors with 2+ movies
   - Calculates movie count and average rating per actor
   - Supports sorting and pagination
   - Only counts movies with 20+ votes for quality

2. **`@app.route("/actor/<int:actor_id>")`**
   - Shows actor profile and biography
   - Lists complete filmography with character names
   - Calculates career statistics
   - Shows top 5 genres for the actor

### Frontend Templates

1. **`templates/top_actors.html`** (NEW)
   - Actor grid layout (6 columns on desktop, responsive)
   - Profile images with fallback icons
   - Movie count badges
   - Average rating display
   - Sort dropdown and pagination

2. **`templates/actor_detail.html`** (NEW)
   - Two-column layout (profile + filmography)
   - Actor profile card with stats
   - Biography section (scrollable if long)
   - Movie grid showing filmography
   - Character names displayed on movie cards

## SQL Query Highlights

### Top Actors Query
```python
actor_stats = (
    session.query(
        Person.id,
        Person.name,
        Person.profile_path,
        Person.popularity,
        func.count(Cast.movie_id).label("movie_count"),
        func.avg(Movie.vote_average).label("avg_rating"),
        func.max(Movie.release_date).label("latest_movie_date")
    )
    .join(Cast, Person.id == Cast.person_id)
    .join(Movie, Cast.movie_id == Movie.id)
    .filter(Movie.vote_count > 20)  # Quality threshold
    .group_by(Person.id, Person.name, Person.profile_path, Person.popularity)
    .having(func.count(Cast.movie_id) >= 2)  # At least 2 movies
)
```

This query:
- Joins Person → Cast → Movie tables
- Aggregates movie count and average rating per actor
- Filters for quality (movies with 20+ votes)
- Requires at least 2 movies per actor
- Calculates career statistics

### Actor Filmography Query
```python
filmography = (
    session.query(Movie, Cast.character_name, Cast.cast_order)
    .join(Cast, Movie.id == Cast.movie_id)
    .filter(Cast.person_id == actor_id)
    .order_by(desc(Movie.release_date))
    .all()
)
```

## Adding Navigation Links

You'll need to update your navigation menu to include the Top Actors page.

### Option 1: Add to your base.html navbar
```html


        Movie Analytics

            Movies
            Top Actors
            Analytics
            Search



```

### Option 2: Add to homepage (index.html)
Add a new button or section:
```html

     Top Actors

```

## UI Features

### Sorting Options
- **Most Movies**: Actors with the most appearances (default)
- **Highest Rated**: Actors whose movies have highest avg rating
- **Most Popular**: Based on TMDB popularity score
- **Name (A-Z)**: Alphabetical order

### Responsive Grid
- **Desktop (lg)**: 6 actors per row
- **Tablet (md)**: 4 actors per row
- **Small tablet (sm)**: 3 actors per row
- **Mobile**: 2 actors per row

### Actor Card Information
- Profile photo (or person icon placeholder)
- Actor name (clickable)
- Movie count badge
- Average rating across their films

### Actor Detail Layout
- **Left column** (25%): Profile, stats, biography
- **Right column** (75%): Complete filmography grid

## Testing Guide

### Test Cases

1. **Top Actors Page**
   - Visit `/top-actors`
   - Verify actors are displayed with images
   - Check movie counts are accurate
   - Test sorting options
   - Navigate through pages
   - Click on an actor card

2. **Actor Detail Page**
   - Verify profile information displays
   - Check biography (if available)
   - Verify career statistics are correct
   - Check filmography movies are listed
   - Verify character names appear
   - Click on a movie to verify links work

3. **Edge Cases**
   - Actor with no profile image (should show icon)
   - Actor with no biography (section should hide)
   - Actor with 2 movies (minimum threshold)
   - Actor with 50+ movies (pagination on detail page)

4. **Sorting**
   - Sort by "Most Movies" - verify highest count first
   - Sort by "Highest Rated" - verify best ratings first
   - Sort by "Name" - verify alphabetical order

### SQL Performance
The top actors query uses:
- Proper JOINs (indexed foreign keys)
- GROUP BY with aggregations
- HAVING clause for filtering
- ORDER BY for sorting
- LIMIT/OFFSET for pagination

Expected performance: < 50ms for typical database sizes

## Configuration Notes

### Image URLs
Uses the existing `config.get_poster_url()` method for:
- Actor profile images (w300 and w500 sizes)
- Movie posters in filmography

### Minimum Thresholds
```python
Movie.vote_count > 20  # Only quality movies
func.count(Cast.movie_id) >= 2  # At least 2 movies per actor
```

Adjust these values if you want:
- **More actors**: Lower to `>= 1` movie
- **Higher quality**: Raise vote_count to `> 50` or `> 100`

## Future Enhancements

Potential improvements:
- **Search actors** by name
- **Filter by genre** (show actors in specific genres)
- **Decade filter** (actors prominent in certain decades)
- **Collaborations** (actors who frequently work together)
- **Career timeline** chart showing movies per year
- **Award information** (if data available)
- **Similar actors** recommendations
- **Social links** (Twitter, Instagram, IMDb)

## Database Requirements

✅ **No migrations needed!**

Uses existing tables:
- `people` - Actor information
- `cast` - Movie-actor relationships with character names
- `movies` - Movie data
- `movie_genres` - For top genres calculation

All relationships already established via SQLAlchemy models.

## Dependencies

✅ **No new dependencies!**

Uses existing:
- Flask routing
- SQLAlchemy queries with aggregations
- Bootstrap 5 for UI
- Bootstrap Icons for icons
- Jinja2 templating

## Integration with Existing Features

### Movie Detail Page
The existing movie detail page already shows cast members. Now those cast member names can link to actor detail pages:

```html


    {{ person.name }}

```

### Analytics Dashboard
Consider adding an "Actors" section:
```python
# In analytics route
top_actors = (
    session.query(Person.name, func.count(Cast.movie_id).label('count'))
    .join(Cast)
    .group_by(Person.name)
    .order_by(desc('count'))
    .limit(10)
    .all()
)
```

## SEO Considerations

Actor pages are great for SEO:
- Unique content per actor
- Links to movie pages (internal linking)
- Rich metadata (birthdate, birthplace, etc.)
- Regular updates as new movies are added

Consider adding meta tags:
```html

```

## Accessibility

Included features:
- Alt text on images
- Semantic HTML (`<nav>`, `<main>`, etc.)
- ARIA labels on pagination
- Keyboard navigable cards
- Icon fallbacks for missing images

## Mobile Experience

Optimized for mobile:
- Responsive grid (2 columns on mobile)
- Touch-friendly card targets
- Readable font sizes
- Efficient pagination
- Smooth scrolling

## Known Limitations

1. **Biography data**: May not be available for all actors (depends on TMDB data import)
2. **Profile images**: Some actors may not have profile photos
3. **Character names**: Older movies might have incomplete cast data
4. **Popularity scores**: Only updated when data is re-imported from TMDB

## Maintenance

Regular updates needed:
- Re-import actor data from TMDB periodically
- Update profile images when actors update their TMDB profiles
- Add new movies to keep filmographies current

---

This feature provides valuable insights into the actors in your database and creates an engaging browsing experience! 🎬
