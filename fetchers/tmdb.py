"""
fetchers/tmdb.py

Guesses what AMC's mystery screenings ("Screen Unseen" / "Scream
Unseen") are going to be.

AMC only publishes two clues for these: the MPA rating and a running
time. The guess is "upcoming US releases with that rating, about that
length, opening soon" -- the same method fans use by hand. AMC's own
catalog doesn't list films far enough ahead (or with complete ratings
and running times) to be the source for that, so the upcoming releases
come from TMDB's API instead.

The numbers below were set from data/screen_unseen_history.csv, the 97
screenings from Nov 2023 to Sep 2026 as recorded by the r/AMCsAList
megathread (AMC's listed running time, the real one, and the film):

  - Listed minus real running time ran from -7 to +17 minutes, with
    more than half between +2 and +6.
  - The film opened 4-13 days after the screening 90% of the time
    (i.e. that Friday or the next), 14-20 days for most of the rest,
    and later than that once.
  - Every Scream Unseen film was tagged Horror on TMDB; 4 of 79 Screen
    Unseen films were too, so horror is penalised there, not excluded.

tools/backtest_unseen.py replays those screenings through score()
below. Re-run it after changing any of these numbers.

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import List, Optional

import requests

from config import (
    REQUEST_TIMEOUT,
    TMDB_API_KEY,
    TMDB_BASE_URL,
)

from models import Movie

UNSEEN_RE = re.compile(r"\b(screen|scream) unseen\b", re.IGNORECASE)

# How long after the mystery screening the film may open.
RELEASE_WINDOW_DAYS = 20

# AMC's listed running time minus the real one, in minutes.
PADDING_MIN = -7
PADDING_MAX = 17

MAX_CANDIDATES = 6

# AMC writes ratings without the hyphen.
RATING_ALIASES = {
    "PG13": "PG-13",
    "NC17": "NC-17",
}


def is_mystery_screening(movie: Movie) -> bool:
    return bool(UNSEEN_RE.search(movie.title or ""))


def score(
    listed_runtime: Optional[int],
    screening: date,
    horror_only: bool,
    us_release: str,
    first_release: str,
    runtime: Optional[int],
    genres: List[str],
    popularity: float,
) -> Optional[float]:
    """
    How well one upcoming film fits a mystery screening's clues: None
    if it can't be the film, otherwise higher is better.
    """

    is_horror = "Horror" in genres

    if horror_only and not is_horror:
        return None

    # A film already out by the screening isn't "never-before-seen",
    # and neither is a re-release of an older one.
    if not us_release:
        return None

    lead_days = (date.fromisoformat(us_release) - screening).days

    if not 1 <= lead_days <= RELEASE_WINDOW_DAYS:
        return None

    if first_release and int(first_release[:4]) < screening.year - 1:
        return None

    value = 1.0

    if runtime and listed_runtime:

        padding = listed_runtime - runtime

        if not PADDING_MIN <= padding <= PADDING_MAX:
            return None

        if 2 <= padding <= 6:
            value *= 1.0
        elif -3 <= padding <= 8:
            value *= 0.5
        else:
            value *= 0.15

    else:
        # TMDB doesn't know the running time yet: possible, unproven.
        value *= 0.15

    if lead_days <= 6:
        value *= 1.0
    elif lead_days <= 13:
        value *= 0.75
    else:
        value *= 0.2

    if is_horror and not horror_only:
        value *= 0.3

    if "Documentary" in genres:
        value *= 0.2

    # Better-known films are a little more likely; this only really
    # separates candidates that fit the clues equally well.
    value *= math.sqrt(math.log10(1 + popularity)) + 0.05

    return value


class TMDBFetcher:

    def __init__(self):
        self.api_key = TMDB_API_KEY
        self._details = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    # --------------------------------------------------
    # HTTP helper
    # --------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        # TMDB issues two kinds of credential; accept either.
        params = dict(params or {})
        headers = {"Accept": "application/json"}
        if self.api_key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            params["api_key"] = self.api_key

        response = requests.get(
            f"{TMDB_BASE_URL}{path}",
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    # --------------------------------------------------
    # Lookups
    # --------------------------------------------------

    def discover(self, rating: str, start: date, end: date) -> List[dict]:
        """US theatrical releases with this rating opening in the window."""
        results = []
        page = 1
        while page <= 5:
            data = self._get("/discover/movie", {
                "region": "US",
                "with_release_type": "2|3",  # limited | wide theatrical
                "certification_country": "US",
                "certification": rating,
                "release_date.gte": start.isoformat(),
                "release_date.lte": end.isoformat(),
                "sort_by": "popularity.desc",
                "page": page,
            })
            results.extend(data.get("results", []))
            if page >= data.get("total_pages", 1):
                break
            page += 1
        return results

    def movie_details(self, tmdb_id: int) -> dict:
        if tmdb_id not in self._details:
            self._details[tmdb_id] = self._get(f"/movie/{tmdb_id}")
        return self._details[tmdb_id]

    # --------------------------------------------------
    # Public methods
    # --------------------------------------------------

    def candidates(
        self,
        rating: str,
        listed_runtime: Optional[int],
        screening: date,
        horror_only: bool,
    ) -> List[dict]:
        """Every film that fits the clues, best fit first."""

        found = self.discover(
            rating,
            screening + timedelta(days=1),
            screening + timedelta(days=RELEASE_WINDOW_DAYS),
        )

        results = []

        for item in found:

            details = self.movie_details(item["id"])

            genres = [g["name"] for g in details.get("genres", [])]

            runtime = details.get("runtime") or None

            # With region=US, the search result's release_date is the
            # US one; the details' release_date is the film's first
            # release anywhere.
            value = score(
                listed_runtime,
                screening,
                horror_only,
                item.get("release_date") or "",
                details.get("release_date") or "",
                runtime,
                genres,
                details.get("popularity") or 0,
            )

            if value is None:
                continue

            poster_path = details.get("poster_path")

            results.append({
                "tmdb_id": item["id"],
                "title": details.get("title") or item.get("title"),
                "release_date": item.get("release_date"),
                "rating": rating,
                "runtime": runtime,
                "genres": genres,
                "poster": (
                    f"https://image.tmdb.org/t/p/w185{poster_path}"
                    if poster_path else None
                ),
                "url": f"https://www.themoviedb.org/movie/{item['id']}",
                "score": round(value, 3),
            })

        results.sort(key=lambda c: c["score"], reverse=True)

        return results

    def upcoming_releases(
        self,
        start: date,
        end: date,
        min_popularity: float,
    ) -> List[dict]:
        """
        Wide US releases opening between the two dates, for pencilling
        onto the calendar before any theater is selling tickets.

        Wide only, and above a popularity floor: everything TMDB lists
        as theatrical is several films a day, most of which never
        reach these theaters.
        """

        results = []
        page = 1

        while page <= 20:

            data = self._get("/discover/movie", {
                "region": "US",
                "with_release_type": "3",  # wide theatrical
                "release_date.gte": start.isoformat(),
                "release_date.lte": end.isoformat(),
                "sort_by": "popularity.desc",
                "page": page,
            })

            items = data.get("results", [])

            for item in items:

                # Sorted by popularity, so everything after this is
                # below the floor too.
                if (item.get("popularity") or 0) < min_popularity:
                    break

                us_release = item.get("release_date") or ""

                if not start.isoformat() <= us_release <= end.isoformat():
                    continue

                details = self.movie_details(item["id"])

                # A re-release of an older film.
                first_release = details.get("release_date") or ""

                if first_release and int(first_release[:4]) < start.year - 1:
                    continue

                poster_path = details.get("poster_path")

                results.append({
                    "tmdb_id": item["id"],
                    "imdb_id": details.get("imdb_id") or None,
                    "title": details.get("title") or item.get("title"),
                    "release_date": us_release,
                    "runtime": details.get("runtime") or None,
                    "genres": [g["name"] for g in details.get("genres", [])],
                    "plot": details.get("overview") or None,
                    "poster": (
                        f"https://image.tmdb.org/t/p/w342{poster_path}"
                        if poster_path else None
                    ),
                    "url": f"https://www.themoviedb.org/movie/{item['id']}",
                    "popularity": round(item.get("popularity") or 0, 1),
                })

            else:

                if page < data.get("total_pages", 1):
                    page += 1
                    continue

            break

        results.sort(key=lambda r: (r["release_date"], -r["popularity"]))

        return results

    def predict(self, movie: Movie) -> List[dict]:
        """
        Return up to MAX_CANDIDATES likely films for one mystery
        screening, best fit first.
        """
        if not movie.showtimes or not movie.rating:
            return []

        return self.candidates(
            RATING_ALIASES.get(movie.rating, movie.rating),
            movie.runtime,
            date.fromisoformat(movie.showtimes[0].datetime[:10]),
            "scream" in movie.title.lower(),
        )[:MAX_CANDIDATES]
