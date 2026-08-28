import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from .match_policy import BroadcastRange


@dataclass
class SourceContext:
    source_feed_id: Optional[str]
    source_feed_name: Optional[str]
    feed_type: Optional[str]
    feed_entry_id: Optional[str]
    torrent_url: Optional[str]
    raw_title: Optional[str]
    source_published_at: Optional[datetime.datetime]
    observed_at: Optional[datetime.datetime]

    def to_dict(self) -> Dict[str, Any]:
        """Converts source provenance to flat camelCase Firestore fields."""
        return {
            "sourceFeedId": self.source_feed_id,
            "sourceFeedName": self.source_feed_name,
            "feedType": self.feed_type,
            "feedEntryId": self.feed_entry_id,
            "torrentUrl": self.torrent_url,
            "rawTitle": self.raw_title,
            "sourcePublishedAt": self.source_published_at,
            "observedAt": self.observed_at,
        }


def _merge_source_context(
    document: Dict[str, Any], source_context: Optional[SourceContext]
) -> Dict[str, Any]:
    if source_context is None:
        return document
    source_fields = source_context.to_dict()
    for field_name in document.keys() & source_fields.keys():
        if source_fields[field_name] is None:
            del source_fields[field_name]
    document.update(source_fields)
    return document


@dataclass
class Title:
    title: str
    normalized_title: str
    year: Optional[int]
    media_type: str  # 'movie', 'series', 'documentary', or 'short'
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    updated_at: datetime.datetime

    # Optional normalized OMDb metadata fields
    imdb_id: Optional[str] = None
    imdb_rating: Optional[float] = None
    imdb_votes: Optional[int] = None
    metascore: Optional[int] = None
    genres: List[str] = field(default_factory=list)
    countries: List[str] = field(default_factory=list)
    director: Optional[str] = None
    plot: Optional[str] = None
    poster_url: Optional[str] = None
    runtime: Optional[str] = None
    awards: Optional[str] = None
    box_office: Optional[str] = None
    ratings: List[Dict[str, str]] = field(default_factory=list)
    ai_validated: Optional[bool] = None
    ai_checked_at: Optional[datetime.datetime] = None
    source_type: Optional[str] = None
    content_kind: Optional[str] = None
    broadcast_range: Optional[BroadcastRange] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converts the Title model to a camelCase Firestore dictionary."""
        res = {
            "title": self.title,
            "normalizedTitle": self.normalized_title,
            "year": self.year,
            "mediaType": self.media_type,
            "firstSeenAt": self.first_seen_at,
            "lastSeenAt": self.last_seen_at,
            "updatedAt": self.updated_at,
        }
        if self.source_type is not None:
            res["sourceType"] = self.source_type
        if self.content_kind is not None:
            res["contentKind"] = self.content_kind
        if self.broadcast_range is not None:
            res["broadcastRange"] = self.broadcast_range.to_dict()
        if self.imdb_id is not None:
            res["imdbId"] = self.imdb_id
        if self.imdb_rating is not None:
            res["imdbRating"] = self.imdb_rating
        if self.imdb_votes is not None:
            res["imdbVotes"] = self.imdb_votes
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
        if self.ai_validated is not None:
            res["aiValidated"] = self.ai_validated
        if self.ai_checked_at is not None:
            res["aiCheckedAt"] = self.ai_checked_at
        return res


@dataclass
class Occurrence:
    source_feed_id: str
    source_feed_name: str
    feed_entry_id: Optional[str]
    torrent_url: str
    raw_title: str
    quality: Optional[str]
    rip_type: Optional[str]
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    source_context: Optional[SourceContext] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converts the Occurrence model to a camelCase Firestore dictionary."""
        res = {
            "sourceFeedId": self.source_feed_id,
            "sourceFeedName": self.source_feed_name,
            "feedEntryId": self.feed_entry_id,
            "torrentUrl": self.torrent_url,
            "rawTitle": self.raw_title,
            "quality": self.quality,
            "ripType": self.rip_type,
            "firstSeenAt": self.first_seen_at,
            "lastSeenAt": self.last_seen_at,
        }
        return _merge_source_context(res, self.source_context)


