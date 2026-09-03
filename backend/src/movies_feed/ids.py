import hashlib
import re
from typing import Optional, Sequence, Union


def _sha256_id(canonical_value: str) -> str:
    return hashlib.sha256(canonical_value.encode("utf-8")).hexdigest()


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


def get_fallback_title_id_v1(normalized_title: str, year: Optional[int], media_type: str) -> str:
    """Computes the legacy v1 fallback title ID without reinterpreting its inputs."""
    year_str = str(year) if year is not None else ""
    raw_str = f"v1:{normalized_title}:{year_str}:{media_type.lower()}"
    return _sha256_id(raw_str)


def get_fallback_title_id(normalized_title: str, year: Optional[int], media_type: str) -> str:
    """Compatibility wrapper for the legacy v1 fallback title ID."""
    return get_fallback_title_id_v1(normalized_title, year, media_type)


def _normalize_source_media_type(media_type: str) -> str:
    normalized_media_type = media_type.strip().lower() if isinstance(media_type, str) else ""
    if normalized_media_type == "series":
        return "series"
    if normalized_media_type in ("movie", "documentary", "short"):
        return "movie"
    return "unknown"


def get_fallback_title_id_v2(
    resolved_title: str,
    canonical_year: Optional[int],
    source_media_type: str,
) -> str:
    """Computes a v2 title ID from canonical resolved metadata."""
    normalized_resolved_title = normalize_title(resolved_title)
    normalized_source_type = _normalize_source_media_type(source_media_type)
    year_semantics = {
        "movie": "movie_release_year",
        "series": "series_start_year",
    }.get(normalized_source_type, "unknown_year")
    year_value = str(canonical_year) if canonical_year is not None else ""
    canonical_value = (
        f"v2:title:{normalized_resolved_title}:{year_semantics}:"
        f"{year_value}:{normalized_source_type}"
    )
    return _sha256_id(canonical_value)


def get_title_id(imdb_id: Optional[str], normalized_title: str, year: Optional[int], media_type: str) -> str:
    """Gets the title ID, preferring lowercase OMDb imdbID, falling back to versioned deterministic hash."""
    if imdb_id and imdb_id.strip():
        return imdb_id.strip().lower()
    return get_fallback_title_id(normalized_title, year, media_type)


def get_title_id_v2(
    imdb_id: Optional[str],
    resolved_title: str,
    canonical_year: Optional[int],
    source_media_type: str,
) -> str:
    """Gets a normalized IMDb ID or a v2 fallback based on resolved metadata."""
    if imdb_id and imdb_id.strip():
        return imdb_id.strip().lower()
    return get_fallback_title_id_v2(resolved_title, canonical_year, source_media_type)


def get_occurrence_id_v1(feed_entry_id: Optional[str], torrent_url: str) -> str:
    """Computes the legacy v1 source ID without feed identity."""
    if feed_entry_id and feed_entry_id.strip():
        identity_value = feed_entry_id.strip()
    else:
        identity_value = torrent_url.strip()
    return _sha256_id(f"v1:{identity_value}")


def get_occurrence_id(feed_entry_id: Optional[str], torrent_url: str) -> str:
    """Compatibility wrapper for the legacy v1 occurrence ID."""
    return get_occurrence_id_v1(feed_entry_id, torrent_url)


def get_source_item_id(
    source_feed_id: str,
    feed_entry_id: Optional[str],
    torrent_url: Optional[str],
) -> str:
    """Computes the v2 ID shared by an occurrence and its source ParseLog."""
    normalized_source_feed_id = source_feed_id.strip() if isinstance(source_feed_id, str) else ""
    if not normalized_source_feed_id:
        raise ValueError("source_feed_id is required for a v2 source item ID")

    normalized_feed_entry_id = feed_entry_id.strip() if isinstance(feed_entry_id, str) else ""
    if normalized_feed_entry_id:
        identity_kind = "entry"
        identity_value = normalized_feed_entry_id
    else:
        normalized_torrent_url = torrent_url.strip() if isinstance(torrent_url, str) else ""
        if not normalized_torrent_url:
            raise ValueError("feed_entry_id or torrent_url is required for a v2 source item ID")
        identity_kind = "url"
        identity_value = normalized_torrent_url

    return _sha256_id(
        f"v2:source:{normalized_source_feed_id}:{identity_kind}:{identity_value}"
    )


def get_audit_event_id(event_identity: str) -> str:
    """Computes a v2 audit ID in a namespace distinct from source items."""
    normalized_event_identity = event_identity.strip() if isinstance(event_identity, str) else ""
    if not normalized_event_identity:
        raise ValueError("event_identity is required for a v2 audit event ID")
    return _sha256_id(f"v2:audit:{normalized_event_identity}")


