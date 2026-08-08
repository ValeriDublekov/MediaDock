import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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

    def to_dict(self) -> Dict[str, Any]:
        """Converts the Occurrence model to a camelCase Firestore dictionary."""
        return {
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


@dataclass
class OmdbCacheEntry:
    lookup_title: str
    lookup_year: Optional[int]
    status: str  # 'found' or 'not_found' / other explicit negative status
    payload: Optional[Dict[str, Any]]
    fetched_at: datetime.datetime
    expires_at: datetime.datetime

    def to_dict(self) -> Dict[str, Any]:
        """Converts the OmdbCacheEntry model to a camelCase Firestore dictionary."""
        return {
            "lookupTitle": self.lookup_title,
            "lookupYear": self.lookup_year,
            "status": self.status,
            "payload": self.payload,
            "fetchedAt": self.fetched_at,
            "expiresAt": self.expires_at,
        }


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
    ignore_reason: Optional[str]  # 'no_title', 'omdb_not_found', 'excluded_country_or_genre', 'omdb_limit_reached', 'omdb_error', 'empty_title', 'parse_only', None
    processed_at: datetime.datetime

    def to_dict(self) -> Dict[str, Any]:
        """Converts the ParseLog model to a camelCase Firestore dictionary."""
        return {
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

