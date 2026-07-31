# Movie Calendar Project - Backend Handoff

## Goal

Build a static GitHub Pages website that displays movie showtimes for Birmingham-area theaters.

The backend is a Python project that periodically fetches data from APIs and generates a single JSON file consumed by the frontend.

Pipeline:

```text
AMC API
        \
Sidewalk scraper/API
         \
      Merge Movies
           ↓
    OMDb Enrichment
           ↓
 Download/Cache Posters
           ↓
  Generate movies.json
           ↓
    GitHub Pages UI
```

Currently only the AMC portion is implemented.

---

# Project Structure

```text
movie-calendar/

config.py
models.py
fetch_movies.py

fetchers/
    __init__.py
    amc.py
    omdb.py

cache/
    omdb_cache.json

docs/
    movies.json
    posters/
```

---

# APIs

## AMC

Authentication:

```
X-AMC-Vendor-Key
```

Working endpoint:

```
GET /v2/theatres/{id}/showtimes
```

Theater IDs:

- 4101 — AMC Summit 16
- 4103 — AMC Patton Creek 15
- 4105 — AMC Vestavia Hills 10

Pagination is implemented and tested.

## OMDb

Authentication:

```
apikey=...
```

Used for enrichment and cached locally.

---

# Architecture

## Movie

Canonical movie object containing:

- title
- runtime
- rating
- genres
- poster
- plot
- actors
- directors
- writers
- IMDb rating
- Rotten Tomatoes rating
- Metacritic rating
- awards
- language
- country
- box office
- movie_url
- trailer_url
- showtimes

Methods:

- `add_showtime()`
- `sort_showtimes()`
- `to_dict()`

---

## Showtime

Contains:

- theater
- theater_id
- showtime_id
- datetime
- datetime_utc
- auditorium
- premium_format
- purchase_url
- sold out status
- accessibility attributes
- ticket prices

---

## TicketPrice

Contains:

- type
- price
- tax

---

# config.py

Contains:

- project directories
- generated file paths
- API keys
- API endpoints
- theater IDs
- request settings

---

# fetchers/amc.py

Implemented and tested.

Responsibilities:

- authenticate
- paginate through every showtime page
- normalize AMC responses
- create Movie objects
- create Showtime objects
- group showtimes by movie
- return `List[Movie]`

---

# fetchers/omdb.py

Designed to:

- cache OMDb responses
- enrich Movie objects
- fill only missing fields
- preserve AMC data where appropriate

Populates:

- plot
- actors
- directors
- writers
- IMDb ID
- IMDb rating
- Rotten Tomatoes
- Metacritic
- awards
- language
- country
- runtime (if missing)
- release year (if missing)

---

# fetch_movies.py

Pipeline:

```
AMC Fetch
    ↓
Normalize
    ↓
OMDb Enrichment
    ↓
Download Posters
    ↓
Validate
    ↓
Generate Statistics
    ↓
Write docs/movies.json
```

Downloads posters into:

```
docs/posters/
```

Then rewrites poster URLs to local paths such as:

```
posters/superman-2025.jpg
```

---

# Frontend

Already exists as a single HTML page.

Features:

- monthly calendar
- seven days per row
- poster grid
- movie details modal
- grouped showtimes by theater
- purchase links

Consumes:

```
docs/movies.json
```

---

# Remaining Backend Work

1. Review and complete `fetch_movies.py`
2. Finish and test `fetchers/omdb.py`
3. Improve poster caching (download only missing posters)
4. Generate richer metadata:

   - theaters
   - generated_at
   - movie_count
   - showtime_count

5. Verify generated `movies.json` loads correctly in the frontend.

---

# Future Work

## Sidewalk Integration

Implement via scraper or API.

Merge with AMC movies before enrichment.

---

## GitHub Actions

Create:

```
.github/workflows/update.yml
```

Pipeline:

```
checkout
↓
setup python
↓
pip install
↓
python fetch_movies.py
↓
commit updated movies.json
↓
deploy
```

---

## Image Optimization

Resize downloaded posters.

Generate:

- thumbnail
- medium
- full-size

versions.

---

## Trailer Support

Eventually enrich with TMDB or YouTube.

---

# Current Status

- ✅ Project architecture established
- ✅ `models.py` completed
- ✅ `config.py` completed
- ✅ `fetchers/amc.py` implemented and tested against the live AMC API
- ⚠️ `fetchers/omdb.py` needs review and testing
- ⚠️ `fetch_movies.py` needs review and end-to-end testing
- ⚠️ Poster caching should be improved
- ⏳ Generate validated `docs/movies.json`
- ⏳ Sidewalk integration
- ⏳ GitHub Actions automation
- ⏳ GitHub Pages deployment

## Immediate Goal

Produce a robust backend that, when run locally with valid `AMC_API_KEY` and `OMDB_API_KEY` environment variables, generates:

- `docs/movies.json`
- locally cached poster images in `docs/posters/`

These outputs should be consumable by the existing GitHub Pages frontend.