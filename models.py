"""
models.py

Shared dataclasses used throughout the Movie Calendar project.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional

@dataclass
class Theater:

    id: int

    name: str

    city: str

    source: str


# --------------------------------------------------------
# Ticket pricing
# --------------------------------------------------------

@dataclass
class TicketPrice:
    type: str
    price: float
    tax: float = 0.0

    def to_dict(self):
        return asdict(self)


# --------------------------------------------------------
# Individual showtime
# --------------------------------------------------------

@dataclass
class Showtime:

    source: str

    theater_id: int
    theater: str

    showtime_id: int

    datetime: str
    datetime_utc: Optional[str] = None

    auditorium: Optional[int] = None

    premium_format: str = "Standard"

    purchase_url: Optional[str] = None

    sold_out: bool = False
    almost_sold_out: bool = False
    cancelled: bool = False

    has_trailers: bool = False

    discount_matinee: bool = False
    discount_message: Optional[str] = None

    attributes: List[str] = field(default_factory=list)

    ticket_prices: List[TicketPrice] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


# --------------------------------------------------------
# Canonical Movie object
# --------------------------------------------------------

@dataclass(order=True)
class Movie:
    sort_index: str = field(init=False, repr=False)

    def __post_init__(self):
        self.sort_index = self.title.lower()

    #
    # Source information
    #
    source: str

    movie_id: Optional[int] = None

    #
    # Basic information
    #
    title: str = ""
    release_year: Optional[int] = None

    runtime: Optional[int] = None

    rating: Optional[str] = None

    genres: List[str] = field(default_factory=list)

    #
    # Images
    #
    poster: Optional[str] = None

    backdrop: Optional[str] = None

    #
    # Descriptions
    #
    short_description: Optional[str] = None

    plot: Optional[str] = None

    #
    # People
    #
    directors: List[str] = field(default_factory=list)

    writers: List[str] = field(default_factory=list)

    actors: List[str] = field(default_factory=list)

    #
    # Ratings
    #
    imdb_id: Optional[str] = None

    imdb_rating: Optional[str] = None

    imdb_votes: Optional[str] = None

    rotten_tomatoes: Optional[str] = None

    metacritic: Optional[str] = None

    letterboxd_rating: Optional[float] = None

    letterboxd_rating_count: Optional[int] = None

    letterboxd_url: Optional[str] = None

    #
    # Extra metadata
    #
    awards: Optional[str] = None

    language: Optional[str] = None

    country: Optional[str] = None

    box_office: Optional[str] = None

    website: Optional[str] = None

    #
    # URLs
    #
    movie_url: Optional[str] = None

    trailer_url: Optional[str] = None

    #
    # Showtime data
    #
    showtimes: List[Showtime] = field(default_factory=list)

    #
    # Utility methods
    #

    def add_showtime(self, showtime: Showtime):
        self.showtimes.append(showtime)

    def sort_showtimes(self):
        self.showtimes.sort(key=lambda s: s.datetime)

    def to_dict(self):
        return asdict(self)


# --------------------------------------------------------
# Utility helpers
# --------------------------------------------------------

def sort_movies(movies: List[Movie]) -> List[Movie]:
    """
    Sort every movie's showtimes, then sort movies alphabetically.
    """

    for movie in movies:
        movie.sort_showtimes()

    movies.sort(key=lambda m: m.title.lower())

    return movies