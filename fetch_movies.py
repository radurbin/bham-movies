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

from zoneinfo import ZoneInfo


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
        print("Fetching Sidewalk showtimes (scraped)")
        print("=" * 60)

        try:
            sidewalk = SidewalkFetcher()
            sidewalk_movies = sidewalk.fetch_movies()
        except Exception as ex:
            # Sidewalk's site (and whatever's in front of it, e.g.
            # Cloudflare) is out of our control. Don't let it take down
            # the whole run -- AMC's data is still worth writing.
            print(f"Sidewalk fetch failed, continuing without it: {ex}")
            sidewalk_movies = []

        print(f"Fetched {len(sidewalk_movies)} movies from Sidewalk.")

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

            "generated_at": datetime.now(ZoneInfo("America/Chicago")).isoformat(),

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

    def build_changelog_entry(self):
        """
        Compare the previous movies.json against the new data and
        build a summary of added/removed movies and showtimes.
        """

        old_movies = {}

        if MOVIES_JSON.exists():
            try:
                with open(MOVIES_JSON, "r", encoding="utf-8") as f:
                    old_payload = json.load(f)
                for m in old_payload.get("movies", []):
                    key = f"{m.get('title')}::{m.get('release_year')}"
                    old_movies[key] = m
            except Exception as ex:
                print("Failed to read previous movies.json:", ex)

        new_movies = {}
        for movie in self.movies:
            key = f"{movie.title}::{movie.release_year}"
            new_movies[key] = movie.to_dict()

        old_keys = set(old_movies.keys())
        new_keys = set(new_movies.keys())

        added_movies = sorted(new_keys - old_keys)
        removed_movies = sorted(old_keys - new_keys)

        def showtime_set(movie_dict):
            s = set()
            for st in movie_dict.get("showtimes", []):
                s.add((
                    st.get("theater"),
                    st.get("datetime"),
                    st.get("premium_format"),
                ))
            return s

        showtime_changes = []

        for key in old_keys & new_keys:
            old_st = showtime_set(old_movies[key])
            new_st = showtime_set(new_movies[key])

            added = new_st - old_st
            removed = old_st - new_st

            if added or removed:
                title = new_movies[key].get("title")
                showtime_changes.append({
                    "title": title,
                    "added": [
                        {"theater": t, "datetime": d, "format": f}
                        for (t, d, f) in sorted(added, key=lambda x: (x[1] or ""))
                    ],
                    "removed": [
                        {"theater": t, "datetime": d, "format": f}
                        for (t, d, f) in sorted(removed, key=lambda x: (x[1] or ""))
                    ],
                })

        entry = {
            "date": datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %I:%M %p %Z"),
            "movies_added": [new_movies[k]["title"] for k in added_movies],
            "movies_removed": [old_movies[k]["title"] for k in removed_movies],
            "showtime_changes": showtime_changes,
        }

        return entry

    # ---------------------------------------------------------

    def write_changelog(self, entry: dict):
        """
        Append the changelog entry to a running JSON log and a
        human-readable markdown log.
        """

        print()
        print("=" * 60)
        print("Writing changelog")
        print("=" * 60)

        changelog_json_path = DOCS_DIR / "changelog.json"
        changelog_md_path = DOCS_DIR / "CHANGELOG.md"

        # --- JSON log (structured, easy to consume from the frontend) ---
        history = []
        if changelog_json_path.exists():
            try:
                with open(changelog_json_path, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []

        history.append(entry)

        # Keep the last 90 days of entries to prevent unbounded growth
        history = history[-90:]

        with open(changelog_json_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

        # --- Markdown log (human readable) ---
        lines = [f"## {entry['date']}", ""]

        if entry["movies_added"]:
            lines.append("**Movies added:**")
            for title in entry["movies_added"]:
                lines.append(f"- {title}")
            lines.append("")

        if entry["movies_removed"]:
            lines.append("**Movies removed:**")
            for title in entry["movies_removed"]:
                lines.append(f"- {title}")
            lines.append("")

        if entry["showtime_changes"]:
            lines.append("**Showtime changes:**")
            for change in entry["showtime_changes"]:
                lines.append(f"- {change['title']}")
                for st in change["added"]:
                    lines.append(f"  - + {st['theater']} @ {st['datetime']} ({st['format']})")
                for st in change["removed"]:
                    lines.append(f"  - − {st['theater']} @ {st['datetime']} ({st['format']})")
            lines.append("")

        if not (entry["movies_added"] or entry["movies_removed"] or entry["showtime_changes"]):
            lines.append("No changes.")
            lines.append("")

        new_section = "\n".join(lines) + "\n"

        existing_md = ""
        if changelog_md_path.exists():
            existing_md = changelog_md_path.read_text(encoding="utf-8")

        with open(changelog_md_path, "w", encoding="utf-8") as f:
            f.write(new_section + existing_md)

        print(f"Wrote {changelog_json_path}")
        print(f"Wrote {changelog_md_path}")

    def build(self):

        self.fetch_movies()

        self.enrich_movies()

        self.download_posters()

        self.sort_movies()

        self.validate()

        changelog_entry = self.build_changelog_entry()

        self.write_json()

        self.write_changelog(changelog_entry)

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