@dataclass
class OmdbCacheEntry:
    lookup_title: str
    lookup_year: Optional[int]
    status: str  # 'found' or 'not_found' / other explicit negative status
    payload: Optional[Dict[str, Any]]
    fetched_at: datetime.datetime
    expires_at: datetime.datetime
    lookup_year_semantics: Optional[str] = None
    source_type: Optional[str] = None
    lookup_identity: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converts the OmdbCacheEntry model to a camelCase Firestore dictionary."""
        res = {
            "lookupTitle": self.lookup_title,
            "lookupYear": self.lookup_year,
            "status": self.status,
            "payload": self.payload,
            "fetchedAt": self.fetched_at,
            "expiresAt": self.expires_at,
        }
        if self.lookup_year_semantics is not None:
            res["lookupYearSemantics"] = self.lookup_year_semantics
        if self.source_type is not None:
            res["sourceType"] = self.source_type
        if self.lookup_identity is not None:
            res["lookupIdentity"] = self.lookup_identity
        return res


@dataclass
class ScanRun:
    started_at: datetime.datetime
    finished_at: Optional[datetime.datetime]
    status: str  # 'running', 'succeeded', 'partial', or 'failed'
    trigger: str  # 'schedule', 'manual', or 'local'
    feeds_processed: int = 0
    entries_seen: int = 0
    titles_created: int = 0
    occurrences_created: int = 0
    cache_hits: int = 0
    omdb_requests: int = 0
    ignored_entries: int = 0
    error_count: int = 0
    error_summary: List[str] = field(default_factory=list)
    section_timings: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Converts the ScanRun model to a camelCase Firestore dictionary."""
        res = {
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "status": self.status,
            "trigger": self.trigger,
            "feedsProcessed": self.feeds_processed,
            "entriesSeen": self.entries_seen,
            "titlesCreated": self.titles_created,
            "occurrencesCreated": self.occurrences_created,
            "cacheHits": self.cache_hits,
            "omdbRequests": self.omdb_requests,
            "ignoredEntries": self.ignored_entries,
            "errorCount": self.error_count,
            "errorSummary": self.error_summary,
        }
        if self.section_timings:
            res["sectionTimings"] = self.section_timings
        return res


RetryState = Literal["retryable", "terminal", "resolved"]
ResolutionOutcome = Literal["matched", "terminal"]


@dataclass(frozen=True)
class ParseLogResolution:
    resolved_at: datetime.datetime
    outcome: ResolutionOutcome
    reason: str
    title_id: Optional[str] = None
    occurrence_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.resolved_at, datetime.datetime):
            raise ValueError("resolved_at must be a datetime")
        if self.outcome not in ("matched", "terminal"):
            raise ValueError("resolution outcome must be matched or terminal")
        if not isinstance(self.reason, str) or not self.reason or len(self.reason) > 128:
            raise ValueError("resolution reason must contain 1..128 characters")
        for value in (self.title_id, self.occurrence_id):
            if value is not None and (not isinstance(value, str) or len(value) > 256):
                raise ValueError("resolution identifiers must not exceed 256 characters")

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "resolvedAt": self.resolved_at,
            "outcome": self.outcome,
            "reason": self.reason,
        }
        if self.title_id is not None:
            result["titleId"] = self.title_id
        if self.occurrence_id is not None:
            result["occurrenceId"] = self.occurrence_id
        return result


@dataclass(frozen=True)
class RetryCursor:
    processed_at: datetime.datetime
    log_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.processed_at, datetime.datetime):
            raise ValueError("retry cursor processed_at must be a datetime")
        if not isinstance(self.log_id, str) or not self.log_id:
            raise ValueError("retry cursor log_id must not be empty")


