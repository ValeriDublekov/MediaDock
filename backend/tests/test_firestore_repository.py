import os
import datetime
import unittest
from typing import Optional

# We must import firestore to handle emulator connection or check if emulator is set
from google.cloud import firestore as cloud_firestore

from movies_feed import (
    FirestoreTitleRepository,
    FirestoreOccurrenceRepository,
    FirestoreOmdbCacheRepository,
    FirestoreScanRunRepository,
    FirestoreParseLogRepository,
    FirestoreManualMappingRepository,
    get_firestore_client,
    Title,
    Occurrence,
    OmdbCacheEntry,
    ScanRun,
    ParseLog,
    ManualMapping,
    get_title_id,
    get_occurrence_id,
    get_cache_key,
)
from movies_feed.firestore_repository import (
    manual_mapping_from_dict,
    parse_log_from_dict,
)


class DictDeserializationTests(unittest.TestCase):
    def test_manual_mapping_deserialization_with_and_without_id_key(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Document with 'id' inside dictionary
        d1 = {"id": "map-1", "rawTitle": "Movie 2024", "imdbId": "tt1234567", "createdAt": now}
        m1 = manual_mapping_from_dict(d1, doc_id="doc-fallback-1")
        self.assertEqual(m1.id, "map-1")
        self.assertEqual(m1.raw_title, "Movie 2024")
        self.assertEqual(m1.imdb_id, "tt1234567")

        # Document without 'id' key (e.g., created directly in Firestore / Web Frontend)
        d2 = {"rawTitle": "Web Movie 2024", "imdbId": "tt7654321", "createdAt": now}
        m2 = manual_mapping_from_dict(d2, doc_id="doc-web-456")
        self.assertEqual(m2.id, "doc-web-456")
        self.assertEqual(m2.raw_title, "Web Movie 2024")

    def test_parse_log_deserialization_with_and_without_id_key(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)

        # Document without 'id' key
        d = {"rawTitle": "Raw 1", "feedName": "Feed 1", "parsedSuccessfully": True}
        p = parse_log_from_dict(d, doc_id="log-doc-123")
        self.assertEqual(p.id, "log-doc-123")
        self.assertEqual(p.raw_title, "Raw 1")
        self.assertEqual(p.feed_name, "Feed 1")
        self.assertTrue(p.parsed_successfully)


@unittest.skipIf(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"),
    "Firestore emulator is not running/configured in environment",
)
class FirestoreRepositoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Get Firestore client connected to emulator
        cls.db = get_firestore_client(project_id="demo-project")
        cls.utc = datetime.timezone.utc

    def setUp(self) -> None:
        # Clear collections before each test to ensure fresh state
        self._clear_collection("titles")
        self._clear_collection("omdbCache")
        self._clear_collection("scanRuns")
        self._clear_collection("parseLogs")
        self._clear_collection("manualMappings")

        self.base_time = datetime.datetime(2026, 8, 7, 10, 0, 0, tzinfo=self.utc)
        self.earlier_time = datetime.datetime(2026, 8, 7, 9, 0, 0, tzinfo=self.utc)
        self.later_time = datetime.datetime(2026, 8, 7, 11, 0, 0, tzinfo=self.utc)

    def _clear_collection(self, collection_name: str) -> None:
        # Helper to recursively delete all documents in a collection
        docs = self.db.collection(collection_name).stream()
        for doc in docs:
            # Delete occurrences subcollection for titles
            if collection_name == "titles":
                sub_docs = doc.reference.collection("occurrences").stream()
                for sub_doc in sub_docs:
                    sub_doc.reference.delete()
            doc.reference.delete()

    def test_title_repository_persistence_and_idempotence(self) -> None:
        repo = FirestoreTitleRepository(self.db)
        title_id = get_title_id("tt0133093", "the matrix", 1999, "movie")

        title = Title(
            title="The Matrix",
            normalized_title="the matrix",
            year=1999,
            media_type="movie",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
            updated_at=self.base_time,
            imdb_id="tt0133093",
            imdb_rating=8.7,
            genres=["Action", "Sci-Fi"],
        )

        # 1. Test basic persistence
        repo.upsert(title_id, title)
        fetched = repo.get(title_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "The Matrix")
        self.assertEqual(fetched.imdb_rating, 8.7)
        self.assertEqual(fetched.genres, ["Action", "Sci-Fi"])
        self.assertEqual(fetched.first_seen_at.replace(tzinfo=self.utc), self.base_time)

        # 2. Test duplicate upsert (idempotency & no duplicate records)
        repo.upsert(title_id, title)
        titles = repo.list_all()
        self.assertEqual(len(titles), 1, "Duplicate upsert created a duplicate record")

        # 3. Test update / merge semantics (timestamp behavior)
        updated_title = Title(
            title="The Matrix Refreshed",
            normalized_title="the matrix",
            year=1999,
            media_type="movie",
            first_seen_at=self.later_time,
            last_seen_at=self.later_time,
            updated_at=self.later_time,
            imdb_id="tt0133093",
            imdb_rating=8.8,
            plot="A cool plot",
        )
        repo.upsert(title_id, updated_title)

        fetched_updated = repo.get(title_id)
        self.assertEqual(fetched_updated.imdb_rating, 8.8)
        self.assertEqual(fetched_updated.plot, "A cool plot")
        # should preserve earliest first_seen_at and latest last_seen_at
        self.assertEqual(fetched_updated.first_seen_at.replace(tzinfo=self.utc), self.base_time)
        self.assertEqual(fetched_updated.last_seen_at.replace(tzinfo=self.utc), self.later_time)

    def test_occurrence_repository_persistence_and_idempotence(self) -> None:
        title_repo = FirestoreTitleRepository(self.db)
        title_id = "test-title-occ"
        title = Title(
            title="Test Movie",
            normalized_title="test movie",
            year=2026,
            media_type="movie",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
            updated_at=self.base_time,
        )
        title_repo.upsert(title_id, title)

        repo = FirestoreOccurrenceRepository(self.db)
        occ_id = get_occurrence_id("feed-entry-123", "https://torrent.com/1")

        occ = Occurrence(
            source_feed_id="feed-1",
            source_feed_name="Feed 1",
            feed_entry_id="feed-entry-123",
            torrent_url="https://torrent.com/1",
            raw_title="Test Movie 2026 1080p",
            quality="1080p",
            rip_type="BDRip",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
        )

        # 1. Test basic persistence
        repo.upsert(title_id, occ_id, occ)
        fetched = repo.get(title_id, occ_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.source_feed_name, "Feed 1")
        self.assertEqual(fetched.first_seen_at.replace(tzinfo=self.utc), self.base_time)

        # 2. Test duplicate upsert (idempotency)
        repo.upsert(title_id, occ_id, occ)
        occurrences = repo.list_by_title(title_id)
        self.assertEqual(len(occurrences), 1, "Duplicate upsert created duplicate occurrence")

        # 3. Test timestamp merging
        later_occ = Occurrence(
            source_feed_id="feed-1",
            source_feed_name="Feed 1",
            feed_entry_id="feed-entry-123",
            torrent_url="https://torrent.com/1",
            raw_title="Test Movie 2026 1080p",
            quality="1080p",
            rip_type="BDRip",
            first_seen_at=self.later_time,
            last_seen_at=self.later_time,
        )
        repo.upsert(title_id, occ_id, later_occ)

        fetched_updated = repo.get(title_id, occ_id)
        self.assertEqual(fetched_updated.first_seen_at.replace(tzinfo=self.utc), self.base_time)
        self.assertEqual(fetched_updated.last_seen_at.replace(tzinfo=self.utc), self.later_time)

    def test_omdb_cache_repository_persistence_and_expiry(self) -> None:
        repo = FirestoreOmdbCacheRepository(self.db)
        cache_key = get_cache_key("inception", 2010)

        entry = OmdbCacheEntry(
            lookup_title="inception",
            lookup_year=2010,
            status="found",
            payload={"Title": "Inception"},
            fetched_at=self.base_time,
            expires_at=self.later_time,
        )

        # Test persistence
        repo.set(cache_key, entry)
        fetched = repo.get(cache_key)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.lookup_title, "inception")
        self.assertEqual(fetched.status, "found")
        self.assertEqual(fetched.payload, {"Title": "Inception"})
        self.assertEqual(fetched.expires_at.replace(tzinfo=self.utc), self.later_time)

        # Cache expiry logic can be tested locally using the expiration timestamp
        is_expired = fetched.expires_at.replace(tzinfo=self.utc) < self.later_time
        self.assertFalse(is_expired)
        
        is_expired_later = fetched.expires_at.replace(tzinfo=self.utc) < (self.later_time + datetime.timedelta(seconds=1))
        self.assertTrue(is_expired_later)

    def test_scan_run_repository_persistence(self) -> None:
        repo = FirestoreScanRunRepository(self.db)
        run_id = "run-123"

        run = ScanRun(
            started_at=self.base_time,
            finished_at=None,
            status="running",
            trigger="schedule",
            feeds_processed=2,
            entries_seen=10,
        )

        # Test persistence
        repo.upsert(run_id, run)
        fetched = repo.get(run_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.status, "running")
        self.assertEqual(fetched.feeds_processed, 2)

        # Test updates
        run.finished_at = self.later_time
        run.status = "succeeded"
        run.titles_created = 3
        repo.upsert(run_id, run)

        fetched_updated = repo.get(run_id)
        self.assertEqual(fetched_updated.status, "succeeded")
        self.assertEqual(fetched_updated.titles_created, 3)
        self.assertEqual(fetched_updated.finished_at.replace(tzinfo=self.utc), self.later_time)

    def test_parse_log_repository_persistence_and_pruning(self) -> None:
        repo = FirestoreParseLogRepository(self.db)
        log_id = "log-123"

        log = ParseLog(
            id=log_id,
            raw_title="The Matrix 1999 1080p BDRip",
            feed_name="Movies Feed",
            parsed_successfully=True,
            parsed_title="The Matrix",
            parsed_year=1999,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            processed_at=self.base_time,
            decision="needs_review",
        )

        repo.add(log)
        recent = repo.list_recent()
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].raw_title, "The Matrix 1999 1080p BDRip")
        self.assertEqual(recent[0].decision, "needs_review")

        # Test pruning
        cutoff = self.base_time + datetime.timedelta(hours=1)
        deleted = repo.prune_older_than(cutoff)
        self.assertEqual(deleted, 1)

        remaining = repo.list_recent()
        self.assertEqual(len(remaining), 0)

    def test_manual_mapping_repository_persistence(self) -> None:
        repo = FirestoreManualMappingRepository(self.db)
        mapping_id = "mapping-123"

        # 1. Test set & get_all with standard model
        mapping = ManualMapping(
            id=mapping_id,
            raw_title="Some Movie 2024",
            imdb_id="tt1234567",
            created_at=self.base_time,
            parsed_title="Some Movie",
            parsed_year=2024,
        )
        repo.set(mapping)

        # 2. Test reading a document created without explicit 'id' inside doc.to_dict() (e.g. from web frontend)
        self.db.collection("manualMappings").document("web-doc-456").set({
            "rawTitle": "Web Created Title",
            "imdbId": "tt7654321",
            "createdAt": self.base_time,
        })

        all_mappings = repo.get_all()
        self.assertEqual(len(all_mappings), 2)
        by_id = {m.id: m for m in all_mappings}
        self.assertIn("mapping-123", by_id)
        self.assertIn("web-doc-456", by_id)
        self.assertEqual(by_id["web-doc-456"].raw_title, "Web Created Title")
        self.assertEqual(by_id["web-doc-456"].imdb_id, "tt7654321")

        # 3. Test delete
        repo.delete(mapping_id)
        remaining = repo.get_all()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].id, "web-doc-456")

