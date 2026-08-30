import copy
import os
import datetime
from typing import Any, Dict, List, Optional
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.field_path import FieldPath

from .match_policy import broadcast_range_from_dict, effective_source_type
from .models import (
    AuditProposal,
    InvalidStatusTransitionError,
    ManualMapping,
    OmdbCacheEntry,
    Occurrence,
    ParseLog,
    ParseLogResolution,
    RetryCursor,
    RetryPage,
    ScanRun,
    SourceContext,
    Title,
    VALID_AUDIT_PROPOSAL_STATUSES,
    is_valid_proposal_status_transition,
)
from .repository import (
    AuditProposalRepository,
    ManualMappingRepository,
    OmdbCacheRepository,
    OccurrenceRepository,
    ParseLogRepository,
    ScanRunRepository,
    TitleRepository,
    effective_retry_state,
    merge_occurrences,
    merge_parse_logs,
    merge_titles,
)


def get_firestore_client(
    project_id: str = "demo-project", database_id: Optional[str] = None
) -> firestore.firestore.Client:
    """Initializes and returns a Firestore client.

    Supports the local Firestore emulator if FIRESTORE_EMULATOR_HOST is set.
    """
    raw_db_id = database_id or os.environ.get("FIRESTORE_DATABASE_ID") or os.environ.get("FIREBASE_DATABASE_ID")
    # If the user or env sets "(default)", "%28default%29", or empty string, treat it as default database
    db_id = raw_db_id if raw_db_id and raw_db_id not in ("(default)", "%28default%29") else None

    if not firebase_admin._apps:
        if os.environ.get("FIRESTORE_EMULATOR_HOST"):
            if not os.environ.get("GCLOUD_PROJECT"):
                os.environ["GCLOUD_PROJECT"] = project_id
            
            # Generate a real, syntactically valid RSA key file using openssl if not present
            key_path = "/tmp/dummy_key.pem"
            if not os.path.exists(key_path):
                import subprocess
                subprocess.run(["openssl", "genrsa", "-out", key_path, "2048"], check=True, capture_output=True)
            
            with open(key_path, "r") as f:
                private_key_content = f.read()

            # Initialize with dummy service account dictionary
            dummy_cert = {
                "type": "service_account",
                "project_id": project_id,
                "private_key_id": "dummy_key_id",
                "private_key": private_key_content,
                "client_email": f"dummy@{project_id}.iam.gserviceaccount.com",
                "client_id": "123456",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/dummy%40{project_id}.iam.gserviceaccount.com"
            }
            cred = credentials.Certificate(dummy_cert)
            firebase_admin.initialize_app(cred, {"projectId": project_id})
        else:
            firebase_admin.initialize_app()

    if db_id:
        return firestore.client(database_id=db_id)
    return firestore.client()


def title_from_dict(d: dict) -> Title:
    """Reconstructs a Title model from a camelCase dictionary retrieved from Firestore."""
    if not isinstance(d, dict) or "title" not in d:
        keys_str = list(d.keys()) if isinstance(d, dict) else str(type(d))
        raise KeyError(f"Document missing required 'title' field (keys present: {keys_str})")
    media_type = d.get("mediaType", "movie")
    content_kind = d.get("contentKind")
    if content_kind is None:
        content_kind = media_type if media_type in ("documentary", "short") else "standard"
    return Title(
        title=d["title"],
        normalized_title=d.get("normalizedTitle", d["title"].lower()),
        year=d.get("year"),
        media_type=media_type,
        first_seen_at=d.get("firstSeenAt", datetime.datetime.now(datetime.timezone.utc)),
        last_seen_at=d.get("lastSeenAt", datetime.datetime.now(datetime.timezone.utc)),
        updated_at=d.get("updatedAt", datetime.datetime.now(datetime.timezone.utc)),
        imdb_id=d.get("imdbId"),
        imdb_rating=d.get("imdbRating") if d.get("imdbRating") is None else float(d["imdbRating"]),
        imdb_votes=d.get("imdbVotes") if d.get("imdbVotes") is None else int(d["imdbVotes"]),
        metascore=d.get("metascore") if d.get("metascore") is None else int(d["metascore"]),
        genres=d.get("genres") or [],
        countries=d.get("countries") or [],
        director=d.get("director"),
        plot=d.get("plot"),
        poster_url=d.get("posterUrl"),
        runtime=d.get("runtime"),
        awards=d.get("awards"),
        box_office=d.get("boxOffice"),
        ratings=d.get("ratings") or [],
        ai_validated=d.get("aiValidated"),
        ai_checked_at=d.get("aiCheckedAt"),
        source_type=d.get("sourceType") or effective_source_type(media_type),
        content_kind=content_kind,
        broadcast_range=broadcast_range_from_dict(d.get("broadcastRange")),
    )


