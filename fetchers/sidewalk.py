"""
fetchers/sidewalk.py

Fetch showtimes for Sidewalk Film Center + Cinema using the TMS API
and normalize them into the project's `Movie` / `Showtime` models.

This mirrors the client-side approach used in `index-v4.html` which
requests `GET /movies/showings` from the TMS API and filters results
by theatre name.
"""
from __future__ import annotations

from typing import List
import requests
from datetime import date

from config import (
    TMS_BASE_URL,
    REQUEST_TIMEOUT,
    get_tms_key,
    SIDEWALK_THEATER,
)

from models import Movie, Showtime


class SidewalkFetcher:
    """Fetch and normalize Sidewalk showtimes from the TMS API."""

    def __init__(self):
        # Will raise if TMS_API_KEY is not set
        self.api_key = get_tms_key()

    def _get(self, endpoint: str, params=None):
        response = requests.get(
            f"{TMS_BASE_URL.rstrip('/')}{endpoint}",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    def fetch_movies(self, zip_code: str = "35222", radius: int = 20, num_days: int = 30) -> List[Movie]:
        """Fetch movies/showings from TMS and return normalized Movie objects for Sidewalk only.

        Parameters are conservative defaults; they can be overridden by the caller.
        """

        # Set startDate to today to match the frontend behavior
        params = {
            "api_key": self.api_key,
            "zip": zip_code,
            "radius": radius,
            "startDate": date.today().isoformat(),
            "numDays": num_days,
        }

        data = self._get("/movies/showings", params=params)

        movies: List[Movie] = []

        for mv in data:
            title = mv.get("title") or mv.get("name")
            if not title:
                continue

            # Determine poster if present in the TMS payload
            poster = None
            # Common TMS keys: 'poster', 'posterImage', 'image' — try a few
            for key in ("poster", "posterImage", "image", "thumbnail"):
                v = mv.get(key)
                if v:
                    poster = v
                    break

            # Collect only the showtimes that belong to Sidewalk Film Center
            sidewalk_shows = []

            for s in mv.get("showtimes", []) or []:
                theatre = s.get("theatre") or s.get("theatreName") or {}
                theatre_name = theatre.get("name") if isinstance(theatre, dict) else theatre or ""

                # Only include shows that mention Sidewalk Film Center in the theatre name
                if SIDEWALK_THEATER.get("name").lower() not in str(theatre_name).lower():
                    continue

                # attempt to find a unique id for the showtime
                show_id = s.get("id") or s.get("showId") or s.get("showID")

                dt = s.get("dateTime") or s.get("date") or s.get("dateTimeLocal")
                dt_utc = s.get("dateTimeUTC") or s.get("dateTimeUtc") or s.get("dateTimeUtc")

                purchase = s.get("ticketURI") or s.get("ticketURL") or s.get("purchaseUrl")

                show = Showtime(
                    source="Sidewalk",
                    theater_id=0,
                    theater=theatre_name or SIDEWALK_THEATER.get("name"),
                    showtime_id=show_id or 0,
                    datetime=dt,
                    datetime_utc=dt_utc,
                    auditorium=None,
                    premium_format="Standard",
                    purchase_url=purchase,
                )

                sidewalk_shows.append(show)

            # Only create a Movie if there are Sidewalk showtimes for it
            if sidewalk_shows:
                movie = Movie(
                    source="Sidewalk",
                    title=title,
                    release_year=mv.get("releaseYear"),
                    runtime=mv.get("runTime") or mv.get("runtime"),
                    poster=poster,
                )

                for show in sidewalk_shows:
                    movie.add_showtime(show)

                movies.append(movie)

        return movies
