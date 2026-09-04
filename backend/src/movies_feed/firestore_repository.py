import copy
import os
import datetime
from typing import Any, Dict, List, Optional
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.field_path import FieldPath

from .audit_proposal import (
    AuditProposal,
    InvalidStatusTransitionError,
    VALID_AUDIT_PROPOSAL_STATUSES,
    audit_proposal_from_dict,
    is_valid_proposal_status_transition,
)
from .firestore_codecs import (
    cache_entry_from_dict,
    manual_mapping_from_dict,
    occurrence_from_dict,
    parse_log_from_dict,
    scan_run_from_dict,
    rss_snapshot_state_to_dict,
    title_from_dict,
)
from .models import (
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
from .repository import (
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

            import shutil
            import subprocess
            import tempfile
            from pathlib import Path

            key_path = Path(tempfile.gettempdir()) / "mediadock_dummy_key.pem"
            if not key_path.exists():
                openssl_path = shutil.which("openssl")
                if openssl_path:
                    subprocess.run(
                        [openssl_path, "genrsa", "-out", str(key_path), "2048"],
                        check=True,
                        capture_output=True,
                    )
                else:
                    from cryptography.hazmat.primitives import serialization
                    from cryptography.hazmat.primitives.asymmetric import rsa

                    private_key = rsa.generate_private_key(
                        public_exponent=65537,
                        key_size=2048,
                    )
                    key_path.write_bytes(
                        private_key.private_bytes(
                            encoding=serialization.Encoding.PEM,
                            format=serialization.PrivateFormat.TraditionalOpenSSL,
                            encryption_algorithm=serialization.NoEncryption(),
                        )
                    )

            private_key_content = key_path.read_text(encoding="utf-8")

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


class FirestoreRssSnapshotRepository(RssSnapshotRepository):
    """Stores immutable RSS generations behind an atomic current pointer."""

    _MAX_BATCH_WRITES = 450

    def __init__(self, db: Optional[firestore.firestore.Client] = None) -> None:
        self.db = db if db is not None else get_firestore_client()
        self.collection_ref = self.db.collection("rssSnapshots")
        self.state_ref = self.db.collection("rssSnapshotState").document("current")

    def _delete_staged_items(self, items_ref: Any) -> None:
        existing_docs = list(items_ref.stream())
        for offset in range(0, len(existing_docs), self._MAX_BATCH_WRITES):
            batch = self.db.batch()
            for item_doc in existing_docs[offset : offset + self._MAX_BATCH_WRITES]:
                batch.delete(item_doc.reference)
            batch.commit()

    def publish(
        self,
        snapshot_id: str,
        snapshot: RssSnapshot,
        items: List[RssSnapshotItem],
    ) -> None:
        if snapshot.id != snapshot_id:
            raise ValueError("snapshot_id must match snapshot.id")
        if snapshot.item_count != len(items):
            raise ValueError("snapshot item_count must match the number of items")
        if len({item.title_id for item in items}) != len(items):
            raise ValueError("RSS snapshot items must have unique title IDs")
        if {item.rss_position for item in items} != set(range(len(items))):
            raise ValueError("RSS snapshot positions must be contiguous")

        snapshot_ref = self.collection_ref.document(snapshot_id)
        items_ref = snapshot_ref.collection("items")
        current_state = self.state_ref.get()
        current_state_data = current_state.to_dict() if current_state.exists else {}
        existing_snapshot = snapshot_ref.get()
        existing_snapshot_data = existing_snapshot.to_dict() if existing_snapshot.exists else {}

        if (
            current_state_data.get("snapshotId") == snapshot_id
            and existing_snapshot_data.get("status") == "ready"
        ):
            return

        if current_state_data.get("snapshotId") == snapshot_id:
            raise RuntimeError("cannot replace the snapshot currently exposed by the pointer")

        if existing_snapshot.exists:
            self._delete_staged_items(items_ref)

        staged_data = {
            **snapshot.to_dict(),
            "status": "staging",
            "schemaVersion": 1,
        }
        snapshot_ref.set(staged_data)

        for offset in range(0, len(items), self._MAX_BATCH_WRITES):
            batch = self.db.batch()
            for item in items[offset : offset + self._MAX_BATCH_WRITES]:
                batch.set(items_ref.document(item.title_id), item.to_dict())
            batch.commit()

        ready_data = {
            **snapshot.to_dict(),
            "status": "ready",
            "schemaVersion": 1,
        }
        pointer_data = rss_snapshot_state_to_dict(snapshot)

        @firestore.transactional
        def _promote(transaction):
            transaction.set(snapshot_ref, ready_data)
            transaction.set(self.state_ref, pointer_data)

        transaction = self.db.transaction()
        _promote(transaction)


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

    def refresh_from_audit(self, proposal: AuditProposal) -> None:
        doc_ref = self.collection_ref.document(proposal.id)

        @firestore.transactional
        def _refresh_tx(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            if not snapshot.exists:
                transaction.set(doc_ref, copy.deepcopy(proposal).to_dict())
                return

            existing = audit_proposal_from_dict(snapshot.to_dict() or {}, doc_id=snapshot.id)
            if existing.status != "pending":
                return

            refreshed = copy.deepcopy(proposal)
            refreshed.created_at = existing.created_at
            refreshed.status = existing.status
            refreshed.leased_until = existing.leased_until
            transaction.set(doc_ref, refreshed.to_dict())

        transaction = self.db.transaction()
        _refresh_tx(transaction)

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


