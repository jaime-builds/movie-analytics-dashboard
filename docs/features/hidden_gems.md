# Feature #3: Hidden Gems - Implementation Guide

## 🎯 What This Feature Does

Discovers **high-rated, low-popularity movies** - those underrated films that deserve more attention. Uses a "gem score" algorithm to find the best overlooked movies in your database.

---

## 📦 Files to Update

### 1. **src/app.py** (Backend)
Replace your entire `src/app.py` with the new version.

**What's New:**
- Added `/hidden-gems` route

### 2. **templates/hidden_gems.html** (Frontend)
New template file.

**Location:** Copy to `templates/hidden_gems.html`

### 3. **templates/base.html** (Navigation)
Add Hidden Gems link to your navbar.

**Add this to your navbar** (after Top Actors):
```html

    Hidden Gems

```

---

## ✨ Key Features

### Discovery Algorithm
- **Minimum Rating**: Default 7.0+ (adjustable)
- **Maximum Popularity**: Default ≤20.0 (adjustable)
- **Minimum Votes**: 50+ (ensures credible ratings)

### Gem Score Formula
```python
gem_score = (rating / 10.0) * (100.0 / (popularity + 10))
```

**Higher score = Better gem**
- Balances high rating with low popularity
- Movies with rating 8.0 and popularity 5 score higher than 7.5/2

### Filters
- **Genre**: Filter by specific genre
- **Decade**: Filter by decade (1920s-2020s)
- **Minimum Rating**: Adjustable threshold (default 7.0)
- **Maximum Popularity**: How "hidden" (default 20.0)

### Sorting Options
1. **Gem Score** (default): Best balance of rating & obscurity
2. **Highest Rating**: Sort by rating only
3. **Most Hidden**: Lowest popularity first
4. **Newest First**: Recent hidden gems

---

## 🚀 Installation Steps

### Step 1: Update Backend
```bash
# Replace your app.py
cp app.py /path/to/your-repo/src/app.py
```

### Step 2: Add Template
```bash
# Copy new template
cp hidden_gems.html /path/to/your-repo/templates/hidden_gems.html
```

### Step 3: Update Navigation
Open `templates/base.html` and add to navbar:
```html

    Hidden Gems

```

### Step 4: Test
```bash
python -m src.app
```

Visit: `http://127.0.0.1:5000/hidden-gems`

---

## 🎨 What Users See

### Hidden Gems Page Features
- **Gem badge** on each movie card (shows gem score)
- **Rating badge** (yellow star)
- **Popularity display** (how obscure the movie is)
- **Filter panel** to customize discovery
- **Info box** explaining what makes a hidden gem
- **Pagination** for browsing many gems

### Visual Elements
- Green gem badge with score on each poster
- Collapsible filter panel
- Info alert explaining the criteria
- Hover effects on movie cards

---

## 🔧 Customization

### Change Default Thresholds

In `app.py`, line ~211:
```python
min_rating = request.args.get("min_rating", default=7.0, type=float)  # Change 7.0
max_popularity = request.args.get("max_popularity", default=20.0, type=float)  # Change 20.0
```

### Adjust Minimum Vote Count

In `app.py`, line ~218:
```python
Movie.vote_count >= 50  # Change to 30 (more movies) or 100 (higher quality)
```

### Modify Gem Score Algorithm

In `app.py`, line ~242:
```python
# Current formula
movie.gem_score = (movie.vote_average / 10.0) * (100.0 / (movie.popularity + 10))

# Alternative: Emphasize obscurity more
movie.gem_score = (movie.vote_average / 10.0) * (200.0 / (movie.popularity + 5))

# Alternative: Emphasize rating more
movie.gem_score = (movie.vote_average ** 2) / (movie.popularity + 10)
```

---

## 📊 SQL Query Details

### The Main Query
```python
query = session.query(Movie).filter(
    Movie.vote_average >= min_rating,      # High rating
    Movie.popularity <= max_popularity,     # Low popularity
    Movie.vote_count >= 50                  # Credible votes
)
```

