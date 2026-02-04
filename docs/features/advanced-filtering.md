# Advanced Filtering Feature

## Overview
This feature adds comprehensive filtering capabilities to the movies page, allowing users to refine their movie search by:
- **Year**: Filter movies by specific release year
- **Decade**: Filter movies by decade (1920s-2020s)
- **Rating Range**: Set minimum and maximum rating thresholds (0.0-10.0)
- **Runtime**: Filter by movie duration in minutes

## Implementation Details

### Backend Changes (`src/app.py`)

#### New Query Parameters
The `/movies` route now accepts the following additional parameters:
- `year` (int): Specific year filter
- `decade` (int): Decade filter (e.g., 1990 for 1990s)
- `rating_min` (float): Minimum rating (0.0-10.0)
- `rating_max` (float): Maximum rating (0.0-10.0)
- `runtime_min` (int): Minimum runtime in minutes
- `runtime_max` (int): Maximum runtime in minutes

#### Database Query Enhancements
```python
# Year filtering using SQLAlchemy extract
if year:
    query = query.filter(extract('year', Movie.release_date) == year)

# Decade filtering (decade to decade+9)
if decade:
    decade_start = decade
    decade_end = decade + 9
    query = query.filter(
        extract('year', Movie.release_date) >= decade_start,
        extract('year', Movie.release_date) <= decade_end
    )

# Rating range filtering
if rating_min is not None:
    query = query.filter(Movie.vote_average >= rating_min)
if rating_max is not None:
    query = query.filter(Movie.vote_average <= rating_max)

# Runtime range filtering
if runtime_min is not None:
    query = query.filter(Movie.runtime >= runtime_min)
if runtime_max is not None:
    query = query.filter(Movie.runtime <= runtime_max)
```

#### Dynamic Filter Options
- **Available Years**: Extracted from the database using distinct years
- **Available Decades**: Generated programmatically (1920-current decade)

### Frontend Changes (`templates/movies.html`)

#### Filter UI Components
1. **Collapsible Filter Panel**: Bootstrap collapse component for better UX
2. **Year Dropdown**: Dynamic list of all years present in the database
3. **Decade Dropdown**: Pre-defined decade options (1920s-2020s)
4. **Rating Range Inputs**: Two number inputs for min/max rating (0.0-10.0, step 0.1)
5. **Runtime Range Inputs**: Two number inputs for min/max runtime in minutes

#### Active Filters Display
- Shows currently applied filters as badges
- Helps users understand what filters are active
- Only displays when filters are applied

#### JavaScript Enhancement
```javascript
// Mutual exclusivity: Year and Decade cannot both be selected
document.getElementById('year').addEventListener('change', function() {
    if (this.value) {
        document.getElementById('decade').value = '';
    }
});

document.getElementById('decade').addEventListener('change', function() {
    if (this.value) {
        document.getElementById('year').value = '';
    }
});
```

#### Pagination Updates
- All pagination links now preserve filter parameters
- Users can navigate through pages without losing their filter selections

## User Experience Improvements

1. **Progressive Disclosure**: Collapsible filter panel reduces initial visual clutter
2. **Clear Visual Feedback**: Active filters displayed as badges
3. **Easy Reset**: "Clear All" button to remove all filters at once
4. **Smart Defaults**: Placeholder text guides users on expected values
5. **No Results Handling**: Helpful message when filters return no movies
6. **Runtime Display**: Movie cards now show runtime alongside year

## SQL Query Performance Considerations

- All filters use indexed columns where applicable
- Year extraction uses SQLAlchemy's `extract()` function for database-level filtering
- Filters are applied in the database query, not in Python (efficient)
- Pagination ensures only 20 movies are fetched per page

## Testing Recommendations

### Test Cases
1. **Single Filter Tests**:
   - Filter by year only (e.g., 2020)
   - Filter by decade only (e.g., 1990s)
   - Filter by rating range (e.g., 7.0-10.0)
   - Filter by runtime (e.g., 90-120 minutes)

2. **Combined Filter Tests**:
   - Genre + Year
   - Decade + Rating Range
   - Year + Runtime + Rating
   - All filters combined

3. **Edge Cases**:
   - No results (very restrictive filters)
   - Very broad filters (no filters applied)
   - Year and Decade conflict (only one should apply)
   - Min > Max values (test validation)

4. **Pagination Tests**:
   - Navigate to page 2 with filters
   - Verify filters persist across pages
   - Change filters on page 2 (should reset to page 1)

5. **Sorting with Filters**:
   - Sort by rating with decade filter
   - Sort by release date with rating filter

## Future Enhancements

Potential improvements for future iterations:
- Add genre multi-select (currently single genre only)
- Add language filter
- Add production company filter
- Save filter presets (requires user accounts)
- Export filtered results as CSV
- Add "quick filter" buttons (e.g., "90s Action", "Highly Rated Thrillers")
- Range sliders instead of text inputs for better UX
- Real-time filter updates (AJAX) instead of page reload

## Migration Notes

### For Existing Installations
No database migrations required - all filters use existing Movie table columns.

### Breaking Changes
None. This is a backward-compatible addition.

## API Impact

If you plan to add API endpoints in the future, these same filters can be exposed:
```
GET /api/movies?year=1990&rating_min=7.0&runtime_min=90
```

## Files Modified

1. `src/app.py` - Added filter logic to `/movies` route
2. `templates/movies.html` - Added filter UI and updated pagination

## Dependencies

No new dependencies required. Uses existing:
- SQLAlchemy for database queries
- Bootstrap 5 for UI components
- Jinja2 for templating
