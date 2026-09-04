import copy
import datetime
from typing import Dict, List, Optional

from movies_feed.audit_proposal import (
    AuditProposal,
    InvalidStatusTransitionError,
    is_valid_proposal_status_transition,
)
from movies_feed.models import (
    ManualMapping,
    OmdbCacheEntry,
    Occurrence,
    ParseLog,
    RetryCursor,
    RetryPage,
    RssSnapshot,
    RssSnapshotItem,
    ScanRun,
    Title,
)
from movies_feed.repository import (
    AuditProposalRepository,
    ManualMappingRepository,
    OmdbCacheRepository,
    OccurrenceRepository,
    ParseLogRepository,
    RssSnapshotRepository,
    ScanRunRepository,
    TitleRepository,
    effective_retry_state,
    merge_occurrences,
    merge_parse_logs,
    merge_titles,
)


class FakeTitleRepository(TitleRepository):
    def __init__(self) -> None:
        self._store: Dict[str, Title] = {}

    def get(self, title_id: str) -> Optional[Title]:
        return copy.deepcopy(self._store.get(title_id))

    def upsert(self, title_id: str, title: Title) -> None:
        existing = self._store.get(title_id)
        incoming = copy.deepcopy(title)
        self._store[title_id] = merge_titles(existing, incoming) if existing else incoming

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
        self._store[title_id][occurrence_id] = (
            merge_occurrences(existing, incoming) if existing else incoming
        )

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


class FakeRssSnapshotRepository(RssSnapshotRepository):
    def __init__(self) -> None:
        self._snapshots: Dict[str, tuple[RssSnapshot, List[RssSnapshotItem]]] = {}
        self._current_snapshot_id: Optional[str] = None

    def publish(
        self,
        snapshot_id: str,
        snapshot: RssSnapshot,
        items: List[RssSnapshotItem],
    ) -> None:
        self._snapshots[snapshot_id] = (
            copy.deepcopy(snapshot),
            copy.deepcopy(items),
        )
        self._current_snapshot_id = snapshot_id

    def get_latest(self) -> Optional[tuple[RssSnapshot, List[RssSnapshotItem]]]:
        if self._current_snapshot_id is None:
            return None
        snapshot = self._snapshots.get(self._current_snapshot_id)
        return copy.deepcopy(snapshot) if snapshot is not None else None


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
        sorted_logs = sorted(self._store.values(), key=lambda log: log.processed_at, reverse=True)
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
            copy.deepcopy(proposal)
            for proposal in self._store.values()
            if proposal.status == status
        ]
        return matching[:limit]

    def list_by_source_title(self, source_title_id: str) -> List[AuditProposal]:
        return [
            copy.deepcopy(proposal)
            for proposal in self._store.values()
            if proposal.source_title_id == source_title_id
        ]

    def list_all(self) -> List[AuditProposal]:
        return [copy.deepcopy(proposal) for proposal in self._store.values()]

    def acquire_lease(
        self,
        proposal_id: str,
        lease_duration: datetime.timedelta,
        now: datetime.datetime,
    ) -> bool:
        proposal = self._store.get(proposal_id)
        if not proposal:
            return False
        if proposal.status == "applying":
            if proposal.leased_until is None or now >= proposal.leased_until:
                proposal.status = "failed"
                proposal.leased_until = None
                proposal.updated_at = now
            return False
        if proposal.status != "approved":
            return False
        for other_proposal in self._store.values():
            if (
                other_proposal.id != proposal_id
                and other_proposal.source_title_id == proposal.source_title_id
                and other_proposal.status == "applying"
                and other_proposal.leased_until is not None
                and now < other_proposal.leased_until
            ):
                return False
        proposal.status = "applying"
        proposal.leased_until = now + lease_duration
        proposal.updated_at = now
        return True

    def delete(self, proposal_id: str) -> None:
        if proposal_id in self._store:
            del self._store[proposal_id]