def source_context_from_dict(d: dict) -> Optional[SourceContext]:
    """Reads optional flat provenance fields without inferring legacy context."""
    context_markers = ("feedType", "sourcePublishedAt", "observedAt")
    if not any(field_name in d for field_name in context_markers):
        return None
    return SourceContext(
        source_feed_id=d.get("sourceFeedId"),
        source_feed_name=d.get("sourceFeedName"),
        feed_type=d.get("feedType"),
        feed_entry_id=d.get("feedEntryId"),
        torrent_url=d.get("torrentUrl"),
        raw_title=d.get("rawTitle"),
        source_published_at=d.get("sourcePublishedAt"),
        observed_at=d.get("observedAt"),
    )


def occurrence_from_dict(d: dict) -> Occurrence:
    """Reconstructs an Occurrence model from a camelCase dictionary retrieved from Firestore."""
    return Occurrence(
        source_feed_id=d["sourceFeedId"],
        source_feed_name=d["sourceFeedName"],
        feed_entry_id=d.get("feedEntryId"),
        torrent_url=d["torrentUrl"],
        raw_title=d["rawTitle"],
        quality=d.get("quality"),
        rip_type=d.get("ripType"),
        first_seen_at=d["firstSeenAt"],
        last_seen_at=d["lastSeenAt"],
        source_context=source_context_from_dict(d),
    )


def cache_entry_from_dict(d: dict) -> OmdbCacheEntry:
    """Reconstructs an OmdbCacheEntry model from a camelCase dictionary retrieved from Firestore."""
    return OmdbCacheEntry(
        lookup_title=d["lookupTitle"],
        lookup_year=d.get("lookupYear"),
        status=d["status"],
        payload=d.get("payload"),
        fetched_at=d["fetchedAt"],
        expires_at=d["expiresAt"],
        lookup_year_semantics=d.get("lookupYearSemantics"),
        source_type=d.get("sourceType"),
        lookup_identity=d.get("lookupIdentity"),
    )


def scan_run_from_dict(d: dict) -> ScanRun:
    """Reconstructs a ScanRun model from a camelCase dictionary retrieved from Firestore."""
    return ScanRun(
        started_at=d["startedAt"],
        finished_at=d.get("finishedAt"),
        status=d["status"],
        trigger=d["trigger"],
        feeds_processed=d.get("feedsProcessed", 0),
        entries_seen=d.get("entriesSeen", 0),
        titles_created=d.get("titlesCreated", 0),
        occurrences_created=d.get("occurrencesCreated", 0),
        cache_hits=d.get("cacheHits", 0),
        omdb_requests=d.get("omdbRequests", 0),
        ignored_entries=d.get("ignoredEntries", 0),
        error_count=d.get("errorCount", 0),
        error_summary=d.get("errorSummary") or [],
        section_timings=d.get("sectionTimings") or {},
    )


