"""
fetchers/sidewalk.py

Scrapes showtimes for Sidewalk Film Center + Cinema directly from their
public cinema page (sidewalkfest.com/cinema/).

Sidewalk isn't in TMS/Gracenote's theatre database at all (confirmed by
querying TMS directly for the area and finding no Sidewalk listings, even
though Sidewalk publishes current showtimes on their own site), so scraping
their own listings is the only reliable source right now.

The page is server-rendered by a WordPress plugin (class names prefixed
`fwpl-`) and paginates with a plain `?_paged=N` query param, so no headless
browser is needed. One quirk: each showtime is a custom
`<elevent-ticket-button-widget>` element, and HTML parsers (tested with
html.parser, lxml, and html5lib) mishandle its closing tag when many of
them appear in one document -- each movie card ends up nested inside the
previous one instead of being its sibling. Splitting the raw HTML into
one chunk per movie card *before* parsing each chunk avoids this.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from config import (
    REQUEST_TIMEOUT,
    SIDEWALK_CINEMA_URL,
    SIDEWALK_MAX_PAGES,
    SIDEWALK_PAGE_DELAY,
    SIDEWALK_SCREEN_WIDTH_FT,
)

from models import Movie, Showtime

RESULT_SPLIT_RE = re.compile(r'(?=<div class="fwpl-result )')
TOTAL_PAGES_RE = re.compile(r'"total_pages":(\d+)')


class SidewalkFetcher:
    """Scrapes Sidewalk Film Center + Cinema showtimes via the Cloudflare
    Worker proxy (see config.SIDEWALK_CINEMA_URL for why)."""

    # --------------------------------------------------
    # HTTP helper
    # --------------------------------------------------

    def _fetch_page(self, page: int) -> str:
        params = {"_paged": page} if page > 1 else None
        response = requests.get(
            SIDEWALK_CINEMA_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.text

    # --------------------------------------------------
    # Parsing helpers
    # --------------------------------------------------

    @staticmethod
    def _split_result_chunks(html: str) -> List[str]:
        parts = RESULT_SPLIT_RE.split(html)
        return [p for p in parts if p.startswith('<div class="fwpl-result')]

    @staticmethod
    def _text(el) -> Optional[str]:
        if el is None:
            return None
        return el.get_text(strip=True) or None

    def _parse_runtime(self, result) -> Optional[int]:
        m = re.match(r"(\d+)\s*min", self._text(result.select_one(".event-running-time")) or "")
        return int(m.group(1)) if m else None

    def _parse_year(self, result) -> Optional[int]:
        t = self._text(result.select_one(".event-year"))
        if not t:
            return None
        try:
            return int(t[:4])
        except ValueError:
            return None

    def _parse_poster(self, result) -> Optional[str]:
        img = result.select_one(".event-image img")
        if img is None:
            return None

        srcset = img.get("srcset")
        if srcset:
            best_url, best_width = None, -1
            for part in srcset.split(","):
                bits = part.strip().rsplit(" ", 1)
                if len(bits) == 2 and bits[1].endswith("w"):
                    try:
                        width = int(bits[1][:-1])
                    except ValueError:
                        continue
                    if width > best_width:
                        best_width, best_url = width, bits[0]
            if best_url:
                return best_url

        return img.get("src")

    def _parse_synopsis(self, result) -> Optional[str]:
        details = result.select_one(".fwpl-col.details")
        if details is None:
            return None

        # The synopsis div's class name is a hashed, non-semantic string
        # that isn't safe to depend on, so find it structurally instead:
        # it's the direct-child item that isn't the title or the button.
        for div in details.find_all("div", class_="fwpl-item", recursive=False):
            classes = div.get("class", [])
            if "title" in classes or "event-button" in classes:
                continue
            text = self._text(div)
            if text:
                return text

        return None

    @staticmethod
    def _parse_showtime_dt(date_str: str, time_text: str) -> Optional[str]:
        try:
            parsed = datetime.strptime(time_text, "%I:%M %p")
        except ValueError:
            return None
        return f"{date_str}T{parsed.strftime('%H:%M:%S')}"

    def _parse_movie(self, chunk: str) -> Optional[Movie]:
        soup = BeautifulSoup(chunk, "html.parser")
        result = soup.select_one(".fwpl-result")
        if result is None:
            return None

        title_el = result.select_one(".fwpl-item.title a")
        if title_el is None:
            return None

        title = title_el.get_text(strip=True)
        detail_url = title_el.get("href")

        # Sidewalk's listing page includes non-screening events too (movie
        # trivia, filmmaker networking nights, etc.) which run in other
        # on-site spaces. Only keep actual screenings in the cinema itself.
        venue = self._text(result.select_one(".venue-wrapper h3")) or ""
        if "Sidewalk Film Center" not in venue:
            return None

        directors = [
            d.strip()
            for d in (self._text(result.select_one(".event-director")) or "").split(",")
            if d.strip()
        ]

        movie = Movie(
            source="Sidewalk",
            title=title,
            release_year=self._parse_year(result),
            runtime=self._parse_runtime(result),
            poster=self._parse_poster(result),
            directors=directors,
            country=self._text(result.select_one(".event-countries")),
            plot=self._parse_synopsis(result),
            movie_url=detail_url,
        )

        for date_div in result.select(".tickets-for-date"):
            date_str = date_div.get("data-date")
            if not date_str:
                continue

            for widget in date_div.find_all("elevent-ticket-button-widget"):
                dt = self._parse_showtime_dt(date_str, widget.get_text(strip=True))
                if not dt:
                    continue

                status_classes = widget.get("class") or []
                status = status_classes[0] if isinstance(status_classes, list) else str(status_classes)

                movie.add_showtime(Showtime(
                    source="Sidewalk",
                    theater_id=0,
                    theater=venue,
                    showtime_id=widget.get("showtime") or 0,
                    datetime=dt,
                    purchase_url=detail_url,
                    sold_out="sold" in status.lower(),
                    screen_width_ft=SIDEWALK_SCREEN_WIDTH_FT,
                ))

        return movie

    # --------------------------------------------------
    # Public method
    # --------------------------------------------------

    def fetch_movies(self) -> List[Movie]:
        """
        Scrape Sidewalk's cinema page and return normalized movies.
        """

        movies: List[Movie] = []
        total_pages = 1

        page = 1
        while page <= total_pages and page <= SIDEWALK_MAX_PAGES:
            print(f"  Fetching Sidewalk cinema page {page}...")

            html = self._fetch_page(page)

            if page == 1:
                m = TOTAL_PAGES_RE.search(html)
                if m:
                    total_pages = int(m.group(1))

            chunks = self._split_result_chunks(html)
            if not chunks:
                break

            for chunk in chunks:
                movie = self._parse_movie(chunk)
                if movie is not None:
                    movies.append(movie)

            page += 1
            if page <= total_pages and page <= SIDEWALK_MAX_PAGES:
                time.sleep(SIDEWALK_PAGE_DELAY)

        print(f"  Found {len(movies)} Sidewalk screenings across {min(page - 1, total_pages)} page(s).")

        return movies
