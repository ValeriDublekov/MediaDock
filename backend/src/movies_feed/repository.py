from abc import ABC, abstractmethod
import copy
import datetime
from typing import Any, Dict, List, Optional

from .audit_proposal import (
    AuditProposal,
    InvalidStatusTransitionError,
    is_valid_proposal_status_transition,
)
from .models import (
    ManualMapping,
    OmdbCacheEntry,
    Occurrence,
    ParseLog,
    RetryCursor,
    RetryPage,
    RetryState,
    ScanRun,
    SourceContext,
    Title,
)


_RETRYABLE_REASONS = frozenset({
    "entry_error",
    "omdb_error",
    "omdb_limit_reached",
    "omdb_not_found",
    "parse_error",
    "source_context_missing",
    "manual_mapping_error",
    "ai_result_missing",
    "ai_title_missing",
    "ai_year_invalid",
    "ai_media_type_missing",
    "reparse_processing_error",
    "catalog_persistence_error",
})
_TERMINAL_REASONS = frozenset({
    "audit_needs_review",
    "empty_title",
    "excluded_country_or_genre",
    "match_ambiguous",
    "media_type_mismatch",
    "no_title",
    "parse_only",
    "year_mismatch",
})


def effective_retry_state(log: ParseLog) -> RetryState:
    if log.retry_state is not None:
        return log.retry_state
    if log.event_kind == "audit_review":
        return "terminal"
    if log.omdb_status == "found" and not log.ignored:
        return "resolved"
    if log.ignore_reason in _RETRYABLE_REASONS:
        return "retryable"
    if log.ignore_reason in _TERMINAL_REASONS:
        return "terminal"
    return "terminal"


def _resolution_matches_state(log: ParseLog) -> bool:
    if log.resolution is None:
        return False
    state = effective_retry_state(log)
    return (
        state == "resolved" and log.resolution.outcome == "matched"
    ) or (
        state == "terminal" and log.resolution.outcome == "terminal"
    )


def merge_source_context(
    existing: Optional[SourceContext], incoming: Optional[SourceContext]
) -> Optional[SourceContext]:
    if existing is None:
        return copy.deepcopy(incoming)
    if incoming is None:
        return copy.deepcopy(existing)
    observed_values = [value for value in (existing.observed_at, incoming.observed_at) if value is not None]
    return SourceContext(
        source_feed_id=existing.source_feed_id or incoming.source_feed_id,
        source_feed_name=incoming.source_feed_name or existing.source_feed_name,
        feed_type=existing.feed_type or incoming.feed_type,
        feed_entry_id=existing.feed_entry_id or incoming.feed_entry_id,
        torrent_url=existing.torrent_url or incoming.torrent_url,
        raw_title=existing.raw_title or incoming.raw_title,
        source_published_at=existing.source_published_at or incoming.source_published_at,
        observed_at=max(observed_values) if observed_values else None,
    )


def merge_titles(existing: Title, incoming: Title) -> Title:
    """Merges refreshed metadata while preserving earliest first_seen_at.

    Uses latest last_seen_at, and merges other OMDb/metadata fields.
    """
    first_seen_at = min(existing.first_seen_at, incoming.first_seen_at)
    last_seen_at = max(existing.last_seen_at, incoming.last_seen_at)

    imdb_id = incoming.imdb_id if incoming.imdb_id is not None else existing.imdb_id
    imdb_rating = incoming.imdb_rating if incoming.imdb_rating is not None else existing.imdb_rating
    imdb_votes = incoming.imdb_votes if incoming.imdb_votes is not None else existing.imdb_votes
    metascore = incoming.metascore if incoming.metascore is not None else existing.metascore
    genres = incoming.genres if incoming.genres else existing.genres
    countries = incoming.countries if incoming.countries else existing.countries
    director = incoming.director if incoming.director is not None else existing.director
    plot = incoming.plot if incoming.plot is not None else existing.plot
    poster_url = incoming.poster_url if incoming.poster_url is not None else existing.poster_url
    runtime = incoming.runtime if incoming.runtime is not None else existing.runtime
    awards = incoming.awards if incoming.awards is not None else existing.awards
    box_office = incoming.box_office if incoming.box_office is not None else existing.box_office
    ratings = incoming.ratings if incoming.ratings else existing.ratings
    ai_validated = incoming.ai_validated if incoming.ai_validated is not None else existing.ai_validated
    ai_checked_at = incoming.ai_checked_at if incoming.ai_checked_at is not None else existing.ai_checked_at
    source_type = incoming.source_type if incoming.source_type is not None else existing.source_type
    content_kind = incoming.content_kind if incoming.content_kind is not None else existing.content_kind
    broadcast_range = incoming.broadcast_range if incoming.broadcast_range is not None else existing.broadcast_range

    return Title(
        title=incoming.title or existing.title,
        normalized_title=incoming.normalized_title or existing.normalized_title,
        year=incoming.year if incoming.year is not None else existing.year,
        media_type=incoming.media_type or existing.media_type,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        updated_at=incoming.updated_at,
        imdb_id=imdb_id,
        imdb_rating=imdb_rating,
        imdb_votes=imdb_votes,
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
        ai_validated=ai_validated,
        ai_checked_at=ai_checked_at,
        source_type=source_type,
        content_kind=content_kind,
        broadcast_range=broadcast_range,
    )