### Sorting by Gem Score
```python
query.order_by(
    desc(Movie.vote_average / (func.log(Movie.popularity + 2) * 2))
)
```

Uses logarithmic scaling to balance rating vs. popularity.

---

## 🧪 Testing Checklist

- [ ] Hidden Gems page loads (`/hidden-gems`)
- [ ] Movies displayed with gem scores
- [ ] Default shows movies rated 7.0+ with popularity ≤20
- [ ] Filter by genre works
- [ ] Filter by decade works
- [ ] Adjust minimum rating (e.g., 8.0)
- [ ] Adjust max popularity (e.g., 10.0)
- [ ] Sort by "Gem Score" (default)
- [ ] Sort by "Highest Rating"
- [ ] Sort by "Most Hidden"
- [ ] Sort by "Newest First"
- [ ] Pagination works
- [ ] Reset button clears filters
- [ ] Click movie → Goes to detail page
- [ ] Works on mobile (responsive)

---

## 💡 Examples of What You'll Find

### Typical Hidden Gems
- **Rating 8.0-9.0, Popularity 5-15**: Critically acclaimed indie films
- **Rating 7.5+, Popularity <5**: Cult classics
- **Rating 8.5+, Popularity <10**: International masterpieces

### Gem Score Examples
| Movie | Rating | Popularity | Gem Score |
|-------|--------|-----------|-----------|
| Indie Drama | 8.2 | 8.5 | **4.45** ← Great gem! |
| Blockbuster | 8.0 | 150.0 | **0.50** ← Not hidden |
| Foreign Film | 7.8 | 3.2 | **5.88** ← Best gem! |

---

## 🎯 Use Cases

### For Users
- "Show me great movies I've never heard of"
- "Find critically acclaimed indie films"
- "Discover international cinema gems"
- "What are the best 1990s movies that weren't blockbusters?"

### For Discovery
- Browse by decade to find era-specific hidden gems
- Filter by genre for niche discoveries
- Adjust thresholds to control how "hidden" movies should be

---

## 🔗 Integration Points

### Links to This Page
Add buttons/links from:
- **Homepage**: "Discover Hidden Gems" button
- **Analytics**: "View Hidden Gems" link
- **Movie Detail**: "More like this (Hidden)" section

### Enhance Movie Detail Page
Show if a movie is a "hidden gem":
```html
{% if movie.popularity < 20 and movie.vote_average >= 7.0 %}

     Hidden Gem

{% endif %}
```

---

## 📝 Good Commit Message

```bash
git commit -m "Add Hidden Gems discovery page

- Add /hidden-gems route for discovering underrated movies
- Implement gem score algorithm balancing rating and obscurity
- Add filters: genre, decade, min rating, max popularity
- Add sorting: gem score, rating, most hidden, newest
- Display gem score badge on each movie card
- Show popularity metric alongside rating
- Include collapsible filter panel with info box
- Add pagination for browsing large result sets
- Default criteria: rating 7.0+, popularity ≤20, votes 50+"
```

---

## 🚫 Common Issues

**Q: No gems found?**
- Your database might only have popular movies
- Lower the minimum rating to 6.5 or 6.0
- Increase max popularity to 30 or 50

**Q: Too many results?**
- Raise minimum rating to 7.5 or 8.0
- Lower max popularity to 15 or 10

**Q: Gem scores seem weird?**
- The formula emphasizes both quality AND obscurity
- A 7.5 rated movie with popularity 2 can score higher than 8.0/20
- Adjust the formula if needed (see Customization section)

---

## 🎉 What Makes This Feature Special

1. **Smart Algorithm**: Not just low popularity, but HIGH QUALITY + low popularity
2. **Adjustable Discovery**: Users control what "hidden" means to them
3. **Multiple Sort Options**: Different ways to explore gems
4. **Visual Feedback**: Gem score badges make it easy to spot great finds
5. **Educational**: Info box teaches users what makes a hidden gem
6. **No Database Changes**: Uses existing Movie table data

---

### Final Navigation Should Look Like:
```
Home | Movies | Top Actors | Hidden Gems | Analytics
```

Enjoy discovering hidden gems in your movie database! 💎🎬
