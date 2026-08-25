import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .match_policy import (
    BroadcastRange,
    classify_media,
    is_year_in_series_period,
    parse_broadcast_range,
)


class OmdbError(Exception):
    """Base exception for all OMDb client errors."""
    pass


class OmdbTransportError(OmdbError):
    """Raised when there's an HTTP network error or timeout."""
    pass


class OmdbLimitReachedError(OmdbError):
    """Raised when the daily API limit is reached."""
    pass


class OmdbNoMatchError(OmdbError):
    """Raised when OMDb returns a negative response (e.g., Movie not found)."""
    pass


@dataclass(frozen=True)
class OmdbMovieResult:
    title: str
    year: Optional[int]
    imdb_id: Optional[str]
    media_type: str  # movie, series, documentary, short
    rating: Optional[float]
    votes: Optional[int]
    metascore: Optional[int]
    genres: List[str]
    countries: List[str]
    director: Optional[str]
    plot: Optional[str]
    poster_url: Optional[str]
    runtime: Optional[str]
    awards: Optional[str]
    box_office: Optional[str]
    ratings: List[Dict[str, str]] = field(default_factory=list)
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    source_type: Optional[str] = None
    content_kind: Optional[str] = None
    broadcast_range: Optional[BroadcastRange] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converts the normalized result to a dictionary with camelCase fields suitable for Firestore."""
        res = {
            "title": self.title,
            "year": self.year,
            "mediaType": self.media_type,
        }
        if self.source_type is not None:
            res["sourceType"] = self.source_type
        if self.content_kind is not None:
            res["contentKind"] = self.content_kind
        if self.broadcast_range is not None:
            res["broadcastRange"] = self.broadcast_range.to_dict()
        if self.imdb_id is not None:
            res["imdbId"] = self.imdb_id
        if self.rating is not None:
            res["imdbRating"] = self.rating
        if self.votes is not None:
            res["imdbVotes"] = self.votes
        if self.metascore is not None:
            res["metascore"] = self.metascore
        if self.genres:
            res["genres"] = self.genres
        if self.countries:
            res["countries"] = self.countries
        if self.director is not None:
            res["director"] = self.director
        if self.plot is not None:
            res["plot"] = self.plot
        if self.poster_url is not None:
            res["posterUrl"] = self.poster_url
        if self.runtime is not None:
            res["runtime"] = self.runtime
        if self.awards is not None:
            res["awards"] = self.awards
        if self.box_office is not None:
            res["boxOffice"] = self.box_office
        if self.ratings:
            res["ratings"] = self.ratings
        return res


class HttpTransport(ABC):
    @abstractmethod
    def get(self, url: str, params: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        """
        Sends an HTTP GET request and returns the parsed JSON dictionary.
        Must raise a subclass of Exception on failure.
        """
        pass


class RequestsHttpTransport(HttpTransport):
    def get(self, url: str, params: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        try:
            import requests
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if "Timeout" in e.__class__.__name__:
                raise TimeoutError(str(e)) from e
            raise IOError(str(e)) from e


def _parse_year(year_str: Optional[str]) -> Optional[int]:
    if not year_str or year_str == "N/A":
        return None
    match = re.search(r"\d{4}", year_str)
    if match:
        return int(match.group())
    return None


def _parse_float(val: Optional[str]) -> Optional[float]:
    if not val or val == "N/A":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _parse_int_with_commas(val: Optional[str]) -> Optional[int]:
    if not val or val == "N/A":
        return None
    try:
        return int(val.replace(",", ""))
    except ValueError:
        return None


def _parse_int(val: Optional[str]) -> Optional[int]:
    if not val or val == "N/A":
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _parse_list(val: Optional[str]) -> List[str]:
    if not val or val == "N/A":
        return []
    return [item.strip() for item in val.split(",") if item.strip()]


def _parse_string(val: Optional[str]) -> Optional[str]:
    if not val or val == "N/A":
        return None
    return val


def determine_media_type(omdb_type: str, genres: List[str]) -> str:
    return classify_media(omdb_type, genres).media_type


def _sanitize_string(text: str, api_key: Optional[str]) -> str:
    if not text:
        return text
    if api_key and len(api_key) > 2:
        return text.replace(api_key, "***")
    return text


class OmdbClient:
    def __init__(self, api_key: str, transport: Optional[HttpTransport] = None):
        if not api_key:
            raise ValueError("OMDb API key is required")
        self._api_key = api_key
        self._transport = transport or RequestsHttpTransport()
        self._base_url = "https://www.omdbapi.com/"
        self._timeout = 10.0

    def __repr__(self) -> str:
        return f"OmdbClient(transport={self._transport.__class__.__name__})"

    def _make_request(
        self,
        title: str,
        year: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "apikey": self._api_key,
            "t": title,
        }
        if year:
            params["y"] = str(year)
        if media_type and media_type.lower() in ("movie", "series"):
            params["type"] = media_type.lower()

        try:
            return self._transport.get(self._base_url, params, timeout=self._timeout)
        except Exception as e:
            sanitized_msg = _sanitize_string(str(e), self._api_key)
            raise OmdbTransportError(f"HTTP transport failed: {sanitized_msg}") from e

    def get_by_imdb_id(self, imdb_id: str) -> OmdbMovieResult:
        if not imdb_id:
            raise ValueError("IMDb ID must not be empty")
        params = {
            "apikey": self._api_key,
            "i": imdb_id.strip(),
        }
        try:
            data = self._transport.get(self._base_url, params, timeout=self._timeout)
        except Exception as e:
            sanitized_msg = _sanitize_string(str(e), self._api_key)
            raise OmdbTransportError(f"HTTP transport failed: {sanitized_msg}") from e

        if data.get("Response") == "True":
            return self._normalize_payload(data)
        else:
            err_msg = data.get("Error", "")
            if "limit reached" in err_msg.lower():
                raise OmdbLimitReachedError("Daily API limit reached")
            raise OmdbNoMatchError(f"OMDb lookup failed for IMDb ID {imdb_id}: {err_msg}")

    def get_movie_info(
        self,
        title: str,
        year: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> OmdbMovieResult:
        if not title:
            raise ValueError("Title must not be empty")

        payload = None

        # Special handling for series:
        # OMDb 'y' param filters series by start year. Multi-season torrent titles often use a season release year
        # (e.g. 2012 for Mad Men Season 5, which started in 2007). Querying OMDb with y=2012 either fails or returns
        # an incorrect single-year title (e.g., "Modern Mad Men").
        # Algorithm:
        # 1. Search OMDb by title and type="series" without 'y'.
        # 2. Check if the returned series broadcasting period (Year) covers the requested year.
        if media_type and media_type.lower() == "series":
            data = self._make_request(title, media_type="series")
            if data.get("Response") == "True":
                payload = data
            else:
                err_msg = data.get("Error", "")
                if "limit reached" in err_msg.lower():
                    raise OmdbLimitReachedError("Daily API limit reached")
                raise OmdbNoMatchError(f"OMDb lookup failed: {err_msg}")

        if payload is None and (not media_type or media_type.lower() != "series"):
            # 1. Primary lookup: Title + Year + Media Type (if year is specified)
            if year:
                try:
                    data = self._make_request(title, year, media_type)
                    if data.get("Response") == "True":
                        payload = data
                    else:
                        err_msg = data.get("Error", "")
                        if "limit reached" in err_msg.lower():
                            raise OmdbLimitReachedError("Daily API limit reached")
                except OmdbTransportError:
                    raise

            # 2. Fallback lookup: Title + Media Type (without year, if media_type is specified or as movie)
            if payload is None and media_type and media_type.lower() in ("movie", "series"):
                data = self._make_request(title, media_type=media_type)
                if data.get("Response") == "True":
                    payload = data
                else:
                    err_msg = data.get("Error", "")
                    if "limit reached" in err_msg.lower():
                        raise OmdbLimitReachedError("Daily API limit reached")

            # 3. Fallback lookup: Title only (if not explicitly constrained or after media_type lookup)
            if payload is None and not media_type:
                data = self._make_request(title)
                if data.get("Response") == "True":
                    payload = data
                else:
                    err_msg = data.get("Error", "")
                    if "limit reached" in err_msg.lower():
                        raise OmdbLimitReachedError("Daily API limit reached")

            if payload is None:
                raise OmdbNoMatchError(f"OMDb lookup failed for '{title}' (year={year}, type={media_type})")

        # Return typed normalized result
        return self._normalize_payload(payload)

    def _normalize_payload(self, data: Dict[str, Any]) -> OmdbMovieResult:
        title = data.get("Title", "")
        raw_year = data.get("Year", "")
        year = _parse_year(raw_year)

        imdb_id = _parse_string(data.get("imdbID"))
        raw_type = data.get("Type", "movie")

        rating = _parse_float(data.get("imdbRating"))
        votes = _parse_int_with_commas(data.get("imdbVotes"))
        metascore = _parse_int(data.get("Metascore"))

        genres = _parse_list(data.get("Genre"))
        countries = _parse_list(data.get("Country"))

        director = _parse_string(data.get("Director"))
        plot = _parse_string(data.get("Plot"))
        poster_url = _parse_string(data.get("Poster"))
        runtime = _parse_string(data.get("Runtime"))
        awards = _parse_string(data.get("Awards"))
        box_office = _parse_string(data.get("BoxOffice"))

        ratings = []
        raw_ratings = data.get("Ratings", [])
        if isinstance(raw_ratings, list):
            for r in raw_ratings:
                if isinstance(r, dict) and "Source" in r and "Value" in r:
                    ratings.append({
                        "Source": r["Source"],
                        "Value": r["Value"]
                    })

        classification = classify_media(raw_type, genres)
        media_type = classification.media_type
        broadcast_range = (
            parse_broadcast_range(raw_year)
            if classification.source_type == "series"
            else None
        )

        return OmdbMovieResult(
            title=title,
            year=year,
            imdb_id=imdb_id,
            media_type=media_type,
            rating=rating,
            votes=votes,
            metascore=metascore,
            genres=genres,
            countries=countries,
            director=director,
            plot=plot,
            poster_url=poster_url,
            runtime=runtime,
            awards=awards,
            box_office=box_office,
            ratings=ratings,
            raw_payload=data,
            source_type=classification.source_type,
            content_kind=classification.content_kind,
            broadcast_range=broadcast_range,
        )