def merge_occurrences(existing: Occurrence, incoming: Occurrence) -> Occurrence:
    """Merges duplicate occurrences by preserving earliest first_seen_at and latest last_seen_at."""
    first_seen_at = min(existing.first_seen_at, incoming.first_seen_at)
    last_seen_at = max(existing.last_seen_at, incoming.last_seen_at)
    return Occurrence(
        source_feed_id=incoming.source_feed_id,
        source_feed_name=incoming.source_feed_name,
        feed_entry_id=incoming.feed_entry_id,
        torrent_url=incoming.torrent_url,
        raw_title=incoming.raw_title,
        quality=incoming.quality if incoming.quality is not None else existing.quality,
        rip_type=incoming.rip_type if incoming.rip_type is not None else existing.rip_type,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        source_context=merge_source_context(existing.source_context, incoming.source_context),
        validation_status=incoming.validation_status or existing.validation_status,
        validation_policy_version=incoming.validation_policy_version or existing.validation_policy_version,
        validation_reason=incoming.validation_reason or existing.validation_reason,
        validated_at=incoming.validated_at or existing.validated_at,
    )


def merge_parse_logs(existing: ParseLog, incoming: ParseLog) -> ParseLog:
    merged = copy.deepcopy(incoming)
    merged.source_context = merge_source_context(existing.source_context, incoming.source_context)
    merged.attempt_count = max(existing.attempt_count, incoming.attempt_count)
    attempt_times = [
        value
        for value in (existing.last_attempt_at, incoming.last_attempt_at)
        if value is not None
    ]
    merged.last_attempt_at = max(attempt_times) if attempt_times else None
    if incoming.resolution is None and _resolution_matches_state(existing):
        merged.resolution = copy.deepcopy(existing.resolution)
    return merged


class TitleRepository(ABC):
    @abstractmethod
    def get(self, title_id: str) -> Optional[Title]:
        """Fetches a Title by its ID."""
        pass

    def get_many(self, title_ids: List[str]) -> Dict[str, Title]:
        """Fetches multiple Titles by their IDs. Default implementation calls get for each."""
        result: Dict[str, Title] = {}
        for title_id in set(title_ids):
            t = self.get(title_id)
            if t is not None:
                result[title_id] = t
        return result

    @abstractmethod
    def upsert(self, title_id: str, title: Title) -> None:
        """Inserts a Title or merges metadata if already existing."""
        pass

    def upsert_many(self, titles: List[tuple[str, Title]]) -> None:
        """Upserts multiple Titles. Default implementation calls upsert for each."""
        for title_id, title in titles:
            self.upsert(title_id, title)

    @abstractmethod
    def list_all(self) -> List[Title]:
        """Lists all Titles in the repository."""
        pass

    @abstractmethod
    def list_all_ids_and_titles(self) -> List[tuple[str, Title]]:
        """Lists all (title_id, Title) pairs in the repository."""
        pass

    @abstractmethod
    def delete(self, title_id: str) -> None:
        """Deletes a Title by its ID."""
        pass


