import hashlib
import re
from typing import Optional


def normalize_title(title: str) -> str:
    """Case-folds and collapses multiple spaces in title for robust matching and deduplication."""
    if not title:
        return ""
    return " ".join(title.strip().lower().split())


def clean_title_for_comparison(title: Optional[str]) -> str:
    """Normalizes title by lowercasing, replacing '&' with 'and', stripping punctuation and extra spaces."""
    if not title:
        return ""
    cleaned = title.lower().replace("&", "and")
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return " ".join(cleaned.split())


def get_fallback_title_id(normalized_title: str, year: Optional[int], media_type: str) -> str:
    """Computes a versioned deterministic SHA-256-derived ID from title, year, and media type."""
    year_str = str(year) if year is not None else ""
    raw_str = f"v1:{normalized_title}:{year_str}:{media_type.lower()}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def get_title_id(imdb_id: Optional[str], normalized_title: str, year: Optional[int], media_type: str) -> str:
    """Gets the title ID, preferring lowercase OMDb imdbID, falling back to versioned deterministic hash."""
    if imdb_id and imdb_id.strip():
        return imdb_id.strip().lower()
    return get_fallback_title_id(normalized_title, year, media_type)


def get_occurrence_id(feed_entry_id: Optional[str], torrent_url: str) -> str:
    """Gets deterministic occurrence ID, using feedEntryId hash if present, otherwise torrentUrl hash."""
    if feed_entry_id and feed_entry_id.strip():
        val = feed_entry_id.strip()
    else:
        val = torrent_url.strip()
    raw_str = f"v1:{val}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def get_cache_key(lookup_title: str, lookup_year: Optional[int]) -> str:
    """Gets deterministic OMDb cache key from lookup title and year."""
    norm_title = normalize_title(lookup_title)
    year_str = str(lookup_year) if lookup_year is not None else ""
    raw_str = f"v1:cache:{norm_title}:{year_str}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
