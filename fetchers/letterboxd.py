"""
fetchers/letterboxd.py

Letterboxd enrichment for Movie objects.

Letterboxd has no public API. Instead this looks up each movie's
Letterboxd page via its IMDb ID -- `letterboxd.com/imdb/{imdb_id}/`
redirects straight to the matching film page -- and pulls the average
rating out of the page's embedded JSON-LD (`schema.org` AggregateRating).
Results are cached on disk the same way `fetchers/omdb.py` caches OMDb
responses, so repeat runs only look up movies that are new.

Movies without an `imdb_id` (OMDb couldn't find a match) are skipped.
Letterboxd's own search page sits behind bot protection that 403s
scripted requests, so there's no reliable title-based fallback -- this
only works for movies OMDb already resolved an IMDb ID for.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from config import (
    LETTERBOXD_CACHE,
    LETTERBOXD_DELAY,
    REQUEST_TIMEOUT,
    USER_AGENT,
)

from models import Movie


LDJSON_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>',
    re.DOTALL,
)


class LetterboxdFetcher:

    def __init__(self):

        self.cache_path = Path(LETTERBOXD_CACHE)

        self.cache_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if self.cache_path.exists():

            with open(self.cache_path, "r") as f:
                self.cache = json.load(f)

        else:

            self.cache = {}


    # ---------------------------------------------------------

    def save_cache(self):

        with open(self.cache_path, "w") as f:

            json.dump(
                self.cache,
                f,
                indent=2,
            )


    # ---------------------------------------------------------

    def _lookup(self, imdb_id: str) -> dict:
        """
        Fetches the Letterboxd film page reached via the IMDb redirect
        and pulls the rating out of the page's JSON-LD block.

        Returns {} if Letterboxd has no film matching this IMDb ID.
        """

        response = requests.get(
            f"https://letterboxd.com/imdb/{imdb_id}/",
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        response.raise_for_status()

        match = LDJSON_RE.search(response.text)

        if not match:
            return {}

        # Letterboxd wraps the JSON-LD payload in a CDATA comment
        # (`/* <![CDATA[ */ {...} /* ]]> */`) rather than emitting raw
        # JSON, so pull out just the outermost braces before parsing.
        raw = match.group(1)
        start = raw.find("{")
        end = raw.rfind("}")

        if start == -1 or end == -1:
            return {}

        try:
            data = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return {}

        rating = data.get("aggregateRating")

        if not rating:
            return {}

        return {
            "rating": rating.get("ratingValue"),
            "rating_count": rating.get("ratingCount"),
            "url": data.get("url") or response.url,
        }


    # ---------------------------------------------------------

    def get(self, imdb_id: str) -> dict:

        if imdb_id not in self.cache:

            print(f"Letterboxd: {imdb_id}")

            self.cache[imdb_id] = self._lookup(imdb_id)

            self.save_cache()

            time.sleep(LETTERBOXD_DELAY)

        return self.cache[imdb_id]


    # ---------------------------------------------------------

    def enrich_movie(self, movie: Movie):

        if not movie.imdb_id or movie.letterboxd_rating:
            return movie

        data = self.get(movie.imdb_id)

        if data.get("rating") is not None:
            movie.letterboxd_rating = data["rating"]

        if data.get("rating_count") is not None:
            movie.letterboxd_rating_count = data["rating_count"]

        if data.get("url"):
            movie.letterboxd_url = data["url"]

        return movie


    # ---------------------------------------------------------

    def enrich(self, movies):

        for movie in movies:

            self.enrich_movie(movie)

        self.save_cache()

        return movies
