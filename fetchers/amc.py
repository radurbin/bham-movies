"""
fetchers/amc.py

AMC showtime fetcher.

Fetches AMC theater showtimes and converts them into
our internal Movie / Showtime models.
"""

from typing import Dict, List

import requests

from config import (
    AMC_BASE_URL,
    AMC_THEATERS,
    REQUEST_TIMEOUT,
    SHOWTIME_PAGE_SIZE,
    get_amc_key,
)

from models import (
    Movie,
    Showtime,
    TicketPrice,
)


class AMCFetcher:
    """
    Fetches and normalizes AMC showtime data.
    """

    def __init__(self):
        self.api_key = get_amc_key()

        self.headers = {
            "accept": "application/json",
            "x-amc-vendor-key": self.api_key,
        }


    # --------------------------------------------------
    # HTTP helper
    # --------------------------------------------------

    def _get(self, endpoint: str, params=None):
        """
        Perform an authenticated AMC API request.
        """

        response = requests.get(
            f"{AMC_BASE_URL}{endpoint}",
            headers=self.headers,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()


    # --------------------------------------------------
    # Fetching
    # --------------------------------------------------

    def fetch_theater_showtimes(
        self,
        theater_id: int,
    ) -> List[dict]:
        """
        Fetch every page of showtimes for a theater.

        AMC defaults to 10 results per page, so we
        explicitly request more and follow pagination.
        """

        showtimes = []

        page = 1

        while True:

            print(
                f"  Fetching theater {theater_id} page {page}..."
            )

            data = self._get(
                f"/theatres/{theater_id}/showtimes",
                {
                    "page-number": page,
                    "page-size": SHOWTIME_PAGE_SIZE,
                },
            )


            embedded = data.get("_embedded", {})

            results = embedded.get(
                "showtimes",
                [],
            )

            showtimes.extend(results)


            #
            # Stop when AMC doesn't provide another page
            #

            links = data.get("_links", {})

            if "next" not in links:
                break


            page += 1


        return showtimes


    def fetch_all_showtimes(self):
        """
        Fetch raw showtimes from every AMC theater.
        """

        results = []

        for theater_id, theater in AMC_THEATERS.items():

            print(
                f"\nFetching {theater['name']}..."
            )

            shows = self.fetch_theater_showtimes(
                theater_id
            )

            for show in shows:

                show["_theater"] = theater

                results.append(show)


            print(
                f"  Found {len(shows)} showtimes"
            )


        return results


    # --------------------------------------------------
    # Normalization
    # --------------------------------------------------

    def _get_poster(self, show: dict) -> str | None:
        """
        AMC returns several poster sizes.
        Pick the best available one.
        """

        media = show.get("media", {})

        candidates = [

            media.get("posterDynamic"),

            media.get("posterAlternateDynamic"),

            media.get("posterIMAXDynamic"),

            media.get("poster3DDynamic"),

            media.get("posterDynamic180X74"),

        ]


        for poster in candidates:

            if poster:
                return poster


        return None



    def _get_movie_key(self, show: dict):
        """
        Unique movie identifier.
        """

        return (
            show.get("movieId"),
            show.get("movieName"),
        )


    def _convert_ticket_prices(
        self,
        show: dict,
    ) -> List[TicketPrice]:

        prices = []

        for price in show.get(
            "ticketPrices",
            [],
        ):

            prices.append(
                TicketPrice(
                    type=price.get("type", ""),
                    price=price.get("price", 0),
                    tax=price.get("tax", 0),
                )
            )

        return prices



    def _convert_showtime(
        self,
        show: dict,
    ) -> Showtime:

        theater = show["_theater"]

        attributes = [

            item.get("name")

            for item in show.get(
                "attributes",
                []
            )

            if item.get("name")
        ]


        return Showtime(

            source="AMC",

            theater_id=show.get(
                "theatreId"
            ),

            theater=theater["name"],

            showtime_id=show.get(
                "id"
            ),

            datetime=show.get(
                "showDateTimeLocal"
            ),

            datetime_utc=show.get(
                "showDateTimeUtc"
            ),

            auditorium=show.get(
                "auditorium"
            ),

            premium_format=(
                show.get(
                    "premiumFormat"
                )
                or "Standard"
            ),

            purchase_url=show.get(
                "purchaseUrl"
            ),

            sold_out=show.get(
                "isSoldOut",
                False,
            ),

            almost_sold_out=show.get(
                "isAlmostSoldOut",
                False,
            ),

            cancelled=show.get(
                "isCanceled",
                False,
            ),

            has_trailers=show.get(
                "hasTrailers",
                False,
            ),

            discount_matinee=show.get(
                "isDiscountMatineePriced",
                False,
            ),

            discount_message=show.get(
                "discountMatineeMessage"
            ),

            attributes=attributes,

            ticket_prices=self._convert_ticket_prices(
                show
            ),
        )



    # --------------------------------------------------
    # Public method
    # --------------------------------------------------

    def fetch_movies(self) -> List[Movie]:
        """
        Fetch AMC data and return normalized movies.
        """

        movies: Dict[tuple, Movie] = {}


        raw_showtimes = self.fetch_all_showtimes()


        print(
            f"\nNormalizing {len(raw_showtimes)} showtimes..."
        )


        for show in raw_showtimes:

            key = self._get_movie_key(show)


            if key not in movies:

                movie = Movie(

                    source="AMC",

                    movie_id=show.get(
                        "movieId"
                    ),

                    title=show.get(
                        "movieName",
                        "",
                    ),

                    runtime=show.get(
                        "runTime"
                    ),

                    rating=show.get(
                        "mpaaRating"
                    ),

                    genres=[
                        show.get("genre")
                    ]
                    if show.get("genre")
                    else [],

                    poster=self._get_poster(
                        show
                    ),

                    movie_url=show.get(
                        "movieUrl"
                    ),

                )

                movies[key] = movie



            movies[key].add_showtime(
                self._convert_showtime(
                    show
                )
            )


        result = list(
            movies.values()
        )


        for movie in result:

            movie.sort_showtimes()


        result.sort(
            key=lambda movie:
                movie.title.lower()
        )


        print(
            f"Created {len(result)} unique movies."
        )


        return result