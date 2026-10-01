#!/usr/bin/env python3
"""
tools/backtest_unseen.py

Replays every past mystery screening in data/screen_unseen_history.csv
through the prediction rules in fetchers/tmdb.py and reports how often
the real film would have been the first pick, in the top three, and on
the six-film shortlist.

Run from the repo root with TMDB_API_KEY set:

    python tools/backtest_unseen.py

Two things to keep in mind when reading the result: the rules were
tuned on this same history, so it flatters them a little; and TMDB's
popularity figures are today's, not what they were before each film
opened (popularity is only a tie-breaker, so that matters little).
"""

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fetchers.tmdb import MAX_CANDIDATES, TMDBFetcher  # noqa: E402


def find_film(tmdb: TMDBFetcher, title: str, screening: date):
    """TMDB id of the film a history row names, or None."""
    results = tmdb._get("/search/movie", {"query": title, "region": "US"})["results"]
    near = [
        r for r in results
        if r.get("release_date")
        and -45 <= (date.fromisoformat(r["release_date"]) - screening).days <= 60
    ]
    return max(near, key=lambda r: r["vote_count"])["id"] if near else None


def main():
    tmdb = TMDBFetcher()
    if not tmdb.enabled:
        sys.exit("TMDB_API_KEY is not set.")

    with open(ROOT / "data" / "screen_unseen_history.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    ranks = []

    for row in rows:
        screening = date.fromisoformat(row["date"])
        actual = find_film(tmdb, row["title"], screening)

        ids = [
            c["tmdb_id"]
            for c in tmdb.candidates(
                row["rating"],
                int(row["listed_runtime"]),
                screening,
                row["scream"] == "1",
            )
        ]

        rank = ids.index(actual) + 1 if actual in ids else None
        ranks.append(rank)

        if rank is None or rank > 3:
            print(f"  {row['date']}  {row['title']}: " + (f"rank {rank}" if rank else "not listed"))

    total = len(ranks)
    print()
    print(f"Screenings:      {total}")
    print(f"First pick:      {sum(1 for r in ranks if r == 1)}")
    print(f"Top three:       {sum(1 for r in ranks if r and r <= 3)}")
    print(f"On shortlist:    {sum(1 for r in ranks if r and r <= MAX_CANDIDATES)}")


if __name__ == "__main__":
    main()