def get_rss_snapshot_id(run_id: str) -> str:
    """Computes a stable snapshot ID for one scanner run."""
    normalized_run_id = run_id.strip() if isinstance(run_id, str) else ""
    if not normalized_run_id:
        raise ValueError("run_id is required for an RSS snapshot ID")
    return _sha256_id(f"v1:rss-snapshot:{normalized_run_id}")


def get_cache_key(
    lookup_title: str,
    lookup_year: Optional[int],
    media_type: Optional[str] = None,
    year_semantics: Optional[str] = None,
    lookup_identity: Optional[str] = None,
) -> str:
    """Gets a versioned OMDb cache key with type and year semantics."""
    norm_title = normalize_title(lookup_title)
    year_str = str(lookup_year) if lookup_year is not None else ""
    normalized_media_type = media_type.strip().lower() if isinstance(media_type, str) else "unknown"
    if normalized_media_type not in ("movie", "series"):
        normalized_media_type = "unknown"
    normalized_year_semantics = year_semantics.strip().lower() if isinstance(year_semantics, str) else ""
    if not normalized_year_semantics:
        normalized_year_semantics = {
            "movie": "movie_release_year",
            "series": "series_season_year",
        }.get(normalized_media_type, "unknown_year")
    normalized_identity = lookup_identity.strip().lower() if isinstance(lookup_identity, str) else ""
    raw_str = (
        f"v2:cache:{norm_title}:{year_str}:{normalized_year_semantics}:"
        f"{normalized_media_type}:{normalized_identity}"
    )
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def get_audit_proposal_id(
    source_title_id: str,
    cluster_identity: Union[str, Sequence[str]],
    policy_version: str = "v1",
) -> str:
    """Generates a deterministic v2 ID for an audit proposal.

    Derived from the source title, normalized cluster identity, and policy version.
    """
    normalized_source_title_id = source_title_id.strip() if isinstance(source_title_id, str) else ""
    if not normalized_source_title_id:
        raise ValueError("source_title_id is required for an audit proposal ID")

    if isinstance(cluster_identity, (list, tuple, set)):
        cleaned_cluster = ",".join(sorted(str(c).strip() for c in cluster_identity if str(c).strip()))
    elif isinstance(cluster_identity, str):
        cleaned_cluster = cluster_identity.strip()
    else:
        cleaned_cluster = str(cluster_identity).strip()

    if not cleaned_cluster:
        raise ValueError("cluster_identity is required for an audit proposal ID")

    normalized_policy_version = policy_version.strip() if isinstance(policy_version, str) else "v1"
    if not normalized_policy_version:
        normalized_policy_version = "v1"

    canonical_raw = f"v2:proposal:{normalized_source_title_id}:{cleaned_cluster}:{normalized_policy_version}"
    return _sha256_id(canonical_raw)


def get_audit_proposal_id_v3(
    source_title_id: str,
    source_feed_id: str,
    raw_title: str,
    occurrence_ids: Sequence[str],
    policy_version: str,
) -> str:
    """Generates a deterministic v3 ID from source and occurrence identity."""
    normalized_source_title_id = source_title_id.strip() if isinstance(source_title_id, str) else ""
    if not normalized_source_title_id:
        raise ValueError("source_title_id is required for a v3 audit proposal ID")

    normalized_source_feed_id = source_feed_id.strip() if isinstance(source_feed_id, str) else ""
    if not normalized_source_feed_id:
        raise ValueError("source_feed_id is required for a v3 audit proposal ID")

    normalized_raw_title = normalize_title(raw_title) if isinstance(raw_title, str) else ""
    if not normalized_raw_title:
        raise ValueError("raw_title is required for a v3 audit proposal ID")

    if isinstance(occurrence_ids, str):
        raise ValueError("occurrence_ids are required for a v3 audit proposal ID")
    try:
        normalized_occurrence_ids = []
        for occurrence_id in occurrence_ids:
            if not isinstance(occurrence_id, str) or not occurrence_id.strip():
                raise ValueError("occurrence_ids must contain non-empty IDs for a v3 audit proposal ID")
            normalized_occurrence_ids.append(occurrence_id.strip())
    except TypeError as exc:
        raise ValueError("occurrence_ids are required for a v3 audit proposal ID") from exc
    if not normalized_occurrence_ids:
        raise ValueError("occurrence_ids are required for a v3 audit proposal ID")

    normalized_policy_version = policy_version.strip() if isinstance(policy_version, str) else ""
    if not normalized_policy_version:
        raise ValueError("policy_version is required for a v3 audit proposal ID")

    canonical_raw = (
        f"v3:proposal:{normalized_source_title_id}:{normalized_source_feed_id}:"
        f"{normalized_raw_title}:{','.join(sorted(normalized_occurrence_ids))}:"
        f"{normalized_policy_version}"
    )
    return _sha256_id(canonical_raw)

