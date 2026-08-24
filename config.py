"""
config.py

Global configuration for the Movie Calendar project.
"""

import os
from pathlib import Path

# ============================================================
# Project directories
# ============================================================

ROOT = Path(__file__).resolve().parent

FETCHERS_DIR = ROOT / "fetchers"

CACHE_DIR = ROOT / "cache"

DOCS_DIR = ROOT / "docs"

CACHE_DIR.mkdir(exist_ok=True)

DOCS_DIR.mkdir(exist_ok=True)

# ============================================================
# Generated files
# ============================================================

MOVIES_JSON = DOCS_DIR / "movies.json"

OMDB_CACHE = CACHE_DIR / "omdb_cache.json"

LETTERBOXD_CACHE = CACHE_DIR / "letterboxd_cache.json"

# ============================================================
# API Keys
# ============================================================

AMC_API_KEY = os.getenv("AMC_API_KEY")

OMDB_API_KEY = os.getenv("OMDB_API_KEY")

# ============================================================
# API Endpoints
# ============================================================

AMC_BASE_URL = "https://api.amctheatres.com/v2"

OMDB_BASE_URL = "https://www.omdbapi.com/"

# Sidewalk isn't in TMS/Gracenote's theatre database (confirmed by
# directly querying TMS and finding no Sidewalk listings at all), so
# showtimes are scraped from Sidewalk's own public showtimes page instead.
#
# That page sits behind Cloudflare/a WAF that flatly 403s requests from
# GitHub Actions' datacenter IPs, even with browser-like headers -- the
# identical request works fine from a home IP, so this is IP-reputation
# based, not header based. Routed through a small Cloudflare Worker
# (cloudflare/sidewalk-proxy-worker.js) instead, which fetches Sidewalk's
# page from Cloudflare's own edge network and mimics a real browser there.
SIDEWALK_CINEMA_URL = "https://shiny-resonance-e149.rileydurbin.workers.dev/"
SIDEWALK_MAX_PAGES = 30  # safety ceiling; the real page count usually stops well short
SIDEWALK_PAGE_DELAY = 0.5

# ============================================================
# Request settings
# ============================================================

REQUEST_TIMEOUT = 30

USER_AGENT = (
    "MovieCalendar/1.0 "
    "(https://github.com/yourusername/movie-calendar)"
)

SHOWTIME_PAGE_SIZE = 100

OMDB_DELAY = 0.25

LETTERBOXD_DELAY = 0.5

# ============================================================
# Birmingham Theaters
# ============================================================

AMC_THEATERS = {
    4101: {
        "name": "AMC Summit 16",
        "city": "Birmingham",
    },
    4103: {
        "name": "AMC Patton Creek 15",
        "city": "Hoover",
    },
    4105: {
        "name": "AMC Vestavia Hills 10",
        "city": "Vestavia Hills",
    },
}

SIDEWALK_THEATER = {
    "name": "Sidewalk Film Center + Cinema",
    "city": "Birmingham",
}

TARGET_THEATERS = [
    AMC_THEATERS[4101]["name"],
    AMC_THEATERS[4103]["name"],
    AMC_THEATERS[4105]["name"],
    SIDEWALK_THEATER["name"],
]

# ============================================================
# Estimated screen widths (feet)
# ============================================================
#
# AMC's API exposes no auditorium/screen dimensions, and its
# seating-layout endpoints (linked from every showtime) 404 under the
# vendor key -- that data is only reachable from inside an actual
# purchase session, not a read-only catalog integration. These are
# manual estimates from on-site seat counts per auditorium, using
# per-seat-type widths worked out by hand (see project notes):
#   - standard fixed seat: 21" per-seat row pitch (shared armrests are
#     already baked into how fixed seating is manufactured/specced)
#   - AMC Signature Recliner, single: 32" standalone, but neighbors in
#     the same row share an armrest, so each seat after the first in a
#     contiguous run only costs 26" -- total = 26*seats + 6
#   - AMC Signature Recliner, paired ("loveseat"): 58" per pair, shared
#     center console, no correction needed (pairs are self-contained
#     units, not shared row-to-row like the singles)
#
# Keyed by AMC theatre ID -> auditorium number -> estimated screen
# width in feet. Static physical data, not something to fetch per run.
AUDITORIUM_SCREEN_WIDTH_FT = {
    4101: {  # AMC Summit 16 (single recliners)
        1: 20.0,
        2: 20.0,
        3: 20.0,
        4: 20.0,
        5: 20.0,
        6: 20.0,
        7: 28.7,
        8: 28.7,
        9: 28.7,
        10: 28.7,
        11: 20.0,
        12: 20.0,
        13: 17.8,
        14: 17.8,
        15: 20.0,
        16: 20.0,
    },
    4103: {  # AMC Patton Creek 15 (standard seats)
        1: 29.8,
        2: 35.0,
        3: 35.0,
        4: 33.3,
        5: 38.5,
        6: 47.3,
        7: 61.3,
        8: 61.3,
        9: 29.8,
        10: 33.3,
        11: 35.0,
        12: 35.0,
        13: 29.8,
        14: 59.5,
        15: 59.5,
    },
    4105: {  # AMC Vestavia Hills 10 (paired recliners)
        1: 43.5,
        2: 41.3,
        3: 36.5,
        4: 36.5,
        5: 31.7,
        6: 29.0,
        7: 29.0,
        8: 31.7,
        9: 43.5,
        10: 43.5,
    },
}

# Sidewalk has two identical auditoriums and no per-showtime auditorium
# number in the scraped data, so every Sidewalk showtime gets the same
# estimate rather than a per-auditorium lookup.
SIDEWALK_SCREEN_WIDTH_FT = 26.25

# ============================================================
# Poster settings
# ============================================================

POSTER_PRIORITY = [
    "posterDynamic",
    "posterAlternateDynamic",
    "poster3DDynamic",
    "posterIMAXDynamic",
    "posterDynamic180X74",
]

# ============================================================
# OMDb fields
# ============================================================

OMDB_RATINGS = {
    "Internet Movie Database": "imdb",
    "Rotten Tomatoes": "rotten",
    "Metacritic": "metacritic",
}

# ============================================================
# Helpers
# ============================================================

def require_api_key(name: str) -> str:
    """
    Raises a helpful exception if an API key is missing.
    """

    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"{name} environment variable is not set."
        )

    return value


def get_amc_key() -> str:
    return require_api_key("AMC_API_KEY")


def get_omdb_key() -> str:
    return require_api_key("OMDB_API_KEY")