@dataclass
class ParseLog:
    id: str
    raw_title: str
    feed_name: str
    parsed_successfully: bool
    parsed_title: Optional[str]
    parsed_year: Optional[int]
    omdb_status: str  # 'found', 'not_found', 'skipped', 'error', 'not_parsed'
    ignored: bool
    ignore_reason: Optional[str]  # 'no_title', 'parse_error', 'entry_error', 'omdb_not_found', 'excluded_country_or_genre', 'omdb_limit_reached', 'omdb_error', 'empty_title', 'parse_only', None
    processed_at: datetime.datetime
    error_message: Optional[str] = None
    trace_details: Optional[Dict[str, Any]] = None
    decision: Optional[str] = None
    source_context: Optional[SourceContext] = None
    event_kind: Optional[Literal["source", "audit_review"]] = None
    retry_state: Optional[RetryState] = None
    attempt_count: int = 0
    last_attempt_at: Optional[datetime.datetime] = None
    resolution: Optional[ParseLogResolution] = None

    def __post_init__(self) -> None:
        if self.retry_state is not None and self.retry_state not in (
            "retryable",
            "terminal",
            "resolved",
        ):
            raise ValueError("invalid retry state")
        if (
            not isinstance(self.attempt_count, int)
            or isinstance(self.attempt_count, bool)
            or self.attempt_count < 0
        ):
            raise ValueError("attempt_count must not be negative")
        if self.last_attempt_at is not None and not isinstance(
            self.last_attempt_at, datetime.datetime
        ):
            raise ValueError("last_attempt_at must be a datetime")
        if self.resolution is not None and self.retry_state == "retryable":
            raise ValueError("retryable parse logs cannot have resolution metadata")
        if (
            self.resolution is not None
            and self.retry_state == "resolved"
            and self.resolution.outcome != "matched"
        ):
            raise ValueError("resolved parse logs require a matched resolution outcome")
        if (
            self.resolution is not None
            and self.retry_state == "terminal"
            and self.resolution.outcome != "terminal"
        ):
            raise ValueError("terminal parse logs require a terminal resolution outcome")

    def to_dict(self) -> Dict[str, Any]:
        """Converts the ParseLog model to a camelCase Firestore dictionary."""
        res = {
            "id": self.id,
            "rawTitle": self.raw_title,
            "feedName": self.feed_name,
            "parsedSuccessfully": self.parsed_successfully,
            "parsedTitle": self.parsed_title,
            "parsedYear": self.parsed_year,
            "omdbStatus": self.omdb_status,
            "ignored": self.ignored,
            "ignoreReason": self.ignore_reason,
            "processedAt": self.processed_at,
        }
        if self.error_message is not None:
            res["errorMessage"] = self.error_message
        if self.trace_details is not None:
            res["traceDetails"] = self.trace_details
        if self.decision is not None:
            res["decision"] = self.decision
        _merge_source_context(res, self.source_context)
        if self.event_kind is not None:
            res["eventKind"] = self.event_kind
        if self.retry_state is not None:
            res["retryState"] = self.retry_state
        res["attemptCount"] = self.attempt_count
        if self.last_attempt_at is not None:
            res["lastAttemptAt"] = self.last_attempt_at
        if self.resolution is not None:
            res["resolution"] = self.resolution.to_dict()
        return res


@dataclass(frozen=True)
class RetryPage:
    items: List[ParseLog]
    next_cursor: Optional[RetryCursor]


@dataclass
class ManualMapping:
    id: str
    raw_title: str
    imdb_id: str
    created_at: datetime.datetime
    parsed_title: Optional[str] = None
    parsed_year: Optional[int] = None
    created_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converts the ManualMapping model to a camelCase Firestore dictionary."""
        res = {
            "id": self.id,
            "rawTitle": self.raw_title,
            "imdbId": self.imdb_id,
            "createdAt": self.created_at,
        }
        if self.parsed_title is not None:
            res["parsedTitle"] = self.parsed_title
        if self.parsed_year is not None:
            res["parsedYear"] = self.parsed_year
        if self.created_by is not None:
            res["createdBy"] = self.created_by
        return res

