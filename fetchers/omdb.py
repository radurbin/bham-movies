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
import unicodedata
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
ANNIVERSARY_NUMBER_RE = re.compile(
    r"\b(\d+)(?:st|nd|rd|th)\s+anniversary",
    re.IGNORECASE,
)

# The cache is committed by the GitHub Actions workflow so each run only
# asks OMDb about new or expired titles (the free tier allows 1,000
# requests a day). Hits expire so ratings stay reasonably current; misses
# expire sooner so a film OMDb adds later still gets picked up.
CACHE_HIT_TTL = 7 * 24 * 3600
CACHE_MISS_TTL = 2 * 24 * 3600


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

        self.used_keys = set()


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

        self.used_keys.add(key)

        entry = self.cache.get(key)

        if entry is None or self._expired(entry):

            print(f"OMDb: {title}" + (f" ({year})" if year else ""))

            try:

                data = self._lookup(
                    title,
                    year,
                )

            except requests.RequestException as ex:

                # OMDb being down or over its daily limit shouldn't take
                # the whole run with it. Use the expired entry if there
                # is one, and don't cache the failure.
                print(f"OMDb request failed for {title}: {ex}")

                return entry or {"Response": "False"}

            data["_fetched_at"] = time.time()

            self.cache[key] = data

            self.save_cache()

            time.sleep(OMDB_DELAY)


        return self.cache[key]


    # ---------------------------------------------------------

    @staticmethod
    def _expired(entry: dict) -> bool:

        # Entries written before timestamps existed count as expired.
        fetched_at = entry.get("_fetched_at")

        if not fetched_at:
            return True

        ttl = (
            CACHE_MISS_TTL
            if entry.get("Response") == "False"
            else CACHE_HIT_TTL
        )

        return time.time() - fetched_at > ttl


    # ---------------------------------------------------------

    @staticmethod
    def _candidate_years(movie: Movie) -> list:
        """
        (year, trusted) pairs to try, best guess first.

        For AMC movies `release_year` is the year of *this* release, so
        a re-release carries the wrong year for OMDb. "Nth Anniversary"
        in the title gives the original year (give or take one, since
        anniversaries are counted loosely). The final `None` is a
        title-only lookup for re-releases with no such hint.

        A trusted year is accepted unless _same_film() contradicts it;
        the others are guesses and need _same_film() to confirm them.
        """

        candidates = {}

        match = ANNIVERSARY_NUMBER_RE.search(movie.title)

        if match and movie.release_year:

            original = movie.release_year - int(match.group(1))

            candidates[original] = True
            candidates[original - 1] = False
            candidates[original + 1] = False

        candidates.setdefault(movie.release_year, True)
        candidates.setdefault(None, False)

        return list(candidates.items())


    @staticmethod
    def _name_tokens(name: str) -> list:

        ascii_name = (
            unicodedata.normalize("NFKD", name)
            .encode("ascii", "ignore")
            .decode()
        )

        return re.findall(r"[a-z]+", ascii_name.lower())


    def _same_film(self, movie: Movie, data: dict) -> Optional[bool]:
        """
        Does OMDb's record describe the same film as what the source
        (AMC or Sidewalk) told us? True/False when there is something
        to compare, None when there isn't.
        """

        compared_people = False

        # Directors: surname is enough, since sources differ on middle
        # names, initials and name order. Substring rather than equality
        # because AMC mangles accented letters ("I?ARRITU" for Iñárritu).
        omdb_director = data.get("Director") or ""

        if movie.directors and omdb_director not in ("", "N/A"):

            compared_people = True

            omdb_tokens = self._name_tokens(omdb_director)

            for director in movie.directors:

                tokens = self._name_tokens(director)

                surname = tokens[-1] if tokens else ""

                if len(surname) >= 4 and any(
                    surname in token or (len(token) >= 4 and token in surname)
                    for token in omdb_tokens
                ):
                    return True

        # Cast: the sources sometimes credit different directors for
        # the same film, so a shared lead actor also counts.
        omdb_actors = data.get("Actors") or ""

        if movie.actors and omdb_actors not in ("", "N/A"):

            compared_people = True

            omdb_names = {
                " ".join(self._name_tokens(name))
                for name in omdb_actors.split(",")
            }

            for actor in movie.actors:

                if " ".join(self._name_tokens(actor)) in omdb_names:
                    return True

        if compared_people:
            return False

        # No people to compare (AMC often lists none for re-releases):
        # a near-identical running time is the remaining evidence. A
        # different one proves nothing -- AMC's running times for
        # upcoming films are often provisional.
        match = re.match(r"(\d+) min", data.get("Runtime") or "")

        if movie.runtime and match:

            if abs(movie.runtime - int(match.group(1))) <= 3:
                return True

        return None


    def find_match(self, movie: Movie) -> Optional[dict]:
        """
        Return OMDb's record for this movie, or None if nothing
        trustworthy was found.
        """

        lookup_title = clean_title_for_lookup(movie.title)

        for year, trusted_year in self._candidate_years(movie):

            data = self.get(
                lookup_title,
                year,
            )

            if data.get("Response") == "False":
                continue

            agree = self._same_film(movie, data)

            if agree is True or (agree is None and trusted_year):
                return data

            print(
                f"OMDb: rejected '{data.get('Title')}' ({data.get('Year')}) "
                f"for '{movie.title}'"
            )

        return None


    # ---------------------------------------------------------

    def enrich_movie(
        self,
        movie: Movie,
    ):

        data = self.find_match(movie)

        if data is None:

            return movie


        #
        # Fill only missing fields.
        #

        poster = data.get("Poster")

        if poster and poster != "N/A":

            movie.fallback_poster = poster

            if not movie.poster:

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

                if actor.strip() and actor.strip() != "N/A"

            ]


        if not movie.directors:

            directors = data.get(
                "Director",
                "",
            )

            movie.directors = [

                director.strip()

                for director in directors.split(",")

                if director.strip() and director.strip() != "N/A"

            ]


        if not movie.writers:

            writers = data.get(
                "Writer",
                "",
            )

            movie.writers = [

                writer.strip()

                for writer in writers.split(",")

                if writer.strip() and writer.strip() != "N/A"

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

        # Drop entries for titles that are no longer showing, so the
        # committed cache doesn't grow forever.
        self.cache = {
            key: value
            for key, value in self.cache.items()
            if key in self.used_keys
        }

        self.save_cache()

        return movies