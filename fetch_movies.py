#!/usr/bin/env python3
"""
fetch_movies.py

Builds the movies.json file used by the website.

Pipeline

AMC API
        ↓
Normalize
        ↓
OMDb enrichment
        ↓
Download poster images
        ↓
Generate statistics
        ↓
Write docs/movies.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from config import (
    DOCS_DIR,
    MOVIES_JSON,
)

from fetchers.amc import AMCFetcher
from fetchers.omdb import OMDbFetcher
from fetchers.sidewalk import SidewalkFetcher

from models import Movie


POSTERS_DIR = DOCS_DIR / "posters"


class MoviePipeline:
    """
    Coordinates the entire build process.
    """

    def __init__(self):

        self.movies: list[Movie] = []

        self.poster_dir = POSTERS_DIR

        self.poster_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    # ---------------------------------------------------------

    def fetch_movies(self):

        print("=" * 60)
        print("Fetching AMC showtimes")
        print("=" * 60)

        amc = AMCFetcher()

        self.movies = amc.fetch_movies()

        print()

        print(f"Fetched {len(self.movies)} unique movies from AMC.")

        # Fetch Sidewalk movies and merge them in
        print()
        print("=" * 60)
        print("Fetching Sidewalk showtimes (TMS)")
        print("=" * 60)

        sidewalk = SidewalkFetcher()

        sidewalk_movies = sidewalk.fetch_movies()

        print(f"Fetched {len(sidewalk_movies)} movies from Sidewalk/TMS.")

        # Merge sidewalk movies into AMC movies using a smarter
        # normalized-title matching strategy (ignores articles,
        # punctuation, and accepts substring matches when years
        # are compatible).

        def normalize_title(t: str) -> str:
            if not t:
                return ""
            s = t.lower().strip()
            for p in ("the ", "a ", "an "):
                if s.startswith(p):
                    s = s[len(p):]
                    break
            s = re.sub(r"[^a-z0-9\s]", "", s)
            s = " ".join(s.split())
            return s

        title_map: dict[str, list[Movie]] = {}

        for m in self.movies:
            n = normalize_title(m.title)
            title_map.setdefault(n, []).append(m)

        added = 0

        for sm in sidewalk_movies:
            ns = normalize_title(sm.title)

            merged = False

            # direct normalized-title candidates
            candidates = title_map.get(ns, [])

            for existing in candidates:
                year_ok = (
                    existing.release_year == sm.release_year
                    or existing.release_year is None
                    or sm.release_year is None
                )
                if year_ok:
                    # merge
                    for st in sm.showtimes:
                        existing.add_showtime(st)
                    if not existing.poster and sm.poster:
                        existing.poster = sm.poster
                    if not existing.runtime and sm.runtime:
                        existing.runtime = sm.runtime
                    if not existing.rating and getattr(sm, "rating", None):
                        existing.rating = sm.rating
                    merged = True
                    break

            if merged:
                continue

            # try substring matches across known normalized titles
            for k, lst in list(title_map.items()):
                if not k or not ns:
                    continue
                if ns in k or k in ns:
                    for existing in lst:
                        year_ok = (
                            existing.release_year == sm.release_year
                            or existing.release_year is None
                            or sm.release_year is None
                        )
                        if year_ok:
                            for st in sm.showtimes:
                                existing.add_showtime(st)
                            if not existing.poster and sm.poster:
                                existing.poster = sm.poster
                            if not existing.runtime and sm.runtime:
                                existing.runtime = sm.runtime
                            if not existing.rating and getattr(sm, "rating", None):
                                existing.rating = sm.rating
                            merged = True
                            break
                if merged:
                    break

            if merged:
                continue

            # no match found; add as new movie
            self.movies.append(sm)
            title_map.setdefault(ns, []).append(sm)
            added += 1

        print(f"Merged Sidewalk movies: {added} new movies added.")

    # ---------------------------------------------------------

    def enrich_movies(self):

        print()

        print("=" * 60)
        print("Enriching with OMDb")
        print("=" * 60)

        omdb = OMDbFetcher()

        self.movies = omdb.enrich(
            self.movies
        )

        print()

        print("Finished OMDb enrichment.")

    # ---------------------------------------------------------

    def fetch_watchlist(self):
        """Fetch full watchlist from Letterboxd with pagination."""
        import os
        
        print()
        print("=" * 60)
        print("Fetching Letterboxd watchlist")
        print("=" * 60)
        
        username = os.getenv("LETTERBOXD_USERNAME")
        if not username:
            print("LETTERBOXD_USERNAME not set, skipping watchlist")
            return set()
        
        watchlist = []
        page = 1
        
        try:
            from bs4 import BeautifulSoup
            
            while True:
                url = f"https://letterboxd.com/{username}/watchlist/page/{page}/"
                headers = {"User-Agent": "Mozilla/5.0"}
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'html.parser')
                films = soup.find_all('div', class_='film-poster')
                
                if not films:
                    break
                
                for film in films:
                    img = film.find('img')
                    if img and img.get('alt'):
                        watchlist.append(img['alt'].lower())
                
                print(f"Page {page}: {len(films)} movies (total: {len(watchlist)})")
                page += 1
            
            print(f"Found {len(watchlist)} total movies in watchlist")
            return set(watchlist)
        
        except Exception as ex:
            print(f"Failed to fetch watchlist: {ex}")
            return set()

    # ---------------------------------------------------------

    @staticmethod
    def slugify(title: str):

        chars = []

        for c in title.lower():

            if c.isalnum():

                chars.append(c)

            elif c in " -_":

                chars.append("-")

        slug = "".join(chars)

        while "--" in slug:

            slug = slug.replace(
                "--",
                "-",
            )

        return slug.strip("-")

    # ---------------------------------------------------------

    def poster_filename(
        self,
        movie: Movie,
    ):

        if movie.release_year:

            return (
                self.slugify(movie.title)
                + "-"
                + str(movie.release_year)
                + ".jpg"
            )

        return (
            self.slugify(movie.title)
            + ".jpg"
        )

    # ---------------------------------------------------------

    def clean_posters(self):

        """
        Remove old posters.

        This prevents stale artwork from
        accumulating over time.
        """

        print()

        print("=" * 60)
        print("Cleaning poster cache")
        print("=" * 60)

        if not self.poster_dir.exists():

            return

        count = 0

        for file in self.poster_dir.glob("*"):

            if file.is_file():

                file.unlink()

                count += 1

        print(
            f"Removed {count} cached posters."
        )

    # ---------------------------------------------------------

    def download_poster(
        self,
        movie: Movie,
    ):

        """
        Downloads one poster.
        """

        if not movie.poster:

            return

        filename = self.poster_filename(
            movie
        )

        destination = (
            self.poster_dir / filename
        )

        try:

            response = requests.get(
                movie.poster,
                timeout=30,
            )

            response.raise_for_status()

            with open(
                destination,
                "wb",
            ) as f:

                f.write(
                    response.content
                )

            #
            # Replace remote URL with local path.
            #

            movie.poster = (
                "posters/" + filename
            )

        except Exception as ex:

            print(
                "Poster download failed:",
                movie.title,
                ex,
            )

    # ---------------------------------------------------------

    def download_posters(self):

        print()

        print("=" * 60)
        print("Downloading Posters")
        print("=" * 60)

        total = len(self.movies)

        for index, movie in enumerate(self.movies, start=1):

            filename = self.poster_filename(movie)

            destination = self.poster_dir / filename

            # If we've already downloaded this poster, skip re-downloading.
            if destination.exists():
                print(f"[{index}/{total}] {movie.title} - poster exists, skipping")
                # Ensure movie.poster points to the local path
                movie.poster = "posters/" + filename
                continue

            print(f"[{index}/{total}] {movie.title}")

            self.download_poster(movie)

    # ---------------------------------------------------------

    def sort_movies(self):

        self.movies.sort(
            key=lambda movie:
            movie.title.lower()
        )

        for movie in self.movies:

            movie.sort_showtimes()

        # ---------------------------------------------------------

    def statistics(self):
        """
        Build summary statistics for movies.json.
        """

        showtime_count = 0
        theater_counter = Counter()

        for movie in self.movies:

            showtime_count += len(movie.showtimes)

            for show in movie.showtimes:

                theater_counter[show.theater] += 1

        return {

            "generated_at": datetime.now().isoformat(),

            "movie_count": len(self.movies),

            "showtime_count": showtime_count,

            "theaters": dict(theater_counter),

        }

    # ---------------------------------------------------------

    def validate(self):
        """
        Basic validation before writing JSON.
        """

        titles = set()

        duplicates = []

        for movie in self.movies:

            title = movie.title.lower()

            if title in titles:

                duplicates.append(movie.title)

            titles.add(title)

        if duplicates:

            print()

            print("Duplicate movie titles detected:")

            for title in duplicates:

                print("   ", title)

        print()

        print(f"Validated {len(self.movies)} movies.")

    # ---------------------------------------------------------

    def build_json(self):

        return {

            "metadata": self.statistics(),

            "movies": [

                movie.to_dict()

                for movie in self.movies

            ]

        }

    # ---------------------------------------------------------

    def write_json(self):

        payload = self.build_json()

        print()

        print("=" * 60)
        print("Writing JSON")
        print("=" * 60)

        with open(
            MOVIES_JSON,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                payload,
                f,
                indent=2,
                ensure_ascii=False,
            )

        size = MOVIES_JSON.stat().st_size / 1024

        print()

        print(f"Wrote {MOVIES_JSON}")

        print(f"{size:.1f} KB")

        # Remove any poster files that are no longer referenced
        try:
            self.remove_stale_posters(payload)
        except Exception as ex:
            print("Failed to remove stale posters:", ex)

    # ---------------------------------------------------------

    def remove_stale_posters(self, payload: dict):
        """
        Remove poster image files in the poster directory that are not
        referenced by the newly generated `movies.json` payload.

        This prevents the poster cache from growing indefinitely when
        movies are removed from the source data.
        """

        referenced = set()

        for movie in payload.get("movies", []):
            poster = movie.get("poster")

            if not poster:
                continue

            # Expect posters to be stored as a relative path like 'posters/foo.jpg'
            if isinstance(poster, str) and poster.startswith("posters/"):
                referenced.add(poster.split("/", 1)[1])

        if not self.poster_dir.exists():
            return

        removed = 0

        for file in self.poster_dir.iterdir():
            if not file.is_file():
                continue

            if file.name not in referenced:
                try:
                    file.unlink()
                    removed += 1
                except Exception:
                    # ignore failures to remove individual files
                    pass

        print(f"Removed {removed} stale poster(s).")

    def mark_watchlist_movies(self, watchlist: set):
        """Mark movies that are in the watchlist."""
        for movie in self.movies:
            movie.on_watchlist = movie.title.lower() in watchlist

    def build(self):
        self.fetch_movies()
        watchlist = self.fetch_watchlist()
        self.enrich_movies()
        self.mark_watchlist_movies(watchlist)
        self.download_posters()
        self.sort_movies()
        self.validate()
        self.write_json()

# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Generate docs/movies.json"
    )

    parser.parse_args()

    pipeline = MoviePipeline()

    pipeline.build()

    print()

    print("=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()