class OccurrenceRepository(ABC):
    @abstractmethod
    def get(self, title_id: str, occurrence_id: str) -> Optional[Occurrence]:
        """Fetches an Occurrence by title ID and occurrence ID."""
        pass

    def get_many(self, keys: List[tuple[str, str]]) -> Dict[tuple[str, str], Occurrence]:
        """Fetches multiple Occurrences by (title_id, occurrence_id) tuple keys."""
        result: Dict[tuple[str, str], Occurrence] = {}
        for title_id, occurrence_id in set(keys):
            occ = self.get(title_id, occurrence_id)
            if occ is not None:
                result[(title_id, occurrence_id)] = occ
        return result

    @abstractmethod
    def upsert(self, title_id: str, occurrence_id: str, occurrence: Occurrence) -> None:
        """Inserts an Occurrence or merges lastSeenAt if already existing."""
        pass

    def upsert_many(self, occurrences: List[tuple[str, str, Occurrence]]) -> None:
        """Upserts multiple Occurrences. Default implementation calls upsert for each."""
        for title_id, occurrence_id, occ in occurrences:
            self.upsert(title_id, occurrence_id, occ)

    @abstractmethod
    def list_by_title(self, title_id: str) -> List[Occurrence]:
        """Lists all Occurrences associated with a Title."""
        pass

    @abstractmethod
    def delete(self, title_id: str, occurrence_id: str) -> None:
        """Deletes a specific Occurrence."""
        pass

    @abstractmethod
    def delete_by_title(self, title_id: str) -> None:
        """Deletes all Occurrences associated with a Title."""
        pass


class OmdbCacheRepository(ABC):
    @abstractmethod
    def get(self, cache_key: str) -> Optional[OmdbCacheEntry]:
        """Fetches an OMDb cache entry by its deterministic key."""
        pass

    def get_many(self, cache_keys: List[str]) -> Dict[str, OmdbCacheEntry]:
        """Fetches multiple OMDb cache entries by keys."""
        result: Dict[str, OmdbCacheEntry] = {}
        for key in set(cache_keys):
            entry = self.get(key)
            if entry is not None:
                result[key] = entry
        return result

    @abstractmethod
    def set(self, cache_key: str, entry: OmdbCacheEntry) -> None:
        """Stores or replaces an OMDb cache entry."""
        pass


class ScanRunRepository(ABC):
    @abstractmethod
    def get(self, run_id: str) -> Optional[ScanRun]:
        """Fetches a ScanRun by its ID."""
        pass

    @abstractmethod
    def upsert(self, run_id: str, run: ScanRun) -> None:
        """Stores or updates a ScanRun by its ID."""
        pass

    @abstractmethod
    def list_all(self) -> List[ScanRun]:
        """Lists all ScanRuns in the repository."""
        pass


class ParseLogRepository(ABC):
    @abstractmethod
    def add(self, log: ParseLog) -> None:
        """Stores a parse log entry."""
        pass

    def add_many(self, logs: List[ParseLog]) -> None:
        """Stores multiple parse log entries."""
        for log in logs:
            self.add(log)

    @abstractmethod
    def prune_older_than(self, cutoff: datetime.datetime) -> int:
        """Deletes parse log entries older than cutoff timestamp."""
        pass

    @abstractmethod
    def list_recent(self, limit: int = 100) -> List[ParseLog]:
        """Lists recent parse log entries."""
        pass

    def list_unmapped(self, limit: int = 200) -> List[ParseLog]:
        """Compatibility adapter returning the first bounded retry page."""
        return self.list_retryable(limit=limit).items

    @abstractmethod
    def list_retryable(
        self,
        limit: int = 200,
        cursor: Optional[RetryCursor] = None,
    ) -> RetryPage:
        """Lists retryable parse logs in deterministic newest-first order."""
        pass


class FakeTitleRepository(TitleRepository):
    def __init__(self) -> None:
        self._store: Dict[str, Title] = {}

    def get(self, title_id: str) -> Optional[Title]:
        return copy.deepcopy(self._store.get(title_id))

    def upsert(self, title_id: str, title: Title) -> None:
        existing = self._store.get(title_id)
        incoming = copy.deepcopy(title)
        if existing:
            self._store[title_id] = merge_titles(existing, incoming)
        else:
            self._store[title_id] = incoming

    def list_all(self) -> List[Title]:
        return copy.deepcopy(list(self._store.values()))

    def list_all_ids_and_titles(self) -> List[tuple[str, Title]]:
        return [(title_id, copy.deepcopy(title)) for title_id, title in self._store.items()]

    def delete(self, title_id: str) -> None:
        if title_id in self._store:
            del self._store[title_id]