def parse_log_from_dict(d: dict, doc_id: Optional[str] = None) -> ParseLog:
    """Reconstructs a ParseLog model from a camelCase dictionary retrieved from Firestore."""
    log_id = d.get("id") or doc_id or ""
    retry_state = d.get("retryState")
    if retry_state not in ("retryable", "terminal", "resolved"):
        retry_state = None
    attempt_count = d.get("attemptCount", 0)
    if not isinstance(attempt_count, int) or isinstance(attempt_count, bool) or attempt_count < 0:
        attempt_count = 0
    resolution = None
    resolution_data = d.get("resolution")
    if isinstance(resolution_data, dict):
        try:
            resolution = ParseLogResolution(
                resolved_at=resolution_data["resolvedAt"],
                outcome=resolution_data["outcome"],
                reason=resolution_data["reason"],
                title_id=resolution_data.get("titleId"),
                occurrence_id=resolution_data.get("occurrenceId"),
            )
        except (KeyError, TypeError, ValueError):
            resolution = None
    log = ParseLog(
        id=log_id,
        raw_title=d.get("rawTitle", ""),
        feed_name=d.get("feedName", ""),
        parsed_successfully=d.get("parsedSuccessfully", False),
        parsed_title=d.get("parsedTitle"),
        parsed_year=d.get("parsedYear"),
        omdb_status=d.get("omdbStatus", "not_parsed"),
        ignored=d.get("ignored", False),
        ignore_reason=d.get("ignoreReason"),
        processed_at=d.get("processedAt") or datetime.datetime.now(datetime.timezone.utc),
        error_message=d.get("errorMessage"),
        trace_details=d.get("traceDetails"),
        decision=d.get("decision"),
        source_context=source_context_from_dict(d),
        event_kind=d.get("eventKind"),
        retry_state=retry_state,
        attempt_count=attempt_count,
        last_attempt_at=d.get("lastAttemptAt"),
        resolution=resolution,
    )
    log.retry_state = effective_retry_state(log)
    if log.retry_state == "retryable" or (
        log.resolution is not None
        and (
            (log.retry_state == "resolved" and log.resolution.outcome != "matched")
            or (log.retry_state == "terminal" and log.resolution.outcome != "terminal")
        )
    ):
        log.resolution = None
    return log


def manual_mapping_from_dict(d: dict, doc_id: Optional[str] = None) -> ManualMapping:
    """Reconstructs a ManualMapping model from a camelCase dictionary retrieved from Firestore."""
    mapping_id = d.get("id") or doc_id or ""
    return ManualMapping(
        id=mapping_id,
        raw_title=d.get("rawTitle", ""),
        imdb_id=d.get("imdbId", ""),
        created_at=d.get("createdAt") or datetime.datetime.now(datetime.timezone.utc),
        parsed_title=d.get("parsedTitle"),
        parsed_year=d.get("parsedYear"),
        created_by=d.get("createdBy"),
    )


def audit_proposal_from_dict(d: dict, doc_id: Optional[str] = None) -> AuditProposal:
    """Reconstructs an AuditProposal model from a camelCase dictionary retrieved from Firestore."""
    proposal_id = d.get("id") or doc_id or ""
    created_at = d.get("createdAt")
    if not isinstance(created_at, datetime.datetime):
        created_at = datetime.datetime.now(datetime.timezone.utc)
    updated_at = d.get("updatedAt")
    if not isinstance(updated_at, datetime.datetime):
        updated_at = datetime.datetime.now(datetime.timezone.utc)

    status = d.get("status", "pending")
    if status not in VALID_AUDIT_PROPOSAL_STATUSES:
        status = "pending"

    confidence = d.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (ValueError, TypeError):
        confidence = 0.0

    return AuditProposal(
        id=proposal_id,
        source_title_id=d.get("sourceTitleId", ""),
        occurrence_ids=list(d.get("occurrenceIds") or []),
        raw_title_cluster=list(d.get("rawTitleCluster") or []),
        current_metadata=dict(d.get("currentMetadata") or {}),
        proposed_metadata=dict(d.get("proposedMetadata") or {}),
        evidence=dict(d.get("evidence") or {}),
        confidence=confidence,
        policy_version=d.get("policyVersion", "v1"),
        created_at=created_at,
        updated_at=updated_at,
        status=status,
    )




