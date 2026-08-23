from abc import ABC, abstractmethod
import datetime
from typing import Any, Dict, List, Optional

from .models import ManualMapping, OmdbCacheEntry, Occurrence, ParseLog, ScanRun, Title


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
    )


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

    @abstractmethod
    def list_unmapped(self, limit: int = 200) -> List[ParseLog]:
        """Lists recent unmapped/not_found/error parse logs."""
        pass


class FakeTitleRepository(TitleRepository):
    def __init__(self) -> None:
        self._store: Dict[str, Title] = {}

    def get(self, title_id: str) -> Optional[Title]:
        return self._store.get(title_id)

    def upsert(self, title_id: str, title: Title) -> None:
        existing = self._store.get(title_id)
        if existing:
            self._store[title_id] = merge_titles(existing, title)
        else:
            self._store[title_id] = title

    def list_all(self) -> List[Title]:
        return list(self._store.values())

    def list_all_ids_and_titles(self) -> List[tuple[str, Title]]:
        return list(self._store.items())

    def delete(self, title_id: str) -> None:
        if title_id in self._store:
            del self._store[title_id]


class FakeOccurrenceRepository(OccurrenceRepository):
    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Occurrence]] = {}

    def get(self, title_id: str, occurrence_id: str) -> Optional[Occurrence]:
        return self._store.get(title_id, {}).get(occurrence_id)

    def upsert(self, title_id: str, occurrence_id: str, occurrence: Occurrence) -> None:
        if title_id not in self._store:
            self._store[title_id] = {}
        existing = self._store[title_id].get(occurrence_id)
        if existing:
            self._store[title_id][occurrence_id] = merge_occurrences(existing, occurrence)
        else:
            self._store[title_id][occurrence_id] = occurrence

    def list_by_title(self, title_id: str) -> List[Occurrence]:
        return list(self._store.get(title_id, {}).values())

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
        return self._store.get(cache_key)

    def set(self, cache_key: str, entry: OmdbCacheEntry) -> None:
        self._store[cache_key] = entry


class FakeScanRunRepository(ScanRunRepository):
    def __init__(self) -> None:
        self._store: Dict[str, ScanRun] = {}

    def get(self, run_id: str) -> Optional[ScanRun]:
        return self._store.get(run_id)

    def upsert(self, run_id: str, run: ScanRun) -> None:
        self._store[run_id] = run

    def list_all(self) -> List[ScanRun]:
        return list(self._store.values())


class FakeParseLogRepository(ParseLogRepository):
    def __init__(self) -> None:
        self._store: Dict[str, ParseLog] = {}

    def add(self, log: ParseLog) -> None:
        self._store[log.id] = log

    def prune_older_than(self, cutoff: datetime.datetime) -> int:
        to_delete = [log_id for log_id, log in self._store.items() if log.processed_at < cutoff]
        for log_id in to_delete:
            del self._store[log_id]
        return len(to_delete)

    def list_recent(self, limit: int = 100) -> List[ParseLog]:
        sorted_logs = sorted(self._store.values(), key=lambda l: l.processed_at, reverse=True)
        return sorted_logs[:limit]

    def list_unmapped(self, limit: int = 200) -> List[ParseLog]:
        unmapped = [
            l for l in self._store.values()
            if l.omdb_status in ("not_found", "error", "not_parsed", "skipped") or l.ignored
        ]
        sorted_unmapped = sorted(unmapped, key=lambda l: l.processed_at, reverse=True)
        return sorted_unmapped[:limit]

    def get_all(self) -> List[ParseLog]:
        return list(self._store.values())


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
        return list(self._store.values())

    def set(self, mapping: ManualMapping) -> None:
        self._store[mapping.id] = mapping

    def delete(self, mapping_id: str) -> None:
        if mapping_id in self._store:
            del self._store[mapping_id]

