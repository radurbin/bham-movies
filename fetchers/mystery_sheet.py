"""
fetchers/mystery_sheet.py

Reads Regal's listed running time for each Monday mystery screening from
a community Google Sheet that tracks AMC, Regal, Cinemark and Marcus
mystery movies side by side (MYSTERY_SHEET_CSV_URL in config.py).

Regal shows the same film as AMC on the same Monday, but pads the
running time differently (about +8 minutes, against AMC's +4), and the
two chains' errors are mostly unrelated. Used together they narrow the
film's real length far better than AMC's number alone; see
fetchers/tmdb.py for how it is scored.

The sheet is kept by a volunteer. If it can't be read, or has no Regal
number for a screening yet, predictions fall back to AMC's clue alone.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Dict, List, Optional

import requests

from config import MYSTERY_SHEET_CSV_URL, REQUEST_TIMEOUT


def _minutes(value: str) -> Optional[int]:
    """A running time cell as minutes; the sheet uses blank or 0 for none."""
    try:
        minutes = int(float(value.strip()))
    except ValueError:
        return None
    return minutes if minutes > 0 else None


def _rating(value: str) -> str:
    """'PG-13', 'PG13' and 'pg-13 ' all become 'PG13'."""
    return value.replace("-", "").replace(" ", "").upper()


class MysterySheet:

    def __init__(self):
        # Every row of the sheet, in order.
        self.rows: List[dict] = []

    def load(self) -> bool:
        """Downloads the sheet. Returns False (and stays empty) on failure."""
        try:
            response = requests.get(MYSTERY_SHEET_CSV_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            self.rows = self.parse(response.content.decode("utf-8"))
        except Exception as ex:
            print("Could not read the mystery movie sheet:", ex)
            self.rows = []
            return False
        return True

    @staticmethod
    def parse(text: str) -> List[dict]:
        reader = csv.reader(io.StringIO(text))
        header = [cell.strip() for cell in next(reader)]

        def column(name: str) -> int:
            # e.g. "Reported Runtime (in minutes) AMC", "Regal"
            return next(i for i, h in enumerate(header) if h.endswith(name))

        cols = {
            "date": column("Date"),
            "title": column("Title"),
            "rating": column("MPAA Rating"),
            "amc": column("AMC"),
            "regal": column("Regal"),
        }

        rows = []
        current = None

        for cell in reader:
            cell = cell + [""] * (len(header) - len(cell))

            # A second screening on the same Monday (usually Scream
            # Unseen) leaves the date blank.
            if cell[cols["date"]].strip():
                try:
                    current = datetime.strptime(
                        cell[cols["date"]].strip(), "%m/%d/%Y"
                    ).date()
                except ValueError:
                    current = None

            title = cell[cols["title"]].strip()

            if current is None or not title:
                continue

            rows.append({
                "date": current,
                # "????" until the film is revealed
                "title": "" if set(title) == {"?"} else title,
                "rating": _rating(cell[cols["rating"]]),
                "amc": _minutes(cell[cols["amc"]]),
                "regal": _minutes(cell[cols["regal"]]),
            })

        return rows

    def regal_runtime(
        self,
        screening: date,
        rating: str,
        amc_runtime: Optional[int],
    ) -> Optional[int]:
        """
        Regal's listed running time for the AMC mystery screening with
        these clues, or None if the sheet doesn't have one.
        """
        same_day = [
            r for r in self.rows
            if r["date"] == screening and r["rating"] == _rating(rating)
        ]

        # Two screenings that night with the same rating (Screen and
        # Scream Unseen): AMC's running time tells them apart.
        exact = [r for r in same_day if amc_runtime and r["amc"] == amc_runtime]

        if exact:
            return exact[0]["regal"]

        if len(same_day) == 1:
            return same_day[0]["regal"]

        return None

    def regal_runtime_by_title(self, title: str) -> Optional[int]:
        """Regal's listed running time for a revealed film (for the backtest)."""
        wanted = title.strip().lower()
        for r in self.rows:
            if r["title"].lower() == wanted:
                return r["regal"]
        return None