class FakeOccurrenceRepository(OccurrenceRepository):
    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Occurrence]] = {}

    def get(self, title_id: str, occurrence_id: str) -> Optional[Occurrence]:
        return copy.deepcopy(self._store.get(title_id, {}).get(occurrence_id))

    def upsert(self, title_id: str, occurrence_id: str, occurrence: Occurrence) -> None:
        if title_id not in self._store:
            self._store[title_id] = {}
        existing = self._store[title_id].get(occurrence_id)
        incoming = copy.deepcopy(occurrence)
        if existing:
            self._store[title_id][occurrence_id] = merge_occurrences(existing, incoming)
        else:
            self._store[title_id][occurrence_id] = incoming

    def list_by_title(self, title_id: str) -> List[Occurrence]:
        return copy.deepcopy(list(self._store.get(title_id, {}).values()))

    def delete(self, title_id: str, occurrence_id: str) -> None:
        if title_id in self._store and occurrence_id in self._store[title_id]:
            del self._store[title_id][occurrence_id]

    def delete_by_title(self, title_id: str) -> None:
        if title_id in self._store:
            del self._store[title_id]


class FakeOmdbCacheRepository(OmdbCacheRepository):
    def __init__(self) -> None:
        self._store: Dict[str, OmdbCacheEntry] = {}

    def get(self, cache_key: str) -> Optional[OmdbCacheEntry]:
        return copy.deepcopy(self._store.get(cache_key))

    def set(self, cache_key: str, entry: OmdbCacheEntry) -> None:
        self._store[cache_key] = copy.deepcopy(entry)


class FakeScanRunRepository(ScanRunRepository):
    def __init__(self) -> None:
        self._store: Dict[str, ScanRun] = {}

    def get(self, run_id: str) -> Optional[ScanRun]:
        return copy.deepcopy(self._store.get(run_id))

    def upsert(self, run_id: str, run: ScanRun) -> None:
        self._store[run_id] = copy.deepcopy(run)

    def list_all(self) -> List[ScanRun]:
        return copy.deepcopy(list(self._store.values()))


class FakeParseLogRepository(ParseLogRepository):
    def __init__(self) -> None:
        self._store: Dict[str, ParseLog] = {}

    def add(self, log: ParseLog) -> None:
        existing = self._store.get(log.id)
        incoming = copy.deepcopy(log)
        if incoming.retry_state is None:
            incoming.retry_state = effective_retry_state(incoming)
        self._store[log.id] = merge_parse_logs(existing, incoming) if existing else incoming

    def prune_older_than(self, cutoff: datetime.datetime) -> int:
        to_delete = [
            log_id
            for log_id, log in self._store.items()
            if log.processed_at < cutoff and effective_retry_state(log) != "retryable"
        ]
        for log_id in to_delete:
            del self._store[log_id]
        return len(to_delete)

    def list_recent(self, limit: int = 100) -> List[ParseLog]:
        sorted_logs = sorted(self._store.values(), key=lambda l: l.processed_at, reverse=True)
        return copy.deepcopy(sorted_logs[:limit])

    def list_retryable(
        self,
        limit: int = 200,
        cursor: Optional[RetryCursor] = None,
    ) -> RetryPage:
        if limit <= 0 or limit > 500:
            raise ValueError("retry page limit must be between 1 and 500")
        ordered = sorted(
            (log for log in self._store.values() if effective_retry_state(log) == "retryable"),
            key=lambda log: (log.processed_at, log.id),
            reverse=True,
        )
        if cursor is not None:
            ordered = [
                log
                for log in ordered
                if (log.processed_at, log.id) < (cursor.processed_at, cursor.log_id)
            ]
        page_items = ordered[:limit]
        next_cursor = None
        if len(ordered) > limit:
            last = page_items[-1]
            next_cursor = RetryCursor(last.processed_at, last.id)
        return RetryPage(copy.deepcopy(page_items), next_cursor)

    def get_all(self) -> List[ParseLog]:
        return copy.deepcopy(list(self._store.values()))


class ManualMappingRepository(ABC):
    @abstractmethod
    def get_all(self) -> List[ManualMapping]:
        """Lists all active manual mappings."""
        pass

    @abstractmethod
    def set(self, mapping: ManualMapping) -> None:
        """Stores or replaces a manual mapping."""
        pass

    @abstractmethod
    def delete(self, mapping_id: str) -> None:
        """Deletes a manual mapping by ID."""
        pass


class FakeManualMappingRepository(ManualMappingRepository):
    def __init__(self) -> None:
        self._store: Dict[str, ManualMapping] = {}

    def get_all(self) -> List[ManualMapping]:
        return copy.deepcopy(list(self._store.values()))

    def set(self, mapping: ManualMapping) -> None:
        self._store[mapping.id] = copy.deepcopy(mapping)

    def delete(self, mapping_id: str) -> None:
        if mapping_id in self._store:
            del self._store[mapping_id]


