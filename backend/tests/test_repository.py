import datetime
import hashlib
import unittest

from movies_feed import (
    FakeOmdbCacheRepository,
    FakeOccurrenceRepository,
    FakeScanRunRepository,
    FakeTitleRepository,
    OmdbCacheEntry,
    Occurrence,
    ScanRun,
    Title,
    get_cache_key,
    get_fallback_title_id,
    get_occurrence_id,
    get_title_id,
    merge_occurrences,
    merge_titles,
    normalize_title,
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
        expected_raw = f"v1:cache:inception:{year}"
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
        )

        merged = merge_occurrences(existing, incoming)
        self.assertEqual(merged.first_seen_at, self.base_time)
        self.assertEqual(merged.last_seen_at, self.later_time)

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

