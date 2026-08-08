import os
import datetime
from typing import Any, Dict, List, Optional
import firebase_admin
from firebase_admin import credentials, firestore

from .models import OmdbCacheEntry, Occurrence, ParseLog, ScanRun, Title
from .repository import (
    OmdbCacheRepository,
    OccurrenceRepository,
    ParseLogRepository,
    ScanRunRepository,
    TitleRepository,
    merge_occurrences,
    merge_titles,
)


def get_firestore_client(project_id: str = "demo-project") -> firestore.firestore.Client:
    """Initializes and returns a Firestore client.

    Supports the local Firestore emulator if FIRESTORE_EMULATOR_HOST is set.
    """
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
    return firestore.client()


def title_from_dict(d: dict) -> Title:
    """Reconstructs a Title model from a camelCase dictionary retrieved from Firestore."""
    return Title(
        title=d["title"],
        normalized_title=d["normalizedTitle"],
        year=d.get("year"),
        media_type=d["mediaType"],
        first_seen_at=d["firstSeenAt"],
        last_seen_at=d["lastSeenAt"],
        updated_at=d["updatedAt"],
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


def parse_log_from_dict(d: dict) -> ParseLog:
    """Reconstructs a ParseLog model from a camelCase dictionary retrieved from Firestore."""
    return ParseLog(
        id=d["id"],
        raw_title=d["rawTitle"],
        feed_name=d["feedName"],
        parsed_successfully=d["parsedSuccessfully"],
        parsed_title=d.get("parsedTitle"),
        parsed_year=d.get("parsedYear"),
        omdb_status=d["omdbStatus"],
        ignored=d["ignored"],
        ignore_reason=d.get("ignoreReason"),
        processed_at=d["processedAt"],
    )



class FirestoreTitleRepository(TitleRepository):
    def __init__(self, db: Optional[firestore.firestore.Client] = None) -> None:
        self.db = db if db is not None else get_firestore_client()
        self.collection_ref = self.db.collection("titles")

    def get(self, title_id: str) -> Optional[Title]:
        doc_ref = self.collection_ref.document(title_id)
        snapshot = doc_ref.get()
        if snapshot.exists:
            return title_from_dict(snapshot.to_dict())
        return None

    def get_many(self, title_ids: List[str]) -> Dict[str, Title]:
        ids = list(set(title_ids))
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
                    result[snap.id] = title_from_dict(snap.to_dict())
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
        if not titles:
            return
        chunk_size = 500
        for i in range(0, len(titles), chunk_size):
            chunk = titles[i : i + chunk_size]
            batch = self.db.batch()
            for title_id, title in chunk:
                doc_ref = self.collection_ref.document(title_id)
                batch.set(doc_ref, title.to_dict())
            batch.commit()

    def list_all(self) -> List[Title]:
        docs = self.collection_ref.stream()
        return [title_from_dict(doc.to_dict()) for doc in docs]


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
        if not occurrences:
            return
        chunk_size = 500
        for i in range(0, len(occurrences), chunk_size):
            chunk = occurrences[i : i + chunk_size]
            batch = self.db.batch()
            for title_id, occurrence_id, occ in chunk:
                doc_ref = self._get_occ_ref(title_id, occurrence_id)
                batch.set(doc_ref, occ.to_dict())
            batch.commit()

    def list_by_title(self, title_id: str) -> List[Occurrence]:
        collection_ref = self.db.collection("titles").document(title_id).collection("occurrences")
        docs = collection_ref.stream()
        return [occurrence_from_dict(doc.to_dict()) for doc in docs]


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
        doc_ref.set(log.to_dict())

    def add_many(self, logs: List[ParseLog]) -> None:
        if not logs:
            return
        chunk_size = 500
        for i in range(0, len(logs), chunk_size):
            chunk = logs[i : i + chunk_size]
            batch = self.db.batch()
            for log in chunk:
                doc_ref = self.collection_ref.document(log.id)
                batch.set(doc_ref, log.to_dict())
            batch.commit()

    def prune_older_than(self, cutoff: datetime.datetime) -> int:
        query = self.collection_ref.where("processedAt", "<", cutoff)
        docs = list(query.stream())
        deleted_count = 0
        for doc in docs:
            doc.reference.delete()
            deleted_count += 1
        return deleted_count

    def list_recent(self, limit: int = 100) -> List[ParseLog]:
        query = self.collection_ref.order_by("processedAt", direction=firestore.Query.DESCENDING).limit(limit)
        docs = query.stream()
        return [parse_log_from_dict(doc.to_dict()) for doc in docs]

