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