class FirestoreTitleRepository(TitleRepository):
    def __init__(self, db: Optional[firestore.firestore.Client] = None) -> None:
        self.db = db if db is not None else get_firestore_client()
        self.collection_ref = self.db.collection("titles")

    def get(self, title_id: str) -> Optional[Title]:
        if title_id == "settings_config":
            return None
        doc_ref = self.collection_ref.document(title_id)
        snapshot = doc_ref.get()
        if snapshot.exists:
            data = snapshot.to_dict()
            if not data or "title" not in data:
                return None
            return title_from_dict(data)
        return None

    def get_many(self, title_ids: List[str]) -> Dict[str, Title]:
        ids = [tid for tid in set(title_ids) if tid != "settings_config"]
        if not ids:
            return {}
        result: Dict[str, Title] = {}
        chunk_size = 500
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            doc_refs = [self.collection_ref.document(tid) for tid in chunk]
            snapshots = self.db.get_all(doc_refs)
            for snap in snapshots:
                if snap.exists:
                    data = snap.to_dict()
                    if data and "title" in data:
                        result[snap.id] = title_from_dict(data)
        return result

    def upsert(self, title_id: str, title: Title) -> None:
        doc_ref = self.collection_ref.document(title_id)

        @firestore.transactional
        def _upsert_tx(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            if snapshot.exists:
                existing = title_from_dict(snapshot.to_dict())
                merged = merge_titles(existing, title)
                transaction.set(doc_ref, merged.to_dict())
            else:
                transaction.set(doc_ref, title.to_dict())

        transaction = self.db.transaction()
        _upsert_tx(transaction)

    def upsert_many(self, titles: List[tuple[str, Title]]) -> None:
        for title_id, title in titles:
            self.upsert(title_id, title)

    def list_all(self) -> List[Title]:
        docs = self.collection_ref.stream()
        res = []
        for doc in docs:
            if doc.id == "settings_config":
                continue
            data = doc.to_dict()
            if not data or "title" not in data:
                continue
            try:
                res.append(title_from_dict(data))
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Skipping document '{doc.id}' in list_all: {e}")
        return res

    def list_all_ids_and_titles(self) -> List[tuple[str, Title]]:
        docs = self.collection_ref.stream()
        res = []
        for doc in docs:
            if doc.id == "settings_config":
                continue
            data = doc.to_dict()
            if not data or "title" not in data:
                continue
            try:
                res.append((doc.id, title_from_dict(data)))
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Skipping document '{doc.id}' in list_all_ids_and_titles: {e}")
        return res

    def delete(self, title_id: str) -> None:
        doc_ref = self.collection_ref.document(title_id)
        doc_ref.delete()


class FirestoreOccurrenceRepository(OccurrenceRepository):
    def __init__(self, db: Optional[firestore.firestore.Client] = None) -> None:
        self.db = db if db is not None else get_firestore_client()

    def _get_occ_ref(self, title_id: str, occurrence_id: str):
        return self.db.collection("titles").document(title_id).collection("occurrences").document(occurrence_id)

    def get(self, title_id: str, occurrence_id: str) -> Optional[Occurrence]:
        doc_ref = self._get_occ_ref(title_id, occurrence_id)
        snapshot = doc_ref.get()
        if snapshot.exists:
            return occurrence_from_dict(snapshot.to_dict())
        return None

    def get_many(self, keys: List[tuple[str, str]]) -> Dict[tuple[str, str], Occurrence]:
        unique_keys = list(set(keys))
        if not unique_keys:
            return {}
        result: Dict[tuple[str, str], Occurrence] = {}
        chunk_size = 500
        for i in range(0, len(unique_keys), chunk_size):
            chunk = unique_keys[i : i + chunk_size]
            doc_refs = [self._get_occ_ref(tid, occ_id) for tid, occ_id in chunk]
            snapshots = self.db.get_all(doc_refs)
            for snap in snapshots:
                if snap.exists:
                    title_id = snap.reference.parent.parent.id
                    occ_id = snap.id
                    result[(title_id, occ_id)] = occurrence_from_dict(snap.to_dict())
        return result

    def upsert(self, title_id: str, occurrence_id: str, occurrence: Occurrence) -> None:
        doc_ref = self._get_occ_ref(title_id, occurrence_id)

        @firestore.transactional
        def _upsert_tx(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            if snapshot.exists:
                existing = occurrence_from_dict(snapshot.to_dict())
                merged = merge_occurrences(existing, occurrence)
                transaction.set(doc_ref, merged.to_dict())
            else:
                transaction.set(doc_ref, occurrence.to_dict())

        transaction = self.db.transaction()
        _upsert_tx(transaction)

    def upsert_many(self, occurrences: List[tuple[str, str, Occurrence]]) -> None:
        for title_id, occurrence_id, occurrence in occurrences:
            self.upsert(title_id, occurrence_id, occurrence)

    def list_by_title(self, title_id: str) -> List[Occurrence]:
        collection_ref = self.db.collection("titles").document(title_id).collection("occurrences")
        docs = collection_ref.stream()
        return [occurrence_from_dict(doc.to_dict()) for doc in docs]

    def delete(self, title_id: str, occurrence_id: str) -> None:
        doc_ref = self._get_occ_ref(title_id, occurrence_id)
        doc_ref.delete()

    def delete_by_title(self, title_id: str) -> None:
        collection_ref = self.db.collection("titles").document(title_id).collection("occurrences")
        docs = collection_ref.stream()
        batch = self.db.batch()
        count = 0
        for doc in docs:
            batch.delete(doc.reference)
            count += 1
            if count >= 450:
                batch.commit()
                batch = self.db.batch()
                count = 0
        if count > 0:
            batch.commit()


class FirestoreOmdbCacheRepository(OmdbCacheRepository):
    def __init__(self, db: Optional[firestore.firestore.Client] = None) -> None:
        self.db = db if db is not None else get_firestore_client()
        self.collection_ref = self.db.collection("omdbCache")

    def get(self, cache_key: str) -> Optional[OmdbCacheEntry]:
        doc_ref = self.collection_ref.document(cache_key)
        snapshot = doc_ref.get()
        if snapshot.exists:
            return cache_entry_from_dict(snapshot.to_dict())
        return None

    def get_many(self, cache_keys: List[str]) -> Dict[str, OmdbCacheEntry]:
        keys = list(set(cache_keys))
        if not keys:
            return {}
        result: Dict[str, OmdbCacheEntry] = {}
        chunk_size = 500
        for i in range(0, len(keys), chunk_size):
            chunk = keys[i : i + chunk_size]
            doc_refs = [self.collection_ref.document(k) for k in chunk]
            snapshots = self.db.get_all(doc_refs)
            for snap in snapshots:
                if snap.exists:
                    result[snap.id] = cache_entry_from_dict(snap.to_dict())
        return result

    def set(self, cache_key: str, entry: OmdbCacheEntry) -> None:
        doc_ref = self.collection_ref.document(cache_key)
        doc_ref.set(entry.to_dict())


class FirestoreScanRunRepository(ScanRunRepository):
    def __init__(self, db: Optional[firestore.firestore.Client] = None) -> None:
        self.db = db if db is not None else get_firestore_client()
        self.collection_ref = self.db.collection("scanRuns")

    def get(self, run_id: str) -> Optional[ScanRun]:
        doc_ref = self.collection_ref.document(run_id)
        snapshot = doc_ref.get()
        if snapshot.exists:
            return scan_run_from_dict(snapshot.to_dict())
        return None

    def upsert(self, run_id: str, run: ScanRun) -> None:
        doc_ref = self.collection_ref.document(run_id)
        doc_ref.set(run.to_dict())

    def list_all(self) -> List[ScanRun]:
        docs = self.collection_ref.stream()
        return [scan_run_from_dict(doc.to_dict()) for doc in docs]


class FirestoreParseLogRepository(ParseLogRepository):
    def __init__(self, db: Optional[firestore.firestore.Client] = None) -> None:
        self.db = db if db is not None else get_firestore_client()
        self.collection_ref = self.db.collection("parseLogs")

    def add(self, log: ParseLog) -> None:
        doc_ref = self.collection_ref.document(log.id)

        @firestore.transactional
        def _add_tx(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            stored_log = log
            if snapshot.exists:
                existing = parse_log_from_dict(snapshot.to_dict(), doc_id=snapshot.id)
                stored_log = merge_parse_logs(existing, log)
            if stored_log.retry_state is None:
                stored_log.retry_state = effective_retry_state(stored_log)
            transaction.set(doc_ref, stored_log.to_dict())

        transaction = self.db.transaction()
        _add_tx(transaction)

    def add_many(self, logs: List[ParseLog]) -> None:
        for log in logs:
            self.add(log)

    def prune_older_than(self, cutoff: datetime.datetime) -> int:
        query = self.collection_ref.where("processedAt", "<", cutoff)
        docs = list(query.stream())
        deleted_count = 0
        for doc in docs:
            log = parse_log_from_dict(doc.to_dict(), doc_id=doc.id)
            if effective_retry_state(log) != "retryable":
                doc.reference.delete()
                deleted_count += 1
        return deleted_count

    def list_recent(self, limit: int = 100) -> List[ParseLog]:
        query = self.collection_ref.order_by("processedAt", direction=firestore.Query.DESCENDING).limit(limit)
        docs = query.stream()
        return [parse_log_from_dict(doc.to_dict(), doc_id=doc.id) for doc in docs]

    def list_retryable(
        self,
        limit: int = 200,
        cursor: Optional[RetryCursor] = None,
    ) -> RetryPage:
        if limit <= 0 or limit > 500:
            raise ValueError("retry page limit must be between 1 and 500")
        base_query = self.collection_ref.order_by(
            "processedAt", direction=firestore.Query.DESCENDING
        ).order_by(
            FieldPath.document_id(), direction=firestore.Query.DESCENDING
        )
        if cursor is not None:
            base_query = base_query.start_after({
                "processedAt": cursor.processed_at,
                FieldPath.document_id(): self.collection_ref.document(cursor.log_id),
            })

        selected: List[ParseLog] = []
        query = base_query
        chunk_size = min(max(limit * 2, 25), 500)
        while len(selected) <= limit:
            docs = list(query.limit(chunk_size).stream())
            if not docs:
                break
            for doc in docs:
                log = parse_log_from_dict(doc.to_dict(), doc_id=doc.id)
                if effective_retry_state(log) == "retryable":
                    selected.append(log)
                    if len(selected) > limit:
                        break
            if len(selected) > limit or len(docs) < chunk_size:
                break
            query = base_query.start_after(docs[-1])

        page_items = selected[:limit]
        next_cursor = None
        if len(selected) > limit:
            last = page_items[-1]
            next_cursor = RetryCursor(last.processed_at, last.id)
        return RetryPage(page_items, next_cursor)


class FirestoreManualMappingRepository(ManualMappingRepository):
    def __init__(self, db: Optional[firestore.firestore.Client] = None) -> None:
        self.db = db if db is not None else get_firestore_client()
        self.collection_ref = self.db.collection("manualMappings")

    def get_all(self) -> List[ManualMapping]:
        docs = self.collection_ref.stream()
        return [manual_mapping_from_dict(doc.to_dict(), doc_id=doc.id) for doc in docs]

    def set(self, mapping: ManualMapping) -> None:
        doc_ref = self.collection_ref.document(mapping.id)
        doc_ref.set(mapping.to_dict())

    def delete(self, mapping_id: str) -> None:
        doc_ref = self.collection_ref.document(mapping_id)
        doc_ref.delete()


class FirestoreAuditProposalRepository(AuditProposalRepository):
    def __init__(self, db: Optional[firestore.firestore.Client] = None) -> None:
        self.db = db if db is not None else get_firestore_client()
        self.collection_ref = self.db.collection("auditProposals")

    def get(self, proposal_id: str) -> Optional[AuditProposal]:
        doc_ref = self.collection_ref.document(proposal_id)
        snapshot = doc_ref.get()
        if snapshot.exists:
            data = snapshot.to_dict()
            if not data:
                return None
            return audit_proposal_from_dict(data, doc_id=snapshot.id)
        return None

    def upsert(self, proposal: AuditProposal) -> None:
        doc_ref = self.collection_ref.document(proposal.id)

        @firestore.transactional
        def _upsert_tx(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            incoming = copy.deepcopy(proposal)
            if snapshot.exists:
                data = snapshot.to_dict() or {}
                existing = audit_proposal_from_dict(data, doc_id=snapshot.id)
                if not is_valid_proposal_status_transition(existing.status, incoming.status):
                    raise InvalidStatusTransitionError(
                        f"Cannot transition proposal '{incoming.id}' from '{existing.status}' to '{incoming.status}'"
                    )
                incoming.created_at = min(existing.created_at, incoming.created_at)
            transaction.set(doc_ref, incoming.to_dict())

        transaction = self.db.transaction()
        _upsert_tx(transaction)

    def list_by_status(self, status: str, limit: int = 100) -> List[AuditProposal]:
        if limit <= 0:
            return []
        query = self.collection_ref.where("status", "==", status).limit(limit)
        docs = query.stream()
        return [audit_proposal_from_dict(doc.to_dict(), doc_id=doc.id) for doc in docs]

    def list_by_source_title(self, source_title_id: str) -> List[AuditProposal]:
        query = self.collection_ref.where("sourceTitleId", "==", source_title_id)
        docs = query.stream()
        return [audit_proposal_from_dict(doc.to_dict(), doc_id=doc.id) for doc in docs]

    def list_all(self) -> List[AuditProposal]:
        docs = self.collection_ref.stream()
        return [audit_proposal_from_dict(doc.to_dict(), doc_id=doc.id) for doc in docs]

    def acquire_lease(self, proposal_id: str, lease_duration: datetime.timedelta, now: datetime.datetime) -> bool:
        doc_ref = self.collection_ref.document(proposal_id)

        @firestore.transactional
        def _acquire_tx(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            if not snapshot.exists:
                return False
                
            data = snapshot.to_dict() or {}
            existing = audit_proposal_from_dict(data, doc_id=snapshot.id)
            
            if existing.status == "applying":
                if existing.leased_until is None or now >= existing.leased_until:
                    existing.status = "failed"
                    existing.leased_until = None
                    existing.updated_at = now
                    transaction.set(doc_ref, existing.to_dict())
                    return False
                else:
                    return False
                    
            if existing.status != "approved":
                return False
                
            # Prevent concurrent moves for the same source title
            applying_query = self.collection_ref.where(
                "sourceTitleId", "==", existing.source_title_id
            ).where("status", "==", "applying")
            for doc in applying_query.stream(transaction=transaction):
                if doc.id != snapshot.id:
                    other_data = doc.to_dict() or {}
                    other_leased_until = other_data.get("leasedUntil")
                    if other_leased_until is not None and now < other_leased_until:
                        return False
                
            existing.status = "applying"
            existing.leased_until = now + lease_duration
            existing.updated_at = now
            transaction.set(doc_ref, existing.to_dict())
            return True

        transaction = self.db.transaction()
        return _acquire_tx(transaction)

    def delete(self, proposal_id: str) -> None:
        doc_ref = self.collection_ref.document(proposal_id)
        doc_ref.delete()


