"""
fetchers/omdb.py

OMDb enrichment for Movie objects.

Looks up additional movie metadata from OMDb and merges it into the
Movie dataclasses created by the AMC fetcher.

Automatically caches results on disk.
"""

from __future__ import annotations

import json
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

        data = self.get(
            movie.title,
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
        # Cast
        #

        actors = data.get(
            "Actors",
            "",
        )

        movie.actors = [

            actor.strip()

            for actor in actors.split(",")

            if actor.strip()

        ]


        directors = data.get(
            "Director",
            "",
        )

        movie.directors = [

            director.strip()

            for director in directors.split(",")

            if director.strip()

        ]


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

        movie.imdb_id = data.get(
            "imdbID"
        )

        movie.imdb_rating = data.get(
            "imdbRating"
        )

        movie.imdb_votes = data.get(
            "imdbVotes"
        )

        movie.awards = data.get(
            "Awards"
        )

        movie.language = data.get(
            "Language"
        )

        movie.country = data.get(
            "Country"
        )

        movie.box_office = data.get(
            "BoxOffice"
        )


        for rating in data.get(
            "Ratings",
            [],
        ):

            if rating["Source"] == "Rotten Tomatoes":

                movie.rotten_tomatoes = rating["Value"]

            elif rating["Source"] == "Metacritic":

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