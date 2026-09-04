import datetime
import hashlib
import unittest

from movies_feed import (
    AuditProposal,
    InvalidStatusTransitionError,
    OmdbCacheEntry,
    Occurrence,
    ParseLog,
    ParseLogResolution,
    RetryCursor,
    ScanRun,
    SourceContext,
    Title,
    get_audit_proposal_id,
    get_cache_key,
    get_fallback_title_id,
    get_occurrence_id,
    get_title_id,
    merge_parse_logs,
    merge_occurrences,
    merge_titles,
    normalize_title,
)
from backend.tests.fakes import (
    FakeAuditProposalRepository,
    FakeOmdbCacheRepository,
    FakeOccurrenceRepository,
    FakeParseLogRepository,
    FakeScanRunRepository,
    FakeTitleRepository,
)


class RepositoryAndIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.utc = datetime.timezone.utc
        self.base_time = datetime.datetime(2026, 8, 7, 10, 0, 0, tzinfo=self.utc)
        self.earlier_time = datetime.datetime(2026, 8, 7, 9, 0, 0, tzinfo=self.utc)
        self.later_time = datetime.datetime(2026, 8, 7, 11, 0, 0, tzinfo=self.utc)

    # --- 1. IDs and Normalization Tests ---

    def test_normalize_title(self) -> None:
        self.assertEqual(normalize_title("  The   Matrix  "), "the matrix")
        self.assertEqual(normalize_title("Inception"), "inception")
        self.assertEqual(normalize_title(""), "")
        self.assertEqual(normalize_title(None), "")

    def test_get_fallback_title_id(self) -> None:
        title = "the matrix"
        year = 1999
        media_type = "movie"
        expected_raw = f"v1:{title}:{year}:{media_type}"
        expected_hash = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest()

        fallback_id = get_fallback_title_id(title, year, media_type)
        self.assertEqual(fallback_id, expected_hash)

        # Test with empty year (None)
        fallback_no_year = get_fallback_title_id(title, None, media_type)
        raw_no_year = f"v1:{title}::{media_type}"
        self.assertEqual(fallback_no_year, hashlib.sha256(raw_no_year.encode("utf-8")).hexdigest())

    def test_get_title_id_prefers_imdb_id(self) -> None:
        # If imdb_id is present, it must be normalized (lowercase, striped)
        self.assertEqual(get_title_id("  tt1234567  ", "the matrix", 1999, "movie"), "tt1234567")
        self.assertEqual(get_title_id("TT0096283", "the matrix", 1999, "movie"), "tt0096283")

        # If imdb_id is empty/missing, fallback to deterministic hash
        fallback_id = get_fallback_title_id("the matrix", 1999, "movie")
        self.assertEqual(get_title_id("", "the matrix", 1999, "movie"), fallback_id)
        self.assertEqual(get_title_id(None, "the matrix", 1999, "movie"), fallback_id)

    def test_get_occurrence_id_uses_feed_entry_id(self) -> None:
        feed_entry_id = "some-feed-guid-123"
        torrent_url = "https://rutracker.org/forum/viewtopic.php?t=1"
        expected_raw = f"v1:{feed_entry_id}"
        expected_hash = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest()

        self.assertEqual(get_occurrence_id(feed_entry_id, torrent_url), expected_hash)

    def test_get_occurrence_id_falls_back_to_torrent_url(self) -> None:
        torrent_url = "https://rutracker.org/forum/viewtopic.php?t=1"
        expected_raw = f"v1:{torrent_url}"
        expected_hash = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest()

        self.assertEqual(get_occurrence_id("", torrent_url), expected_hash)
        self.assertEqual(get_occurrence_id(None, torrent_url), expected_hash)

    def test_get_cache_key(self) -> None:
        title = "  Inception  "
        year = 2010
        expected_raw = f"v2:cache:inception:{year}:unknown_year:unknown:"
        expected_hash = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest()

        self.assertEqual(get_cache_key(title, year), expected_hash)

    # --- 2. Merge Semantics Tests ---

    def test_merge_titles_preserves_first_seen_and_takes_latest_last_seen(self) -> None:
        existing = Title(
            title="The Matrix",
            normalized_title="the matrix",
            year=1999,
            media_type="movie",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
            updated_at=self.base_time,
            imdb_id="tt0133093",
            imdb_rating=8.7,
            imdb_votes=1500000,
        )

        incoming = Title(
            title="The Matrix Refreshed",
            normalized_title="the matrix",
            year=1999,
            media_type="movie",
            first_seen_at=self.later_time,
            last_seen_at=self.later_time,
            updated_at=self.later_time,
            imdb_id="tt0133093",
            imdb_rating=8.8,  # Refreshed metadata
            imdb_votes=1800000,  # Refreshed metadata
            plot="A computer hacker learns from mysterious rebels...",
        )

        merged = merge_titles(existing, incoming)

        # Semantics verification
        self.assertEqual(merged.first_seen_at, self.base_time)  # Preserves earlier
        self.assertEqual(merged.last_seen_at, self.later_time)  # Updates to latest
        self.assertEqual(merged.updated_at, self.later_time)  # Sets to refreshed update time
        self.assertEqual(merged.imdb_rating, 8.8)  # Uses refreshed
        self.assertEqual(merged.imdb_votes, 1800000)  # Uses refreshed
        self.assertEqual(merged.plot, "A computer hacker learns from mysterious rebels...")  # Refreshed is merged

        # Incoming can also have earlier first_seen_at, should preserve the earliest of both
        incoming_earlier = Title(
            title="The Matrix",
            normalized_title="the matrix",
            year=1999,
            media_type="movie",
            first_seen_at=self.earlier_time,
            last_seen_at=self.base_time,
            updated_at=self.base_time,
        )
        merged_earlier = merge_titles(existing, incoming_earlier)
        self.assertEqual(merged_earlier.first_seen_at, self.earlier_time)

    def test_merge_occurrences_updates_last_seen_at(self) -> None:
        published_at = self.base_time - datetime.timedelta(days=30)
        existing = Occurrence(
            source_feed_id="feed1",
            source_feed_name="Feed One",
            feed_entry_id="entry1",
            torrent_url="https://torrent1.com",
            raw_title="Movie.1999.RAW",
            quality="1080p",
            rip_type="BDRip",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
            source_context=SourceContext(
                source_feed_id="feed1",
                source_feed_name="Original Feed Name",
                feed_type="movie",
                feed_entry_id="entry1",
                torrent_url="https://torrent1.com",
                raw_title="Movie.1999.RAW",
                source_published_at=published_at,
                observed_at=self.base_time,
            ),
        )

        incoming = Occurrence(
            source_feed_id="feed1",
            source_feed_name="Feed One",
            feed_entry_id="entry1",
            torrent_url="https://torrent1.com",
            raw_title="Movie.1999.RAW",
            quality="1080p",
            rip_type="BDRip",
            first_seen_at=self.later_time,
            last_seen_at=self.later_time,
            source_context=SourceContext(
                source_feed_id="feed1",
                source_feed_name="Renamed Feed",
                feed_type="movie",
                feed_entry_id="entry1",
                torrent_url="https://torrent1.com/changed",
                raw_title="Changed title",
                source_published_at=self.later_time,
                observed_at=self.later_time,
            ),
        )

        merged = merge_occurrences(existing, incoming)
        self.assertEqual(merged.first_seen_at, self.base_time)
        self.assertEqual(merged.last_seen_at, self.later_time)
        self.assertEqual(merged.source_context.source_feed_id, "feed1")
        self.assertEqual(merged.source_context.source_feed_name, "Renamed Feed")
        self.assertEqual(merged.source_context.torrent_url, "https://torrent1.com")
        self.assertEqual(merged.source_context.source_published_at, published_at)
        self.assertEqual(merged.source_context.observed_at, self.later_time)

    def _validated_occurrence(self) -> Occurrence:
        return Occurrence(
            source_feed_id="feed1",
            source_feed_name="Feed One",
            feed_entry_id="entry1",
            torrent_url="https://torrent1.com",
            raw_title="Movie 2020 1080p",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
            source_context=SourceContext(
                source_feed_id="feed1",
                source_feed_name="Feed One",
                feed_type="movie",
                feed_entry_id="entry1",
                torrent_url="https://torrent1.com",
                raw_title="Movie 2020 1080p",
                source_published_at=self.earlier_time,
                observed_at=self.base_time,
            ),
            validation_status="valid",
            validation_policy_version="v1",
            validated_at=self.base_time,
            validation_reason="Stored match is valid",
        )

    def test_merge_occurrences_observation_only_preserves_validation(self) -> None:
        existing = self._validated_occurrence()
        incoming = self._validated_occurrence()
        incoming.last_seen_at = self.later_time
        incoming.source_context.observed_at = self.later_time
        incoming.validation_status = None
        incoming.validation_policy_version = None
        incoming.validated_at = None
        incoming.validation_reason = None

        merged = merge_occurrences(existing, incoming)

        self.assertEqual(merged.last_seen_at, self.later_time)
        self.assertEqual(merged.validation_status, "valid")
        self.assertEqual(merged.validation_policy_version, "v1")
        self.assertEqual(merged.validated_at, self.base_time)
        self.assertEqual(merged.validation_reason, "Stored match is valid")

    def test_merge_occurrences_match_relevant_changes_clear_validation(self) -> None:
        changes = {
            "raw title": lambda occurrence: setattr(occurrence, "raw_title", "Different Movie 2021 1080p"),
            "source feed id": lambda occurrence: setattr(occurrence, "source_feed_id", "feed2"),
            "source feed type": lambda occurrence: setattr(occurrence.source_context, "feed_type", "series"),
            "source year context": lambda occurrence: setattr(
                occurrence.source_context, "raw_title", "Movie 2021 1080p"
            ),
        }

        for label, change in changes.items():
            with self.subTest(change=label):
                existing = self._validated_occurrence()
                incoming = self._validated_occurrence()
                incoming.last_seen_at = self.later_time
                incoming.source_context.observed_at = self.later_time
                incoming.validation_status = None
                incoming.validation_policy_version = None
                incoming.validated_at = None
                incoming.validation_reason = None
                change(incoming)

                merged = merge_occurrences(existing, incoming)

                self.assertIsNone(merged.validation_status)
                self.assertIsNone(merged.validation_policy_version)
                self.assertIsNone(merged.validated_at)
                self.assertIsNone(merged.validation_reason)

    # --- 3. Cache Freshness Tests ---

    def test_cache_entry_freshness(self) -> None:
        entry = OmdbCacheEntry(
            lookup_title="inception",
            lookup_year=2010,
            status="found",
            payload={"Title": "Inception"},
            fetched_at=self.base_time,
            expires_at=self.later_time,
        )

        # Fresh check
        self.assertTrue(entry.expires_at > self.base_time)
        # Stale check
        self.assertFalse(entry.expires_at > self.later_time)
        self.assertFalse(entry.expires_at > (self.later_time + datetime.timedelta(seconds=1)))

    # --- 4. Fake Repositories & Duplicate Upsert/Idempotency Tests ---

    def test_fake_title_repository_duplicate_upsert_is_idempotent(self) -> None:
        repo = FakeTitleRepository()
        title_id = get_title_id("tt0133093", "the matrix", 1999, "movie")

        title1 = Title(
            title="The Matrix",
            normalized_title="the matrix",
            year=1999,
            media_type="movie",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
            updated_at=self.base_time,
            imdb_id="tt0133093",
            imdb_rating=8.7,
        )

        # First insert
        repo.upsert(title_id, title1)
        self.assertEqual(len(repo.list_all()), 1)

        fetched = repo.get(title_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.imdb_rating, 8.7)

        # Repeated identical upsert is idempotent
        repo.upsert(title_id, title1)
        self.assertEqual(len(repo.list_all()), 1)

        # Upserting modified metadata updates/merges existing
        title2 = Title(
            title="The Matrix",
            normalized_title="the matrix",
            year=1999,
            media_type="movie",
            first_seen_at=self.later_time,
            last_seen_at=self.later_time,
            updated_at=self.later_time,
            imdb_id="tt0133093",
            imdb_rating=8.8,
            plot="Updated Plot",
        )
        repo.upsert(title_id, title2)

        self.assertEqual(len(repo.list_all()), 1)
        fetched_updated = repo.get(title_id)
        self.assertEqual(fetched_updated.imdb_rating, 8.8)
        self.assertEqual(fetched_updated.plot, "Updated Plot")
        self.assertEqual(fetched_updated.first_seen_at, self.base_time)  # Preserved!
        self.assertEqual(fetched_updated.last_seen_at, self.later_time)  # Updated!

    def test_fake_occurrence_repository_duplicate_upsert_is_idempotent(self) -> None:
        repo = FakeOccurrenceRepository()
        title_id = "some-title-id"
        occ_id = get_occurrence_id("entry1", "https://torrent1.com")

        occ1 = Occurrence(
            source_feed_id="feed1",
            source_feed_name="Feed One",
            feed_entry_id="entry1",
            torrent_url="https://torrent1.com",
            raw_title="Movie.1999",
            quality="1080p",
            rip_type="BDRip",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
        )

        repo.upsert(title_id, occ_id, occ1)
        self.assertEqual(len(repo.list_by_title(title_id)), 1)

        # Duplicate sighting updates last_seen_at
        occ2 = Occurrence(
            source_feed_id="feed1",
            source_feed_name="Feed One",
            feed_entry_id="entry1",
            torrent_url="https://torrent1.com",
            raw_title="Movie.1999",
            quality="1080p",
            rip_type="BDRip",
            first_seen_at=self.later_time,
            last_seen_at=self.later_time,
        )

        repo.upsert(title_id, occ_id, occ2)
        self.assertEqual(len(repo.list_by_title(title_id)), 1)  # Still 1 record
        fetched = repo.get(title_id, occ_id)
        self.assertEqual(fetched.first_seen_at, self.base_time)
        self.assertEqual(fetched.last_seen_at, self.later_time)

    def test_fake_bulk_and_single_upserts_have_identical_merge_semantics(self) -> None:
        single_repo = FakeOccurrenceRepository()
        bulk_repo = FakeOccurrenceRepository()
        initial = Occurrence(
            source_feed_id="stable-feed",
            source_feed_name="Original Name",
            feed_entry_id="entry-1",
            torrent_url="https://example.test/1",
            raw_title="Film 2020",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
        )
        rescan = Occurrence(
            source_feed_id="stable-feed",
            source_feed_name="Renamed Feed",
            feed_entry_id="entry-1",
            torrent_url="https://example.test/1",
            raw_title="Film 2020",
            quality="2160p",
            rip_type="WEB-DL",
            first_seen_at=self.later_time,
            last_seen_at=self.later_time,
        )

        single_repo.upsert("title", "occurrence", initial)
        single_repo.upsert("title", "occurrence", rescan)
        bulk_repo.upsert_many([("title", "occurrence", initial)])
        bulk_repo.upsert_many([("title", "occurrence", rescan)])

        self.assertEqual(
            single_repo.get("title", "occurrence"),
            bulk_repo.get("title", "occurrence"),
        )

    def test_fake_repositories_use_defensive_copies(self) -> None:
        title_repo = FakeTitleRepository()
        title = Title(
            title="Copied Film",
            normalized_title="copied film",
            year=2020,
            media_type="movie",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
            updated_at=self.base_time,
            ai_validated=False,
        )
        title_repo.upsert("copied-title", title)
        title.ai_validated = True
        fetched_title = title_repo.get("copied-title")
        self.assertFalse(fetched_title.ai_validated)
        fetched_title.title = "Mutated outside repository"
        self.assertEqual(title_repo.get("copied-title").title, "Copied Film")

    def test_retryable_page_is_filtered_ordered_and_paginated(self) -> None:
        repo = FakeParseLogRepository()

        def add(log_id: str, reason: str, offset: int = 0, retry_state=None) -> None:
            repo.add(ParseLog(
                id=log_id,
                raw_title=log_id,
                feed_name="feed",
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
        self.assertEqual(first.next_cursor, RetryCursor(first.items[-1].processed_at, "retry-b"))
        second = repo.list_retryable(limit=1, cursor=first.next_cursor)
        self.assertEqual([log.id for log in second.items], ["retry-a"])
        self.assertIsNone(second.next_cursor)
        self.assertEqual([log.id for log in repo.list_unmapped(limit=10)], ["retry-b", "retry-a"])

    def test_retryable_work_survives_retention_and_resolution_round_trips(self) -> None:
        repo = FakeParseLogRepository()
        old_time = self.base_time - datetime.timedelta(days=10)
        retryable = ParseLog(
            id="retryable",
            raw_title="Retry",
            feed_name="feed",
            parsed_successfully=False,
            parsed_title=None,
            parsed_year=None,
            omdb_status="error",
            ignored=True,
            ignore_reason="entry_error",
            processed_at=old_time,
            attempt_count=2,
            last_attempt_at=self.earlier_time,
        )
        resolved = ParseLog(
            id="resolved",
            raw_title="Resolved",
            feed_name="feed",
            parsed_successfully=True,
            parsed_title="Resolved",
            parsed_year=2020,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            processed_at=old_time,
            retry_state="resolved",
            attempt_count=3,
            last_attempt_at=self.base_time,
            resolution=ParseLogResolution(
                resolved_at=self.base_time,
                outcome="matched",
                reason="catalog_match",
                title_id="title-1",
                occurrence_id="occurrence-1",
            ),
        )
        repo.add(retryable)
        repo.add(resolved)

        self.assertEqual(repo.prune_older_than(self.base_time), 1)
        stored = repo.get_all()
        self.assertEqual([log.id for log in stored], ["retryable"])
        self.assertEqual(stored[0].attempt_count, 2)
        self.assertEqual(stored[0].last_attempt_at, self.earlier_time)

    def test_legacy_retry_state_classification_is_conservative(self) -> None:
        retryable_reasons = (
            "parse_error",
            "entry_error",
            "omdb_not_found",
            "omdb_limit_reached",
            "omdb_error",
            "source_context_missing",
            "manual_mapping_error",
            "ai_result_missing",
            "ai_title_missing",
            "ai_year_invalid",
            "ai_media_type_missing",
            "reparse_processing_error",
            "catalog_persistence_error",
        )
        terminal_reasons = (
            "excluded_country_or_genre",
            "parse_only",
            "media_type_mismatch",
            "year_mismatch",
            "no_title",
            "empty_title",
            "match_ambiguous",
            "unknown_failure",
        )
        repo = FakeParseLogRepository()
        for reason in retryable_reasons + terminal_reasons:
            repo.add(ParseLog(
                id=reason,
                raw_title=reason,
                feed_name="feed",
                parsed_successfully=reason not in ("parse_error", "no_title", "empty_title"),
                parsed_title=None,
                parsed_year=None,
                omdb_status="error",
                ignored=True,
                ignore_reason=reason,
                processed_at=self.base_time,
            ))
        repo.add(ParseLog(
            id="audit",
            raw_title="audit",
            feed_name="feed",
            parsed_successfully=True,
            parsed_title="audit",
            parsed_year=2020,
            omdb_status="error",
            ignored=True,
            ignore_reason="omdb_error",
            processed_at=self.base_time,
            event_kind="audit_review",
        ))

        self.assertEqual(
            {log.id for log in repo.list_retryable(limit=100).items},
            set(retryable_reasons),
        )

    def test_parse_log_merge_preserves_attempt_history_and_resolution(self) -> None:
        resolution = ParseLogResolution(
            resolved_at=self.base_time,
            outcome="matched",
            reason="catalog_match",
            title_id="title-1",
        )
        existing = ParseLog(
            id="log",
            raw_title="Film",
            feed_name="feed",
            parsed_successfully=True,
            parsed_title="Film",
            parsed_year=2020,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            processed_at=self.base_time,
            retry_state="resolved",
            attempt_count=3,
            last_attempt_at=self.base_time,
            resolution=resolution,
        )
        incoming = ParseLog(
            id="log",
            raw_title="Film",
            feed_name="renamed feed",
            parsed_successfully=True,
            parsed_title="Film",
            parsed_year=2020,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            processed_at=self.later_time,
            retry_state="resolved",
            attempt_count=1,
            last_attempt_at=self.later_time,
        )

        merged = merge_parse_logs(existing, incoming)
        self.assertEqual(merged.attempt_count, 3)
        self.assertEqual(merged.last_attempt_at, self.later_time)
        self.assertEqual(merged.resolution, resolution)

        occurrence_repo = FakeOccurrenceRepository()
        occurrence = Occurrence(
            source_feed_id="feed1",
            source_feed_name="Feed One",
            feed_entry_id="entry1",
            torrent_url="https://torrent1.com",
            raw_title="Copied Film 2020",
            quality="1080p",
            rip_type="WEB-DL",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
        )
        occurrence_repo.upsert("copied-title", "copied-occurrence", occurrence)
        occurrence.raw_title = "Mutated outside repository"
        self.assertEqual(
            occurrence_repo.get("copied-title", "copied-occurrence").raw_title,
            "Copied Film 2020",
        )

        occurrence_with_context = Occurrence(
            **{
                **occurrence.__dict__,
                "raw_title": "Copied Film 2020",
                "source_context": SourceContext(
                    source_feed_id="feed1",
                    source_feed_name="Feed One",
                    feed_type="movie",
                    feed_entry_id="entry1",
                    torrent_url="https://torrent1.com",
                    raw_title="Copied Film 2020",
                    source_published_at=self.earlier_time,
                    observed_at=self.base_time,
                ),
            }
        )
        occurrence_repo.upsert("copied-title", "context-occurrence", occurrence_with_context)
        fetched_occurrence = occurrence_repo.get("copied-title", "context-occurrence")
        fetched_occurrence.source_context.raw_title = "Mutated nested context"
        self.assertEqual(
            occurrence_repo.get("copied-title", "context-occurrence").source_context.raw_title,
            "Copied Film 2020",
        )

    def test_fake_omdb_cache_repository(self) -> None:
        repo = FakeOmdbCacheRepository()
        cache_key = get_cache_key("inception", 2010)

        entry = OmdbCacheEntry(
            lookup_title="inception",
            lookup_year=2010,
            status="found",
            payload={"Title": "Inception"},
            fetched_at=self.base_time,
            expires_at=self.later_time,
        )

        self.assertIsNone(repo.get(cache_key))
        repo.set(cache_key, entry)

        fetched = repo.get(cache_key)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.lookup_title, "inception")
        self.assertEqual(fetched.status, "found")

    def test_fake_scan_run_repository(self) -> None:
        repo = FakeScanRunRepository()
        run_id = "run-abc-123"

        run = ScanRun(
            started_at=self.base_time,
            finished_at=None,
            status="running",
            trigger="schedule",
        )

        self.assertIsNone(repo.get(run_id))
        repo.upsert(run_id, run)

        fetched = repo.get(run_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.status, "running")

        # Update run status
        run.finished_at = self.later_time
        run.status = "succeeded"
        run.titles_created = 5
        repo.upsert(run_id, run)

        fetched_updated = repo.get(run_id)
        self.assertEqual(fetched_updated.status, "succeeded")
        self.assertEqual(fetched_updated.titles_created, 5)
        self.assertEqual(fetched_updated.finished_at, self.later_time)

    def test_fake_title_repository_delete_and_list_all_ids(self) -> None:
        repo = FakeTitleRepository()
        t1 = Title(
            title="Title 1",
            normalized_title="title 1",
            year=2020,
            media_type="movie",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
            updated_at=self.base_time,
        )
        t2 = Title(
            title="Title 2",
            normalized_title="title 2",
            year=2021,
            media_type="series",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
            updated_at=self.base_time,
        )
        repo.upsert("id1", t1)
        repo.upsert("id2", t2)

        pairs = repo.list_all_ids_and_titles()
        self.assertEqual(len(pairs), 2)
        self.assertEqual({p[0] for p in pairs}, {"id1", "id2"})

        # Delete id1
        repo.delete("id1")
        self.assertIsNone(repo.get("id1"))
        self.assertIsNotNone(repo.get("id2"))
        self.assertEqual(len(repo.list_all_ids_and_titles()), 1)

    def test_fake_occurrence_repository_delete_by_title(self) -> None:
        repo = FakeOccurrenceRepository()
        occ1 = Occurrence(
            source_feed_id="f1",
            source_feed_name="F1",
            feed_entry_id="e1",
            torrent_url="u1",
            raw_title="Raw 1",
            quality="1080p",
            rip_type="BDRip",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
        )
        occ2 = Occurrence(
            source_feed_id="f1",
            source_feed_name="F1",
            feed_entry_id="e2",
            torrent_url="u2",
            raw_title="Raw 2",
            quality="1080p",
            rip_type="BDRip",
            first_seen_at=self.base_time,
            last_seen_at=self.base_time,
        )
        repo.upsert("t1", "occ1", occ1)
        repo.upsert("t1", "occ2", occ2)
        repo.upsert("t2", "occ3", occ1)

        self.assertEqual(len(repo.list_by_title("t1")), 2)
        self.assertEqual(len(repo.list_by_title("t2")), 1)

        # Delete by title t1
        repo.delete_by_title("t1")
        self.assertEqual(len(repo.list_by_title("t1")), 0)
        self.assertEqual(len(repo.list_by_title("t2")), 1)

    def test_get_audit_proposal_id(self) -> None:
        source_id = "tt0133093"
        cluster = ["The Matrix 1999 1080p", "The Matrix 1999 720p"]
        pid = get_audit_proposal_id(source_id, cluster, "v1")
        self.assertEqual(len(pid), 64)
        # Idempotent with reordered list
        self.assertEqual(pid, get_audit_proposal_id(source_id, ["The Matrix 1999 720p", "The Matrix 1999 1080p"], "v1"))

    def test_fake_audit_proposal_repository_lifecycle(self) -> None:
        repo = FakeAuditProposalRepository()
        proposal = AuditProposal(
            id="p1",
            source_title_id="t1",
            occurrence_ids=["occ-1"],
            raw_title_cluster=["Raw Matrix"],
            current_metadata={"title": "Matrix"},
            proposed_metadata={"title": "The Matrix", "imdbId": "tt0133093"},
            evidence={"score": 0.95},
            confidence=0.95,
            policy_version="v1",
            created_at=self.earlier_time,
            updated_at=self.base_time,
            status="pending",
        )
        repo.upsert(proposal)
        self.assertEqual(repo.get("p1").status, "pending")
        self.assertEqual(len(repo.list_by_status("pending")), 1)
        self.assertEqual(len(repo.list_by_source_title("t1")), 1)

        # Transition to approved
        proposal.status = "approved"
        proposal.updated_at = self.later_time
        repo.upsert(proposal)
        updated = repo.get("p1")
        self.assertEqual(updated.status, "approved")
        self.assertEqual(updated.created_at, self.earlier_time)

        # Invalid transition approved -> pending
        proposal.status = "pending"
        with self.assertRaises(InvalidStatusTransitionError):
            repo.upsert(proposal)

        repo.delete("p1")
        self.assertIsNone(repo.get("p1"))


