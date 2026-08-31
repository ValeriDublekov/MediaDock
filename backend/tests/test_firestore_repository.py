import os
import datetime
import unittest
from typing import Optional

try:
    from . import _test_stubs
except ImportError:
    import _test_stubs

# We must import firestore to handle emulator connection or check if emulator is set
from google.cloud import firestore as cloud_firestore

from movies_feed import (
    AuditProposal,
    FirestoreAuditProposalRepository,
    FirestoreTitleRepository,
    FirestoreOccurrenceRepository,
    FirestoreOmdbCacheRepository,
    FirestoreScanRunRepository,
    FirestoreParseLogRepository,
    FirestoreManualMappingRepository,
    InvalidStatusTransitionError,
    get_firestore_client,
    Title,
    Occurrence,
    OmdbCacheEntry,
    ScanRun,
    SourceContext,
    ParseLog,
    ParseLogResolution,
    ManualMapping,
    get_title_id,
    get_occurrence_id,
    get_cache_key,
    BroadcastRange,
)
from movies_feed.firestore_repository import (
    audit_proposal_from_dict,
    manual_mapping_from_dict,
    occurrence_from_dict,
    parse_log_from_dict,
    title_from_dict,
)


class DictDeserializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.utc = datetime.timezone.utc
        self.published_at = datetime.datetime(2026, 8, 6, 8, 0, tzinfo=self.utc)
        self.observed_at = datetime.datetime(2026, 8, 7, 10, 0, tzinfo=self.utc)

    def make_source_context(
        self,
        source_published_at: Optional[datetime.datetime] = None,
    ) -> SourceContext:
        return SourceContext(
            source_feed_id="movies-feed",
            source_feed_name="Movies Feed",
            feed_type="movie",
            feed_entry_id="entry-123",
            torrent_url="https://rutracker.org/forum/viewtopic.php?t=123",
            raw_title="Example Film [2026]",
            source_published_at=source_published_at,
            observed_at=self.observed_at,
        )

    def test_occurrence_source_context_round_trip(self) -> None:
        first_seen_at = self.observed_at + datetime.timedelta(minutes=1)
        last_seen_at = self.observed_at + datetime.timedelta(minutes=2)
        source_context = self.make_source_context(self.published_at)
        occurrence = Occurrence(
            source_feed_id="movies-feed",
            source_feed_name="Movies Feed",
            feed_entry_id="entry-123",
            torrent_url="https://rutracker.org/forum/viewtopic.php?t=123",
            raw_title="Example Film [2026]",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=first_seen_at,
            last_seen_at=last_seen_at,
            source_context=source_context,
        )

        restored = occurrence_from_dict(occurrence.to_dict())

        self.assertEqual(restored.source_context, source_context)
        self.assertEqual(restored.source_context.source_published_at, self.published_at)
        self.assertEqual(restored.source_context.observed_at, self.observed_at)
        self.assertEqual(restored.first_seen_at, first_seen_at)
        self.assertEqual(restored.last_seen_at, last_seen_at)

    def test_parse_log_source_context_and_event_kinds_round_trip(self) -> None:
        for event_kind in ("source", "audit_review"):
            with self.subTest(event_kind=event_kind):
                source_context = self.make_source_context(self.published_at)
                log = ParseLog(
                    id=f"log-{event_kind}",
                    raw_title="Example Film [2026]",
                    feed_name="Movies Feed",
                    parsed_successfully=True,
                    parsed_title="Example Film",
                    parsed_year=2026,
                    omdb_status="found",
                    ignored=False,
                    ignore_reason=None,
                    processed_at=self.observed_at + datetime.timedelta(minutes=3),
                    source_context=source_context,
                    event_kind=event_kind,
                )

                restored = parse_log_from_dict(log.to_dict())

                self.assertEqual(restored.source_context, source_context)
                self.assertEqual(restored.event_kind, event_kind)
                self.assertNotEqual(restored.processed_at, restored.source_context.observed_at)
                self.assertNotEqual(
                    restored.source_context.source_published_at,
                    restored.source_context.observed_at,
                )

    def test_null_source_publication_time_is_preserved(self) -> None:
        source_context = self.make_source_context()
        log = ParseLog(
            id="log-null-publication",
            raw_title="Example Film [2026]",
            feed_name="Movies Feed",
            parsed_successfully=True,
            parsed_title="Example Film",
            parsed_year=2026,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            processed_at=self.observed_at,
            source_context=source_context,
            event_kind="source",
        )

        serialized = log.to_dict()
        restored = parse_log_from_dict(serialized)

        self.assertIn("sourcePublishedAt", serialized)
        self.assertIsNone(serialized["sourcePublishedAt"])
        self.assertIsNone(restored.source_context.source_published_at)
        self.assertEqual(restored.source_context.observed_at, self.observed_at)

    def test_partial_source_context_does_not_erase_existing_flat_fields(self) -> None:
        source_context = SourceContext(
            source_feed_id=None,
            source_feed_name=None,
            feed_type="movie",
            feed_entry_id=None,
            torrent_url=None,
            raw_title=None,
            source_published_at=None,
            observed_at=self.observed_at,
        )
        occurrence = Occurrence(
            source_feed_id="movies-feed",
            source_feed_name="Movies Feed",
            feed_entry_id="entry-123",
            torrent_url="https://example.test/123",
            raw_title="Example Film [2026]",
            quality=None,
            rip_type=None,
            first_seen_at=self.observed_at,
            last_seen_at=self.observed_at,
            source_context=source_context,
        )
        log = ParseLog(
            id="partial-context",
            raw_title="Example Film [2026]",
            feed_name="Movies Feed",
            parsed_successfully=True,
            parsed_title="Example Film",
            parsed_year=2026,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            processed_at=self.observed_at,
            source_context=source_context,
            event_kind="source",
        )

        occurrence_data = occurrence.to_dict()
        log_data = log.to_dict()

        self.assertEqual(occurrence_data["sourceFeedId"], "movies-feed")
        self.assertEqual(occurrence_data["rawTitle"], "Example Film [2026]")
        self.assertEqual(log_data["rawTitle"], "Example Film [2026]")
        self.assertIn("sourcePublishedAt", occurrence_data)
        self.assertIsNone(occurrence_data["sourcePublishedAt"])

    def test_legacy_documents_do_not_invent_source_context(self) -> None:
        legacy_occurrence = occurrence_from_dict({
            "sourceFeedId": "legacy-feed",
            "sourceFeedName": "Legacy Feed",
            "feedEntryId": "legacy-entry",
            "torrentUrl": "https://example.test/legacy",
            "rawTitle": "Legacy Film 2020",
            "quality": None,
            "ripType": None,
            "firstSeenAt": self.published_at,
            "lastSeenAt": self.observed_at,
        })
        legacy_log = parse_log_from_dict({
            "rawTitle": "Legacy Film 2020",
            "feedName": "Legacy Feed",
            "parsedSuccessfully": True,
            "processedAt": self.observed_at,
        }, doc_id="legacy-log")

        self.assertIsNone(legacy_occurrence.source_context)
        self.assertIsNone(legacy_log.source_context)
        self.assertIsNone(legacy_log.event_kind)

    def test_title_type_fields_round_trip_and_legacy_derivation(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        broadcast_range = BroadcastRange(start_year=2007, end_year=2015, raw="2007-2015")
        title = Title(
            title="Mad Men",
            normalized_title="mad men",
            year=2007,
            media_type="series",
            first_seen_at=now,
            last_seen_at=now,
            updated_at=now,
            source_type="series",
            content_kind="standard",
            broadcast_range=broadcast_range,
        )

        restored = title_from_dict(title.to_dict())
        self.assertEqual(restored.source_type, "series")
        self.assertEqual(restored.content_kind, "standard")
        self.assertEqual(restored.broadcast_range, broadcast_range)

        legacy = title_from_dict({
            "title": "Planet Earth",
            "mediaType": "documentary",
        })
        self.assertEqual(legacy.source_type, "movie")
        self.assertEqual(legacy.content_kind, "documentary")

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

    def test_audit_proposal_deserialization_round_trip(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        d = {
            "id": "prop-123",
            "sourceTitleId": "tt0133093",
            "occurrenceIds": ["occ-1"],
            "rawTitleCluster": ["The Matrix 1999"],
            "currentMetadata": {"title": "Matrix"},
            "proposedMetadata": {"title": "The Matrix", "imdbId": "tt0133093"},
            "evidence": {"score": 0.98},
            "confidence": 0.98,
            "policyVersion": "v1",
            "createdAt": now,
            "updatedAt": now,
            "status": "pending",
        }
        proposal = audit_proposal_from_dict(d, doc_id="prop-fallback")
        self.assertEqual(proposal.id, "prop-123")
        self.assertEqual(proposal.source_title_id, "tt0133093")
        self.assertEqual(proposal.confidence, 0.98)
        self.assertEqual(proposal.status, "pending")


    def test_parse_log_deserialization_with_and_without_id_key(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)

        # Document without 'id' key
        d = {"rawTitle": "Raw 1", "feedName": "Feed 1", "parsedSuccessfully": True}
        p = parse_log_from_dict(d, doc_id="log-doc-123")
        self.assertEqual(p.id, "log-doc-123")
        self.assertEqual(p.raw_title, "Raw 1")
        self.assertEqual(p.feed_name, "Feed 1")
        self.assertTrue(p.parsed_successfully)

    def test_parse_log_retry_metadata_round_trip_and_legacy_derivation(self) -> None:
        resolution = ParseLogResolution(
            resolved_at=self.observed_at,
            outcome="matched",
            reason="catalog_match",
            title_id="title-1",
            occurrence_id="occurrence-1",
        )
        log = ParseLog(
            id="resolved-log",
            raw_title="Resolved Film",
            feed_name="Feed",
            parsed_successfully=True,
            parsed_title="Resolved Film",
            parsed_year=2026,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            processed_at=self.observed_at,
            retry_state="resolved",
            attempt_count=2,
            last_attempt_at=self.observed_at,
            resolution=resolution,
        )

        restored = parse_log_from_dict(log.to_dict())
        self.assertEqual(restored.retry_state, "resolved")
        self.assertEqual(restored.attempt_count, 2)
        self.assertEqual(restored.last_attempt_at, self.observed_at)
        self.assertEqual(restored.resolution, resolution)

        legacy_retryable = parse_log_from_dict({
            "rawTitle": "Legacy failure",
            "feedName": "Feed",
            "parsedSuccessfully": True,
            "omdbStatus": "not_found",
            "ignored": True,
            "ignoreReason": "omdb_not_found",
            "processedAt": self.observed_at,
        }, doc_id="legacy-retryable")
        unknown_legacy = parse_log_from_dict({
            "rawTitle": "Unknown failure",
            "feedName": "Feed",
            "parsedSuccessfully": False,
            "omdbStatus": "error",
            "ignored": True,
            "ignoreReason": "unknown_failure",
            "processedAt": self.observed_at,
            "retryState": "invalid",
            "attemptCount": -5,
        }, doc_id="legacy-unknown")
        self.assertEqual(legacy_retryable.retry_state, "retryable")
        self.assertEqual(unknown_legacy.retry_state, "terminal")
        self.assertEqual(unknown_legacy.attempt_count, 0)

        legacy_retryable_with_resolution = parse_log_from_dict({
            "rawTitle": "Contradictory failure",
            "feedName": "Feed",
            "parsedSuccessfully": True,
            "omdbStatus": "error",
            "ignored": True,
            "ignoreReason": "omdb_error",
            "processedAt": self.observed_at,
            "resolution": resolution.to_dict(),
        }, doc_id="legacy-contradictory")
        self.assertEqual(legacy_retryable_with_resolution.retry_state, "retryable")
        self.assertIsNone(legacy_retryable_with_resolution.resolution)


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

    def test_bulk_and_single_upserts_apply_the_same_merge_contract(self) -> None:
        title_repo = FirestoreTitleRepository(self.db)
        occurrence_repo = FirestoreOccurrenceRepository(self.db)
        source_context = SourceContext(
            source_feed_id="stable-feed",
            source_feed_name="Original Feed",
            feed_type="movie",
            feed_entry_id="entry-1",
            torrent_url="https://example.test/1",
            raw_title="Film 2020",
            source_published_at=self.earlier_time,
            observed_at=self.base_time,
        )
        initial_title = Title(
            title="Film",
            normalized_title="film",
            year=2020,
            media_type="movie",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
            updated_at=self.base_time,
        )
        initial_occurrence = Occurrence(
            source_feed_id="stable-feed",
            source_feed_name="Original Feed",
            feed_entry_id="entry-1",
            torrent_url="https://example.test/1",
            raw_title="Film 2020",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
            source_context=source_context,
        )
        title_repo.upsert("single-title", initial_title)
        title_repo.upsert_many([("bulk-title", initial_title)])
        occurrence_repo.upsert("single-title", "occurrence", initial_occurrence)
        occurrence_repo.upsert_many([("bulk-title", "occurrence", initial_occurrence)])

        updated_title = Title(
            **{
                **initial_title.__dict__,
                "first_seen_at": self.later_time,
                "last_seen_at": self.later_time,
                "updated_at": self.later_time,
            }
        )
        updated_occurrence = Occurrence(
            **{
                **initial_occurrence.__dict__,
                "source_feed_name": "Renamed Feed",
                "first_seen_at": self.later_time,
                "last_seen_at": self.later_time,
                "source_context": SourceContext(
                    **{
                        **source_context.__dict__,
                        "source_feed_name": "Renamed Feed",
                        "source_published_at": self.later_time,
                        "observed_at": self.later_time,
                    }
                ),
            }
        )
        title_repo.upsert("single-title", updated_title)
        title_repo.upsert_many([("bulk-title", updated_title)])
        occurrence_repo.upsert("single-title", "occurrence", updated_occurrence)
        occurrence_repo.upsert_many([("bulk-title", "occurrence", updated_occurrence)])

        self.assertEqual(title_repo.get("single-title"), title_repo.get("bulk-title"))
        single_occurrence = occurrence_repo.get("single-title", "occurrence")
        bulk_occurrence = occurrence_repo.get("bulk-title", "occurrence")
        self.assertEqual(single_occurrence, bulk_occurrence)
        self.assertEqual(single_occurrence.source_context.source_published_at, self.earlier_time)
        self.assertEqual(single_occurrence.source_context.observed_at, self.later_time)

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

    def test_parse_log_retry_pagination_and_retention(self) -> None:
        repo = FirestoreParseLogRepository(self.db)

        def add(log_id: str, reason: str, offset: int, retry_state=None) -> None:
            repo.add(ParseLog(
                id=log_id,
                raw_title=log_id,
                feed_name="Feed",
                parsed_successfully=True,
                parsed_title=log_id,
                parsed_year=2020,
                omdb_status="not_found",
                ignored=True,
                ignore_reason=reason,
                processed_at=self.base_time + datetime.timedelta(minutes=offset),
                retry_state=retry_state,
            ))

        add("retry-b", "omdb_not_found", 1)
        add("retry-a", "parse_error", 1)
        add("excluded", "excluded_country_or_genre", 2)
        add("resolved", "omdb_not_found", 3, "resolved")

        first = repo.list_retryable(limit=1)
        self.assertEqual([log.id for log in first.items], ["retry-b"])
        self.assertIsNotNone(first.next_cursor)
        second = repo.list_retryable(limit=1, cursor=first.next_cursor)
        self.assertEqual([log.id for log in second.items], ["retry-a"])
        self.assertIsNone(second.next_cursor)

        deleted = repo.prune_older_than(self.later_time)
        self.assertEqual(deleted, 2)
        self.assertEqual(
            [log.id for log in repo.list_retryable(limit=10).items],
            ["retry-b", "retry-a"],
        )

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

    def test_audit_proposal_lease_semantics(self) -> None:
        repo = FirestoreAuditProposalRepository(self.db)
        proposal_id = "test-lease-prop"
        source_title_id = "tt_lease_source"
        proposal = AuditProposal(
            id=proposal_id,
            source_title_id=source_title_id,
            occurrence_ids=["occ-1"],
            raw_title_cluster=["The Matrix"],
            current_metadata={"title": "Matrix"},
            proposed_metadata={"title": "The Matrix", "imdbId": "tt0133093"},
            evidence={"score": 0.98},
            confidence=0.98,
            policy_version="v1",
            created_at=self.base_time,
            updated_at=self.base_time,
            status="approved",
        )
        repo.upsert(proposal)

        # 1. Acquire lease
        lease_duration = datetime.timedelta(minutes=5)
        now1 = datetime.datetime.now(self.utc)
        acquired = repo.acquire_lease(proposal_id, lease_duration, now1)
        self.assertTrue(acquired)
        
        fetched = repo.get(proposal_id)
        self.assertEqual(fetched.status, "applying")
        self.assertIsNotNone(fetched.leased_until)
        
        # 2. Re-acquiring active lease should fail
        now2 = now1 + datetime.timedelta(minutes=1)
        acquired = repo.acquire_lease(proposal_id, lease_duration, now2)
        self.assertFalse(acquired)
        fetched2 = repo.get(proposal_id)
        self.assertEqual(fetched2.status, "applying") # Still applying

        # 3. Stale lease recovery
        now3 = now1 + datetime.timedelta(minutes=10) # Lease expired
        acquired = repo.acquire_lease(proposal_id, lease_duration, now3)
        self.assertFalse(acquired)
        fetched3 = repo.get(proposal_id)
        self.assertEqual(fetched3.status, "failed")
        self.assertIsNone(fetched3.leased_until)

        # 4. Concurrent source title test
        prop2 = copy.deepcopy(proposal)
        prop2.id = "test-lease-prop-2"
        prop2.status = "approved"
        repo.upsert(prop2)
        
        # Set prop1 back to approved
        proposal.status = "approved"
        repo.upsert(proposal)
        
        # Acquire prop1
        self.assertTrue(repo.acquire_lease(proposal_id, lease_duration, now1))
        
        # Attempt to acquire prop2 (same source title), should fail because prop1 is applying
        self.assertFalse(repo.acquire_lease("test-lease-prop-2", lease_duration, now1))
        
        # Cleanup
        repo.delete(proposal_id)
        repo.delete("test-lease-prop-2")

    def test_audit_proposal_repository_persistence(self) -> None:
        repo = FirestoreAuditProposalRepository(self.db)
        proposal_id = "prop-persistence-123"

        proposal = AuditProposal(
            id=proposal_id,
            source_title_id="tt0133093",
            occurrence_ids=["occ-1"],
            raw_title_cluster=["The Matrix 1999 1080p"],
            current_metadata={"title": "Matrix"},
            proposed_metadata={"title": "The Matrix", "imdbId": "tt0133093"},
            evidence={"score": 0.98},
            confidence=0.98,
            policy_version="v1",
            created_at=self.base_time,
            updated_at=self.base_time,
            status="pending",
        )

        repo.upsert(proposal)

        fetched = repo.get(proposal_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, proposal_id)
        self.assertEqual(fetched.source_title_id, "tt0133093")
        self.assertEqual(fetched.status, "pending")

        pending_list = repo.list_by_status("pending")
        self.assertEqual(len(pending_list), 1)
        self.assertEqual(pending_list[0].id, proposal_id)

        source_list = repo.list_by_source_title("tt0133093")
        self.assertEqual(len(source_list), 1)
        self.assertEqual(source_list[0].id, proposal_id)

        # Transition to approved
        proposal.status = "approved"
        repo.upsert(proposal)
        updated = repo.get(proposal_id)
        self.assertEqual(updated.status, "approved")

        # Invalid transition approved -> pending
        proposal.status = "pending"
        with self.assertRaises(InvalidStatusTransitionError):
            repo.upsert(proposal)

        repo.delete(proposal_id)
        self.assertIsNone(repo.get(proposal_id))


