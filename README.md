# Movie Calendar — pages-webapp

This folder builds a static movie showtimes site suitable for GitHub Pages.

Overview
- The Python backend fetches showtimes from the AMC API (`fetchers/amc.py`), enriches metadata using OMDb (`fetchers/omdb.py`), downloads poster images into `docs/posters/`, and writes `docs/movies.json` consumed by the frontend (`docs/index.html`).

Quick local preview

1. Install dependencies (recommended in a virtualenv):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Export API keys locally (example):

```bash
export AMC_API_KEY=your_amc_key
export OMDB_API_KEY=your_omdb_key
```

3. Run the pipeline to generate `docs/movies.json` and download posters:

```bash
python fetch_movies.py
```

4. Preview the generated site:

```bash
python3 -m http.server --directory docs 8000
# Open http://localhost:8000 in your browser
```

GitHub Pages setup (repo-level)

- This project expects a `docs/` folder at the repository root containing `index.html`, `movies.json`, and `posters/`.
- When you push this folder as the repository root (for example, by creating a repository whose contents are the files inside this `pages-webapp` folder), enable GitHub Pages in the repository Settings → Pages and select `main` (or the branch you use) and the `/docs` folder as the source.

Secrets (required for Actions)

Add the following repository secrets under Settings → Secrets & variables → Actions:

- `AMC_API_KEY` — your AMC API key (X-AMC-Vendor-Key header)
- `OMDB_API_KEY` — your OMDb API key
 - `TMS_API_KEY` — your TMS / Gracenote API key used to fetch Sidewalk showtimes

CI / GitHub Actions

- A workflow file `.github/workflows/update.yml` is included. It runs daily (and can be triggered manually) to:
  1. Install `requests`.
  2. Run `python fetch_movies.py` which regenerates `docs/movies.json` and downloads missing posters into `docs/posters/`.
  3. Commit any changed files under `docs/` back to the repo so Pages serves the newest data.

Notes about repository layout

- If you will *only* push the contents of this `pages-webapp` directory as the repository root, the provided workflow will work as-is. If you instead put this folder inside a larger repository, you should update `.github/workflows/update.yml` paths to point to `pages-webapp/` subpath accordingly.

Data sources and theaters

This project currently includes showtimes for four theaters:

- AMC Summit 16 (theater id 4101)
- AMC Patton Creek 15 (theater id 4103)
- AMC Vestavia Hills 10 (theater id 4105)
- Sidewalk Film Center + Cinema (integrated later as a future source / `SIDEWALK_THEATER` in `config.py`)
 - Sidewalk Film Center + Cinema (included via the TMS API and merged into `movies.json`)

How far in the future is fetched

- The AMC fetcher (`fetchers/amc.py`) requests showtimes from AMC's `/theatres/{id}/showtimes` endpoint and paginates results. The API determines how many days ahead are returned. Practically, the generated `movies.json` contains whatever upcoming showtimes the AMC API returns at fetch time. If you need a configurable lookahead window, I can add a date-range parameter to the fetcher.

Poster and movie data retention

- OMDb responses are cached in `cache/omdb_cache.json` by `fetchers/omdb.py` to avoid re-querying OMDb for unchanged titles.
- Posters are downloaded into `docs/posters/`. The pipeline avoids re-downloading posters that already exist (it checks file presence by filename).
- After each run the pipeline removes stale poster files: any files in `docs/posters/` not referenced by the newly generated `movies.json` are deleted. This keeps the poster directory trimmed to only the artwork currently referenced by the frontend.

Scheduling and frequency

- The default workflow runs daily (see `.github/workflows/update.yml`). You can change the cron schedule in that file or trigger the workflow manually from the Actions tab.

Security and secrets

- Never commit API keys. Use GitHub repository secrets for Actions and local environment variables for local testing.

Troubleshooting

- If Actions fails due to missing keys, confirm `AMC_API_KEY` and `OMDB_API_KEY` are set in the repository secrets.
- If posters are failing to download due to remote URL changes, inspect the `docs/movies.json` poster URLs and check network access.

Next improvements (suggested)

- Add image resizing/optimization to generate thumbnails and medium sizes for faster page loads.
- Add a configurable date-range for AMC fetches.
- Add test coverage for stale-poster removal behavior.
