# Movie Calendar — pages-webapp

This folder builds a static movie showtimes site suitable for GitHub Pages.

Overview
- The Python backend fetches showtimes from the AMC API (`fetchers/amc.py`) and by scraping Sidewalk Film Center + Cinema's public showtimes page (`fetchers/sidewalk.py`), enriches metadata using OMDb (`fetchers/omdb.py`) and Letterboxd ratings (`fetchers/letterboxd.py`), downloads poster images into `docs/posters/`, and writes `docs/movies.json` consumed by the frontend (`docs/index.html`).

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

Sidewalk showtimes don't need a key — they're scraped directly from Sidewalk's own site (see "Data sources and theaters" below).

CI / GitHub Actions

- A workflow file `.github/workflows/update.yml` is included. It runs four times a day (and can be triggered manually) to:
  1. Install the packages in `requirements.txt`.
  2. Run `python fetch_movies.py` which regenerates `docs/movies.json` and downloads missing posters into `docs/posters/`.
  3. Commit any changed files under `docs/` back to the repo so Pages serves the newest data.

Notes about repository layout

- If you will *only* push the contents of this `pages-webapp` directory as the repository root, the provided workflow will work as-is. If you instead put this folder inside a larger repository, you should update `.github/workflows/update.yml` paths to point to `pages-webapp/` subpath accordingly.

Data sources and theaters

This project currently includes showtimes for four theaters:

- AMC Summit 16 (theater id 4101)
- AMC Patton Creek 15 (theater id 4103)
- AMC Vestavia Hills 10 (theater id 4105)
- Sidewalk Film Center + Cinema

Sidewalk showtimes were originally fetched from the TMS/Gracenote API, but
TMS stopped carrying Sidewalk in its theatre database entirely (confirmed by
querying TMS directly and finding no Sidewalk listings for the area, despite
Sidewalk showing current showtimes on their own site). `fetchers/sidewalk.py`
now parses Sidewalk's public cinema page (`sidewalkfest.com/cinema/`)
instead and merges results into `movies.json` the same way AMC's
showtimes are.

How Sidewalk's pages reach the pipeline

Sidewalk's site is behind Cloudflare, which answers GitHub Actions' runners
with a JavaScript challenge ("Just a moment...", HTTP 403,
`cf-mitigated: challenge`) instead of the page. History of what was tried:

1. Direct request from the runner, with browser-like headers: challenged.
2. A Cloudflare Worker that proxied each request live (Aug 16 – Sep 17,
   2026): worked for a month, then was challenged too -- but only when a
   GitHub runner was the one calling the Worker. The same Worker called
   from a home IP (or a VPN's datacenter IP) still got the real page.
3. Current design (since Oct 1, 2026): the Worker
   (`cloudflare/sidewalk-proxy-worker.js`) scrapes every page itself on a
   Cron Trigger and stores them in Workers KV. Requests to the Worker only
   read that stored copy, so the runner never causes a request to Sidewalk.

Worker setup (Cloudflare dashboard, account-side -- none of this lives in
the repo, and the Worker code is deployed by pasting the file into the
dashboard's editor, not by CI):

- Worker: `shiny-resonance-e149` (`https://shiny-resonance-e149.rileydurbin.workers.dev/`,
  set as `SIDEWALK_CINEMA_URL` in `config.py`)
- KV namespace `sidewalk-cache`, bound to the Worker as `SIDEWALK_KV`
- Cron Trigger `30 3,9,15,21 * * *` (UTC), half an hour before each
  GitHub Actions run. If the workflow's schedule changes, change this too.

Worker endpoints:

- `/` and `/?_paged=N` -- the stored HTML for page N, with an
  `X-Fetched-At` header saying when it was scraped
- `/status` -- JSON with the stored copy's timestamp and page count, plus
  the result of the latest scrape attempt (including the error if it failed)

A failed scrape leaves the previous stored copy in place, so the site keeps
showing the last good Sidewalk data rather than dropping the theater.
`fetchers/sidewalk.py` prints the stored copy's age on every run and a
`WARNING` once it is older than `SIDEWALK_STALE_HOURS` (24).

Other sources looked at and ruled out: Elevent (Sidewalk's ticketing
vendor; its widget API at `widget.goelevent.com` needs keys and has no
listing endpoint), and Sidewalk's WordPress REST API (same host, so the
same challenge).

Seat maps (AMC showtimes only)

Hovering an AMC showtime in the movie modal shows a live seat map. The page
(`docs/index.html`) requests it from a second Cloudflare Worker,
`patient-haze-05d5` (`cloudflare/seatmap-worker.js`, deployed by pasting the
file into the dashboard editor; no bindings or triggers):

`https://patient-haze-05d5.rileydurbin.workers.dev/seats?theater_id=4101&showtime_id=147495013&datetime=2026-10-01T22:30:00`

The data comes from Fandango's checkout pages, not from AMC. The Worker
finds the Fandango showtime at the same theater and start time, gets an
anonymous checkout token, fetches the seat map, and confirms the match by
the AMC showtime ID that Fandango embeds in its ticket codes. This is not a
documented API and may break or be locked down without notice; when a lookup
fails the tooltip shows "Seat map unavailable".

Sources tried and ruled out (Oct 2026):

- AMC's API: this vendor key has no seating endpoint. Every showtime links to
  `/v2/seating-layouts/{theatre}/{performanceNumber}`, but it returns
  "No matching Web application endpoint was found".
- AMC's website and `graph.amctheatres.com`: Cloudflare blocks anything that
  isn't a real browser, even from a home connection.
- walzr.com (used until Aug 2026): its seat-map fragments now come back empty.
- SeatDrop's backend (used Aug–Sep 2026): now refuses outside use and its
  terms prohibit automated access. Do not go back to it.
- Atom Tickets, Moviefone, IMDb: bot-challenged, and the latter two have no
  seat maps of their own.

Known gaps: after-midnight showtimes are untested, and the Worker's allowed
browser origins are only `radurbin.github.io` and `localhost:8000`.

A-List plan sync

The posters picked in A-List Plan Mode are kept in the browser's
`localStorage` and, once a sync code has been entered on a device (the
"Sync" button in the header), mirrored to a third Cloudflare Worker,
`alist-sync` (`cloudflare/alist-sync-worker.js`,
`https://alist-sync.rileydurbin.workers.dev/plan`).

- Account-side setup: KV namespace bound as `ALIST_KV`, and a secret named
  `SYNC_CODE`. The sync code is that secret; it is not stored in the repo.
- The plan is a single KV entry. The page downloads it on load and whenever
  the tab is shown again, and uploads after every pick. Last save wins.
- KV can take up to a minute to show a change elsewhere, so the page skips
  downloading for 60 seconds after its own upload.
- Picks more than a week old are dropped from what gets uploaded.

How far in the future is fetched

- The AMC fetcher (`fetchers/amc.py`) requests showtimes from AMC's `/theatres/{id}/showtimes` endpoint and paginates results. The API determines how many days ahead are returned. Practically, the generated `movies.json` contains whatever upcoming showtimes the AMC API returns at fetch time. If you need a configurable lookahead window, I can add a date-range parameter to the fetcher.

Poster and movie data retention

- OMDb responses are cached in `cache/omdb_cache.json` by `fetchers/omdb.py` to avoid re-querying OMDb for unchanged titles.
- Letterboxd ratings are looked up fresh on every run by `fetchers/letterboxd.py` and never cached on disk, so they are at most one run (about six hours) old. Letterboxd has no public API, so each movie's page is found via its IMDb ID (`letterboxd.com/imdb/{imdb_id}/`, which redirects to the film page) and the rating is read out of that page's embedded JSON-LD. This only works for movies OMDb already resolved an `imdb_id` for; Letterboxd's own search page 403s scripted requests, so there's no title-based fallback for movies OMDb missed.
- Posters are downloaded into `docs/posters/`. `docs/poster_sources.json` records which remote URL each file came from; a poster is re-downloaded only when its source URL changes. This matters for special events, which AMC lists weeks ahead with "poster coming soon" art and updates later under a new URL (before Oct 2026 the pipeline kept the first file forever).
- Placeholder art is recognised by an image fingerprint (`PLACEHOLDER_POSTER_FINGERPRINTS` in `config.py`) and treated as no poster, so the movie falls back to OMDb's poster, or to the plain title tile, until real art appears. If a new placeholder design shows up, add its fingerprint there.
- OMDb matching for re-releases: AMC's release year is the re-release's, so `fetchers/omdb.py` tries the original year implied by "Nth Anniversary" in the title, then AMC's year, then a title-only lookup, and only accepts a result that agrees with AMC's own director, cast or running time. Director, cast and synopsis come from AMC's movie record when it has them. A film OMDb can't match confidently is left un-enriched rather than given another film's data.
- `cache/omdb_cache.json` is committed by the workflow so each run only queries new or expired titles (hits expire after 1 day for films from this year or last and 7 days for older ones, misses after 2). OMDb's free tier allows 1,000 requests a day; an OMDb failure no longer stops the run.
- After each run the pipeline removes stale poster files: any files in `docs/posters/` not referenced by the newly generated `movies.json` are deleted. This keeps the poster directory trimmed to only the artwork currently referenced by the frontend.

Scheduling and frequency

- The workflow runs at 04:00, 10:00, 16:00 and 22:00 UTC (see `.github/workflows/update.yml`). You can change the cron schedule in that file or trigger the workflow manually from the Actions tab (`gh workflow run update.yml`). The Cloudflare Worker's Cron Trigger is set 30 minutes ahead of these times, so keep the two in step.

Security and secrets

- Never commit API keys. Use GitHub repository secrets for Actions and local environment variables for local testing.

Troubleshooting

- If Actions fails due to missing keys, confirm `AMC_API_KEY` and `OMDB_API_KEY` are set in the repository secrets.
- If Sidewalk disappears from the site or its showtimes look stale: a Sidewalk failure does not fail the workflow (the run continues with AMC only), so check the run log for the `Fetching Sidewalk showtimes` section, then open the Worker's `/status` URL. `"ok": false` with `cf-mitigated challenge` in the error means Sidewalk has started challenging the Worker's scheduled scrape as well; the fallback that was planned but never needed is running the Sidewalk scrape from a home machine and committing its output for the workflow to merge.
- If posters are failing to download due to remote URL changes, inspect the `docs/movies.json` poster URLs and check network access.

Next improvements (suggested)

- Add image resizing/optimization to generate thumbnails and medium sizes for faster page loads.
- Add a configurable date-range for AMC fetches.
- Add test coverage for stale-poster removal behavior.
