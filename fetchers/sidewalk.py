"""
fetchers/sidewalk.py

Reads showtimes for Sidewalk Film Center + Cinema from their own
schedule page (www.sidewalkfest.com/cinema/now-playing).

Sidewalk isn't in TMS/Gracenote's theatre database at all, so their own
site is the only source.

Since Nov 4, 2026 the site is a Next.js app built by Elevent, Sidewalk's
ticketing vendor (it replaced the WordPress site this fetcher used to
scrape). The schedule page embeds the full schedule as JSON for the
page's own JavaScript: an "initialShowtimes" array, every upcoming
showtime (about six weeks) with its film's details, in a single page.
This fetcher pulls that array out of the page rather than reading the
HTML layout, so a visual redesign shouldn't break it.

The page is fetched directly (config.SIDEWALK_CINEMA_URL). The Cloudflare
Worker that used to stand in between still works as a fallback; see the
README.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

from config import (
    REQUEST_TIMEOUT,
    SIDEWALK_CINEMA_URL,
    SIDEWALK_SCREEN_WIDTH_FT,
    SIDEWALK_SITE,
    SIDEWALK_STALE_HOURS,
)

from models import Movie, Showtime

# Next.js streams the page's data as JavaScript string literals:
#   self.__next_f.push([1,"..."])
NEXT_DATA_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)\s*</script>', re.S)

SHOWTIMES_KEY = '"initialShowtimes":'

# Both auditoriums are listed under this venue. Lobby, classroom and
# online events (trivia, karaoke, meetings) have other venue names.
CINEMA_VENUE = "Sidewalk Film Center + Cinema"

LOCAL_TZ = ZoneInfo("America/Chicago")

# What the Nov 9, 2026 test from a GitHub runner sent (and got through with).
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_showtimes(html: str) -> Optional[List[dict]]:
    """The page's "initialShowtimes" array, or None if it isn't there."""

    # Each chunk is a JSON-compatible string literal; joined, they form
    # the page's data stream.
    stream = "".join(json.loads(f'"{chunk}"') for chunk in NEXT_DATA_RE.findall(html))

    start = stream.find(SHOWTIMES_KEY)
    if start < 0:
        return None

    showtimes, _ = json.JSONDecoder().raw_decode(stream, start + len(SHOWTIMES_KEY))
    return showtimes


def _date(value: Optional[str]) -> Optional[datetime]:
    """Next.js marks dates as "$D2026-11-11T20:00:00.000Z" (UTC)."""
    if not value:
        return None
    return datetime.fromisoformat(value.removeprefix("$D").replace("Z", "+00:00"))


def _names(value: Optional[str]) -> List[str]:
    return [n.strip() for n in (value or "").split(",") if n.strip()]


def _poster(event: dict) -> Optional[str]:
    poster = event.get("posterImageUrl")
    if poster:
        # Sidewalk links TMDB's full-size original; a 500px-wide copy is
        # plenty (fetch_movies.py resizes posters to 440px anyway).
        return poster.replace("/t/p/original/", "/t/p/w500/")
    # Some events only have a wide banner image.
    return event.get("imageUrl")


class SidewalkFetcher:

    # --------------------------------------------------
    # HTTP helper
    # --------------------------------------------------

    def _fetch_page(self) -> str:
        response = requests.get(
            SIDEWALK_CINEMA_URL,
            headers=BROWSER_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        # Only when reading through the Worker, which serves a stored
        # copy: say how old it is, since a copy that stops refreshing
        # would otherwise look like Sidewalk simply not adding showtimes.
        fetched_at = response.headers.get("X-Fetched-At")
        if fetched_at:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(
                fetched_at.replace("Z", "+00:00")
            )
            hours = age.total_seconds() / 3600
            print(f"  Stored copy fetched {fetched_at} ({hours:.1f}h ago)")
            if hours > SIDEWALK_STALE_HOURS:
                print(f"  WARNING: stored Sidewalk copy is over {SIDEWALK_STALE_HOURS}h old -- check the Worker's /status")

        return response.text

    # --------------------------------------------------
    # Public method
    # --------------------------------------------------

    def fetch_movies(self) -> List[Movie]:
        """
        Read Sidewalk's schedule and return normalized movies.
        """

        print("  Fetching Sidewalk schedule...")

        showtimes = extract_showtimes(self._fetch_page())

        if showtimes is None:
            raise ValueError(
                "Sidewalk's schedule page has no initialShowtimes data -- "
                "the site may have changed again"
            )

        movies: Dict[str, Movie] = {}

        for show in showtimes:

            venue = (show.get("venue") or {}).get("name") or ""
            event = show.get("event") or {}
            start = _date(show.get("startDateTime"))

            if venue != CINEMA_VENUE or not event.get("name") or not start:
                continue

            if show.get("status") != "Active" or event.get("status") != "Active":
                continue

            event_url = (
                f"{SIDEWALK_SITE}/events/{event['urlName']}"
                if event.get("urlName") else f"{SIDEWALK_SITE}/cinema/now-playing"
            )

            movie = movies.get(event["id"])

            if movie is None:
                year = event.get("releaseYear")
                movie = movies[event["id"]] = Movie(
                    source="Sidewalk",
                    title=event["name"].strip(),
                    release_year=int(year) if year and str(year).isdigit() else None,
                    runtime=event.get("lengthInMinutes") or show.get("lengthInMinutes"),
                    rating=event.get("rating") or None,
                    poster=_poster(event),
                    directors=_names(event.get("director")),
                    actors=_names(event.get("cast")),
                    writers=_names(event.get("writer")),
                    plot=event.get("description") or None,
                    trailer_url=event.get("trailerUrl") or None,
                    movie_url=event_url,
                )

            sold_out = max(
                show.get("capacitySoldOutPercentage") or 0,
                show.get("publicAllocationSoldOutPercentage") or 0,
            ) >= 100

            movie.add_showtime(Showtime(
                source="Sidewalk",
                theater_id=0,
                theater=venue,
                showtime_id=show.get("eleventId") or show.get("id") or 0,
                datetime=start.astimezone(LOCAL_TZ).strftime("%Y-%m-%dT%H:%M:%S"),
                datetime_utc=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                purchase_url=event_url,
                sold_out=sold_out,
                screen_width_ft=SIDEWALK_SCREEN_WIDTH_FT,
            ))

        print(
            f"  Found {len(movies)} Sidewalk films with "
            f"{sum(len(m.showtimes) for m in movies.values())} showtimes."
        )

        return list(movies.values())
