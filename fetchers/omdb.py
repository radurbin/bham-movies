"""
fetchers/omdb.py

OMDb enrichment for Movie objects.

Looks up additional movie metadata from OMDb and merges it into the
Movie dataclasses created by the AMC fetcher.

Automatically caches results on disk.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import requests

from config import (
    OMDB_BASE_URL,
    OMDB_CACHE,
    OMDB_DELAY,
    REQUEST_TIMEOUT,
    get_omdb_key,
)

from models import Movie


# AMC lists many re-releases and special screenings with event/marketing
# text tacked onto the real title -- "Point Break 35th Anniversary",
# "Princess Mononoke - Studio Ghibli Fest 2026", "The Hunger Games (2026)"
# (a 2026 re-screening of the 2012 film). OMDb's `t=` lookup needs an exact
# title match, so these suffixes make roughly a third of AMC's catalog
# silently fail enrichment (confirmed against a live run: 22 of 77 movies).
# Strip the suffix for the OMDb query only -- movie.title keeps the
# original AMC text for display.
ANNIVERSARY_SUFFIX_RE = re.compile(
    r"\s*[:\-–]?\s*\(?\d+(?:st|nd|rd|th)\s+anniversary\)?.*$",
    re.IGNORECASE,
)
EVENT_SUFFIX_RE = re.compile(
    r"\s*[:\-–(]?\s*(?:"
    r"early access"
    r"|fan event"
    r"|fan faves?"
    r"|sensory friendly screening"
    r"|real ?d ?3d fan event"
    r"|bonus performance"
    r"|studio ghibli fest\s*\d{4}"
    r"|\d{4}\s+event\)?"
    r")\)?\s*$",
    re.IGNORECASE,
)
YEAR_SUFFIX_RE = re.compile(r"\s*\(\d{4}\)\s*$")


def clean_title_for_lookup(title: str) -> str:
    cleaned = title
    cleaned = ANNIVERSARY_SUFFIX_RE.sub("", cleaned)
    cleaned = EVENT_SUFFIX_RE.sub("", cleaned)
    cleaned = YEAR_SUFFIX_RE.sub("", cleaned)
    cleaned = cleaned.strip(" :-–()")
    return cleaned or title


class OMDbFetcher:

    def __init__(self):

        self.api_key = get_omdb_key()

        self.cache_path = Path(OMDB_CACHE)

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

    def _cache_key(
        self,
        title: str,
        year: Optional[int],
    ) -> str:

        if year:

            return f"{title.lower()} ({year})"

        return title.lower()


    # ---------------------------------------------------------

    def _lookup(
        self,
        title,
        year=None,
    ):

        params = {
            "apikey": self.api_key,
            "t": title,
        }

        #
        # Only include year if known
        #

        if year:

            params["y"] = year


        response = requests.get(

            OMDB_BASE_URL,

            params=params,

            timeout=REQUEST_TIMEOUT,

        )

        response.raise_for_status()

        return response.json()


    # ---------------------------------------------------------

    def get(
        self,
        title,
        year=None,
    ):

        key = self._cache_key(
            title,
            year,
        )

        if key not in self.cache:

            print(f"OMDb: {title}")

            self.cache[key] = self._lookup(
                title,
                year,
            )

            self.save_cache()

            time.sleep(OMDB_DELAY)


        return self.cache[key]


    # ---------------------------------------------------------

    def enrich_movie(
        self,
        movie: Movie,
    ):

        lookup_title = clean_title_for_lookup(movie.title)

        data = self.get(
            lookup_title,
            movie.release_year,
        )

        if data.get("Response") == "False":

            return movie


        #
        # Fill only missing fields.
        #

        if not movie.poster:

            poster = data.get("Poster")

            if poster and poster != "N/A":

                movie.poster = poster


        if not movie.plot:

            plot = data.get("Plot")

            if plot != "N/A":

                movie.plot = plot


        if not movie.runtime:

            runtime = data.get("Runtime")

            if runtime and runtime.endswith(" min"):

                movie.runtime = int(
                    runtime.replace(
                        " min",
                        "",
                    )
                )


        if not movie.rating:

            rating = data.get("Rated")

            if rating != "N/A":

                movie.rating = rating


        #
        # Genres
        #

        if not movie.genres:

            genres = data.get(
                "Genre",
                "",
            )

            movie.genres = [

                g.strip()

                for g in genres.split(",")

                if g.strip()

            ]


        #
        # Cast -- fill only missing fields so a source that already
        # supplied real data (e.g. Sidewalk's scraped director/country)
        # isn't silently overwritten by an OMDb entry that may not even
        # match the right movie.
        #

        if not movie.actors:

            actors = data.get(
                "Actors",
                "",
            )

            movie.actors = [

                actor.strip()

                for actor in actors.split(",")

                if actor.strip()

            ]


        if not movie.directors:

            directors = data.get(
                "Director",
                "",
            )

            movie.directors = [

                director.strip()

                for director in directors.split(",")

                if director.strip()

            ]


        if not movie.writers:

            writers = data.get(
                "Writer",
                "",
            )

            movie.writers = [

                writer.strip()

                for writer in writers.split(",")

                if writer.strip()

            ]


        #
        # Ratings
        #

        if not movie.imdb_id:
            movie.imdb_id = data.get(
                "imdbID"
            )

        if not movie.imdb_rating:
            movie.imdb_rating = data.get(
                "imdbRating"
            )

        if not movie.imdb_votes:
            movie.imdb_votes = data.get(
                "imdbVotes"
            )

        if not movie.awards:
            movie.awards = data.get(
                "Awards"
            )

        if not movie.language:
            movie.language = data.get(
                "Language"
            )

        if not movie.country:
            movie.country = data.get(
                "Country"
            )

        if not movie.box_office:
            movie.box_office = data.get(
                "BoxOffice"
            )


        for rating in data.get(
            "Ratings",
            [],
        ):

            if rating["Source"] == "Rotten Tomatoes" and not movie.rotten_tomatoes:

                movie.rotten_tomatoes = rating["Value"]

            elif rating["Source"] == "Metacritic" and not movie.metacritic:

                movie.metacritic = rating["Value"]


        #
        # Release year
        #

        if not movie.release_year:

            try:

                movie.release_year = int(
                    data.get(
                        "Year",
                        "0",
                    )[:4]
                )

            except:

                pass


        return movie


    # ---------------------------------------------------------

    def enrich(
        self,
        movies,
    ):

        for movie in movies:

            self.enrich_movie(
                movie
            )

        self.save_cache()

        return movies