import re
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Sequence, Tuple


SourceType = Literal["movie", "series", "unknown"]
ContentKind = Literal["standard", "documentary", "short"]
DecisionStatus = Literal["accepted", "rejected", "ambiguous"]


@dataclass(frozen=True)
class BroadcastRange:
    """The first and last broadcast years reported by OMDb for a series."""

    start_year: int
    end_year: Optional[int]
    raw: str

    def contains(self, year: int) -> bool:
        return year >= self.start_year and (self.end_year is None or year <= self.end_year)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "startYear": self.start_year,
            "endYear": self.end_year,
            "raw": self.raw,
        }


@dataclass(frozen=True)
class MediaClassification:
    source_type: SourceType
    content_kind: ContentKind
    media_type: str


@dataclass(frozen=True)
class MatchDecision:
    status: DecisionStatus
    reason_code: str
    message: str = ""

    @property
    def is_accepted(self) -> bool:
        return self.status == "accepted"

    @property
    def is_rejected(self) -> bool:
        return self.status == "rejected"

    @property
    def is_ambiguous(self) -> bool:
        return self.status == "ambiguous"


def normalize_source_type(value: Optional[str]) -> SourceType:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if normalized == "movie":
        return "movie"
    if normalized == "series":
        return "series"
    return "unknown"


def effective_source_type(
    media_type: Optional[str],
    source_type: Optional[str] = None,
) -> SourceType:
    explicit_source_type = normalize_source_type(source_type)
    if explicit_source_type != "unknown":
        return explicit_source_type

    normalized_media_type = media_type.strip().lower() if isinstance(media_type, str) else ""
    if normalized_media_type == "series":
        return "series"
    if normalized_media_type in ("movie", "documentary", "short"):
        return "movie"
    return "unknown"


def classify_media(raw_type: Optional[str], genres: Sequence[str]) -> MediaClassification:
    source_type = normalize_source_type(raw_type)
    lowered_genres = {
        genre.strip().lower()
        for genre in genres
        if isinstance(genre, str) and genre.strip()
    }
    if "documentary" in lowered_genres:
        content_kind: ContentKind = "documentary"
    elif "short" in lowered_genres:
        content_kind = "short"
    else:
        content_kind = "standard"

    if source_type == "series":
        media_type = "series"
    elif content_kind == "documentary":
        media_type = "documentary"
    elif content_kind == "short":
        media_type = "short"
    else:
        media_type = "movie"

    return MediaClassification(
        source_type=source_type,
        content_kind=content_kind,
        media_type=media_type,
    )


def parse_broadcast_range(raw_value: Optional[str]) -> Optional[BroadcastRange]:
    if not isinstance(raw_value, str):
        return None

    raw = raw_value.strip()
    if not raw or raw.upper() == "N/A":
        return None

    years = [int(value) for value in re.findall(r"\b\d{4}\b", raw)]
    if not years:
        return None

    normalized = raw.replace("–", "-").replace("—", "-")
    if len(years) >= 2:
        end_year: Optional[int] = years[1]
    elif re.search(r"\d{4}\s*-\s*(?:$|present|current|ongoing)", normalized, re.IGNORECASE):
        end_year = None
    else:
        end_year = years[0]

    return BroadcastRange(start_year=years[0], end_year=end_year, raw=raw)


def broadcast_range_from_dict(value: object) -> Optional[BroadcastRange]:
    if not isinstance(value, dict):
        return None
    start_year = value.get("startYear")
    end_year = value.get("endYear")
    raw = value.get("raw")
    if type(start_year) is not int or (end_year is not None and type(end_year) is not int):
        return None
    if not isinstance(raw, str) or not raw:
        raw = str(start_year) if end_year == start_year else f"{start_year}-{end_year or ''}"
    return BroadcastRange(start_year=start_year, end_year=end_year, raw=raw)