class AuditProposalRepository(ABC):
    @abstractmethod
    def get(self, proposal_id: str) -> Optional[AuditProposal]:
        """Fetches an AuditProposal by its ID."""
        pass

    @abstractmethod
    def upsert(self, proposal: AuditProposal) -> None:
        """Stores or updates an AuditProposal, enforcing valid status transitions and bounds."""
        pass

    @abstractmethod
    def refresh_from_audit(self, proposal: AuditProposal) -> None:
        """Refreshes an audit proposal only when its existing status is pending."""
        pass

    @abstractmethod
    def list_by_status(self, status: str, limit: int = 100) -> List[AuditProposal]:
        """Lists AuditProposals filtered by status."""
        pass

    @abstractmethod
    def list_by_source_title(self, source_title_id: str) -> List[AuditProposal]:
        """Lists AuditProposals for a specific source title ID."""
        pass

    @abstractmethod
    def list_all(self) -> List[AuditProposal]:
        """Lists all AuditProposals in the repository."""
        pass

    @abstractmethod
    def acquire_lease(self, proposal_id: str, lease_duration: datetime.timedelta, now: datetime.datetime) -> bool:
        """Attempts to acquire a lease on an 'approved' or stale 'applying' proposal, transitioning it to 'applying'."""
        pass

    @abstractmethod
    def delete(self, proposal_id: str) -> None:
        """Deletes an AuditProposal by ID."""
        pass


class FakeAuditProposalRepository(AuditProposalRepository):
    def __init__(self) -> None:
        self._store: Dict[str, AuditProposal] = {}

    def get(self, proposal_id: str) -> Optional[AuditProposal]:
        proposal = self._store.get(proposal_id)
        return copy.deepcopy(proposal) if proposal is not None else None

    def upsert(self, proposal: AuditProposal) -> None:
        incoming = copy.deepcopy(proposal)
        existing = self._store.get(incoming.id)
        if existing is not None:
            if not is_valid_proposal_status_transition(existing.status, incoming.status):
                raise InvalidStatusTransitionError(
                    f"Cannot transition proposal '{incoming.id}' from '{existing.status}' to '{incoming.status}'"
                )
            incoming.created_at = min(existing.created_at, incoming.created_at)
        self._store[incoming.id] = incoming

    def refresh_from_audit(self, proposal: AuditProposal) -> None:
        incoming = copy.deepcopy(proposal)
        existing = self._store.get(incoming.id)
        if existing is None:
            self._store[incoming.id] = incoming
            return
        if existing.status != "pending":
            return
        incoming.created_at = existing.created_at
        incoming.status = existing.status
        incoming.leased_until = existing.leased_until
        self._store[incoming.id] = incoming

    def list_by_status(self, status: str, limit: int = 100) -> List[AuditProposal]:
        if limit <= 0:
            return []
        matching = [
            copy.deepcopy(p)
            for p in self._store.values()
            if p.status == status
        ]
        return matching[:limit]

    def list_by_source_title(self, source_title_id: str) -> List[AuditProposal]:
        return [
            copy.deepcopy(p)
            for p in self._store.values()
            if p.source_title_id == source_title_id
        ]

    def list_all(self) -> List[AuditProposal]:
        return [copy.deepcopy(p) for p in self._store.values()]

    def acquire_lease(self, proposal_id: str, lease_duration: datetime.timedelta, now: datetime.datetime) -> bool:
        proposal = self._store.get(proposal_id)
        if not proposal:
            return False
        
        if proposal.status == "applying":
            # Stale lease recovery
            if proposal.leased_until is None or now >= proposal.leased_until:
                # Recover
                proposal.status = "failed"
                proposal.leased_until = None
                proposal.updated_at = now
                return False
            else:
                # Currently leased
                return False
                
        if proposal.status != "approved":
            return False

        # Prevent concurrent moves for the same source title
        for other_proposal in self._store.values():
            if (other_proposal.id != proposal_id 
                and other_proposal.source_title_id == proposal.source_title_id 
                and other_proposal.status == "applying"):
                if other_proposal.leased_until is not None and now < other_proposal.leased_until:
                    return False

        proposal.status = "applying"
        proposal.leased_until = now + lease_duration
        proposal.updated_at = now
        return True

    def delete(self, proposal_id: str) -> None:
        if proposal_id in self._store:
            del self._store[proposal_id]