def _exclusion(
    countries: Sequence[str],
    genres: Sequence[str],
    excluded_countries: Sequence[str],
    excluded_genres: Sequence[str],
) -> Optional[Tuple[str, str]]:
    excluded_country_set = {
        country.strip().lower()
        for country in excluded_countries
        if isinstance(country, str) and country.strip()
    }
    normalized_countries = [country for country in countries if isinstance(country, str)]
    if normalized_countries and all(country.lower() in excluded_country_set for country in normalized_countries):
        matched = [country for country in normalized_countries if country.lower() in excluded_country_set]
        return (
            "excluded_country",
            f"Филтрирана държава: {', '.join(matched)} (Всички държави: {', '.join(normalized_countries)})",
        )

    excluded_genre_set = {
        genre.strip().lower()
        for genre in excluded_genres
        if isinstance(genre, str) and genre.strip()
    }
    normalized_genres = [genre for genre in genres if isinstance(genre, str)]
    matched_genres = [genre for genre in normalized_genres if genre.lower() in excluded_genre_set]
    if matched_genres:
        return (
            "excluded_genre",
            f"Филтриран жанр: {', '.join(matched_genres)} (OMDb жанрове: {', '.join(normalized_genres)})",
        )
    return None


def get_exclusion_reason(
    countries: Sequence[str],
    genres: Sequence[str],
    excluded_countries: Sequence[str],
    excluded_genres: Sequence[str],
) -> Optional[str]:
    result = _exclusion(countries, genres, excluded_countries, excluded_genres)
    return result[1] if result else None


def evaluate_match(
    *,
    expected_source_type: Optional[str],
    actual_source_type: Optional[str] = None,
    actual_media_type: Optional[str] = None,
    source_year: Optional[int] = None,
    resolved_year: Optional[int] = None,
    broadcast_range: Optional[BroadcastRange] = None,
    countries: Sequence[str] = (),
    genres: Sequence[str] = (),
    excluded_countries: Sequence[str] = (),
    excluded_genres: Sequence[str] = (),
    manual_mapping: bool = False,
) -> MatchDecision:
    actual = effective_source_type(actual_media_type, actual_source_type)
    expected = normalize_source_type(expected_source_type)

    if manual_mapping:
        exclusion = _exclusion(countries, genres, excluded_countries, excluded_genres)
        if exclusion:
            return MatchDecision("rejected", exclusion[0], exclusion[1])
        return MatchDecision(
            "accepted",
            "manual_mapping_bypass",
            "Manual IMDb mapping bypasses source type and year checks.",
        )

    def accepted(reason_code: str, message: str) -> MatchDecision:
        exclusion = _exclusion(countries, genres, excluded_countries, excluded_genres)
        if exclusion:
            return MatchDecision("rejected", exclusion[0], exclusion[1])
        return MatchDecision("accepted", reason_code, message)

    if expected != "unknown" and actual == "unknown":
        return MatchDecision(
            "ambiguous",
            "source_type_unknown",
            "The resolved metadata does not expose a supported source type.",
        )
    if expected != "unknown" and actual != expected:
        return MatchDecision(
            "rejected",
            "type_mismatch",
            f"Expected source type '{expected}', resolved '{actual}'.",
        )
    if expected == "unknown" and actual == "unknown":
        return MatchDecision(
            "ambiguous",
            "source_type_unknown",
            "Neither the feed nor the resolved metadata identifies a source type.",
        )
    if actual == "series":
        if source_year is None:
            return accepted(
                "series_season_year_unknown",
                "The source does not provide a season/release year.",
            )
        if broadcast_range is None:
            return accepted(
                "series_broadcast_range_unavailable",
                "The source season year is not rejected because OMDb has no broadcast range.",
            )
        if broadcast_range.contains(source_year):
            return accepted(
                "series_season_year_in_range",
                "The source season/release year is inside the OMDb broadcast range.",
            )
        return MatchDecision(
            "rejected",
            "series_season_year_out_of_range",
            "The source season/release year is outside the OMDb broadcast range.",
        )

    if source_year is None or resolved_year is None:
        return accepted(
            "movie_release_year_unknown",
            "The movie release year cannot be compared, so it is not rejected solely for being unknown.",
        )
    if abs(resolved_year - source_year) <= 1:
        return accepted(
            "movie_release_year_within_tolerance",
            "Movie release years are within the one-year tolerance.",
        )
    return MatchDecision(
        "rejected",
        "movie_release_year_mismatch",
        "Movie release years differ by more than one year.",
    )


def is_year_in_series_period(raw_year: Optional[str], target_year: int) -> bool:
    """Backward-compatible helper: unknown OMDb ranges remain non-disqualifying."""
    parsed = parse_broadcast_range(raw_year)
    return parsed is None or parsed.contains(target_year)