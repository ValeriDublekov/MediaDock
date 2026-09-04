import datetime
import unittest
from dataclasses import replace

try:
    from . import _test_stubs
    from .scanner_test_support import MockOmdbClient, ScannerTestMixin
except ImportError:
    import _test_stubs
    from scanner_test_support import MockOmdbClient, ScannerTestMixin

from movies_feed.ids import get_source_item_id, get_title_id_v2
from movies_feed.models import ManualMapping, ParseLog, ScanRun, SourceContext
from movies_feed.scanner import ScannerConfig


class TestScanPersistence(ScannerTestMixin, unittest.TestCase):
    def test_reparse_resolves_retained_manual_mapping_before_gemini(self):
        source_context = SourceContext(
            source_feed_id="archive",
            source_feed_name="Archive Display",
            feed_type="movie",
            feed_entry_id="archived-entry",
            torrent_url="https://example.test/archive/1",
            raw_title="Archived Matrix Release",
            source_published_at=self.now - datetime.timedelta(days=10),
            observed_at=self.now - datetime.timedelta(days=2),
        )
        source_log = ParseLog(
            id=get_source_item_id("archive", "archived-entry", source_context.torrent_url),
            raw_title="Archived Matrix Release",
            feed_name="Archive",
            parsed_successfully=True,
            parsed_title="Archived Matrix",
            parsed_year=1999,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=self.now,
            source_context=source_context,
            event_kind="source",
        )
        self.parse_log_repo.add(source_log)
        mapping = ManualMapping(
            id=source_log.id,
            raw_title="Unrelated mapping label",
            parsed_title="Archived Matrix",
            parsed_year=1999,
            imdb_id=self.valid_movie.imdb_id,
            created_at=self.now,
        )
        self.manual_mapping_repo.set(mapping)

        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({self.valid_movie.imdb_id: self.valid_movie}),
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.side_effect = AssertionError(
            "retained manual mappings must be resolved before Gemini"
        )
        scanner.ai_matcher = mock_ai

        run = scanner.run("retained_manual_mapping")

        title_id = get_title_id_v2(
            self.valid_movie.imdb_id,
            self.valid_movie.title,
            self.valid_movie.year,
            self.valid_movie.media_type,
        )
        occurrence_id = get_source_item_id(
            source_context.source_feed_id,
            source_context.feed_entry_id,
            source_context.torrent_url,
        )
        self.assertEqual(run.status, "succeeded")
        self.assertIsNotNone(self.title_repo.get(title_id))
        occurrence = self.occ_repo.get(title_id, occurrence_id)
        self.assertIsNotNone(occurrence)
        self.assertEqual(occurrence.source_context, source_context)
        self.assertEqual(occurrence.feed_entry_id, source_context.feed_entry_id)
        self.assertEqual(occurrence.torrent_url, source_context.torrent_url)
        resolved_log = next(
            log for log in self.parse_log_repo.get_all() if log.id == source_log.id
        )
        self.assertEqual(resolved_log.retry_state, "resolved")
        self.assertIsNotNone(resolved_log.resolution)
        self.assertEqual(resolved_log.resolution.title_id, title_id)
        self.assertEqual(resolved_log.resolution.occurrence_id, occurrence_id)
        self.assertEqual(resolved_log.attempt_count, 1)
        self.assertEqual(self.manual_mapping_repo.get_all(), [])

    def test_reparse_failure_updates_same_log_and_remains_retryable(self):
        source_log = self.make_retry_log(
            "retry-failure",
            "Missing Film (2020)",
            source_feed_id="archive",
            feed_entry_id="missing-film",
        )
        self.parse_log_repo.add(source_log)
        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({}),
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.return_value = {
            0: {"title": "Missing Film", "year": 2020, "media_type": "movie"}
        }
        scanner.ai_matcher = mock_ai
        run = ScanRun(started_at=self.now, finished_at=None, status="running", trigger="local")

        stats = scanner.reparse_unfound_entries(
            run=run,
            section_timings={"omdb_api": 0.0, "parse_log_write": 0.0},
        )

        logs = self.parse_log_repo.get_all()
        self.assertEqual([log.id for log in logs], [source_log.id])
        self.assertEqual(logs[0].retry_state, "retryable")
        self.assertEqual(logs[0].attempt_count, 1)
        self.assertIsNone(logs[0].resolution)
        self.assertEqual(stats["retried"], 1)
        self.assertEqual(stats["reparsed_succeeded"], 0)
        self.assertEqual(stats["reparsed_failed"], 1)
        self.assertEqual(self.title_repo.list_all(), [])

    def test_reparse_skips_duplicate_logs_for_one_source_identity(self):
        source_log = self.make_retry_log(
            "primary-source-log",
            "Same Title",
            source_feed_id="archive",
            feed_entry_id="same-entry",
        )
        duplicate_log = replace(
            source_log,
            id="duplicate-source-log",
            raw_title="same title",
        )
        self.parse_log_repo.add(source_log)
        self.parse_log_repo.add(duplicate_log)
        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({"the matrix": self.valid_movie}),
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.return_value = {
            0: {"title": "The Matrix", "year": 1999, "media_type": "movie"}
        }
        scanner.ai_matcher = mock_ai

        stats = scanner.reparse_unfound_entries(
            section_timings={"omdb_api": 0.0, "parse_log_write": 0.0},
        )

        self.assertEqual(stats["resolved"], 1)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(mock_ai.batch_extract_titles.call_count, 1)
        occurrences = self.occ_repo.list_by_title(self.valid_movie.imdb_id)
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(len(self.parse_log_repo.get_all()), 2)

    def test_reparse_catalog_write_failure_retries_original_log_and_keeps_mapping(self):
        source_log = self.make_retry_log(
            "write-failure",
            "Write Failure Film (2020)",
            source_feed_id="archive",
            feed_entry_id="write-failure-film",
        )
        self.parse_log_repo.add(source_log)
        mapping = ManualMapping(
            id=get_source_item_id(
                "archive",
                "write-failure-film",
                "https://example.test/archive/write-failure-film",
            ),
            raw_title="Write Failure Film",
            imdb_id=self.valid_movie.imdb_id,
            created_at=self.now,
        )
        self.manual_mapping_repo.set(mapping)

        def failing_upsert(title_id, occurrence_id, occurrence):
            raise RuntimeError("simulated occurrence write failure")

        self.occ_repo.upsert = failing_upsert
        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({self.valid_movie.imdb_id: self.valid_movie}),
        )

        stats = scanner.reparse_unfound_entries(
            section_timings={"omdb_api": 0.0, "parse_log_write": 0.0},
        )

        logs = self.parse_log_repo.get_all()
        self.assertEqual([log.id for log in logs], [source_log.id])
        self.assertEqual(logs[0].retry_state, "retryable")
        self.assertEqual(logs[0].attempt_count, 1)
        self.assertEqual(stats["retried"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual([item.id for item in self.manual_mapping_repo.get_all()], [mapping.id])

    def test_reparse_skips_legacy_retry_without_source_context(self):
        legacy_log = ParseLog(
            id="legacy-retry",
            raw_title="Legacy Film (2020)",
            feed_name="legacy-feed",
            parsed_successfully=True,
            parsed_title="Legacy Film",
            parsed_year=2020,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=self.now,
            trace_details={"feedType": "movie"},
        )
        self.parse_log_repo.add(legacy_log)
        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({"legacy film": self.valid_movie}),
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.side_effect = AssertionError(
            "legacy logs without retained source context must not reach Gemini"
        )
        scanner.ai_matcher = mock_ai

        stats = scanner.reparse_unfound_entries(
            section_timings={"parse_log_write": 0.0},
        )

        stored_log = self.parse_log_repo.get_all()[0]
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["retried"], 0)
        self.assertEqual(stored_log.id, legacy_log.id)
        self.assertEqual(stored_log.retry_state, "retryable")
        self.assertEqual(stored_log.attempt_count, 1)
        self.assertIsNone(stored_log.source_context)
        self.assertEqual(self.title_repo.list_all(), [])

    def test_reparse_manual_mapping_respects_shared_budget(self):
        source_log = self.make_retry_log(
            "manual-budget-retry",
            "Budgeted Film (2020)",
            source_feed_id="archive",
            feed_entry_id="budgeted-film",
        )
        self.parse_log_repo.add(source_log)
        mapping = ManualMapping(
            id=get_source_item_id(
                "archive",
                "budgeted-film",
                "https://example.test/archive/budgeted-film",
            ),
            raw_title="Budgeted Film",
            imdb_id=self.valid_movie.imdb_id,
            created_at=self.now,
        )
        self.manual_mapping_repo.set(mapping)
        omdb = MockOmdbClient({self.valid_movie.imdb_id: self.valid_movie})
        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound", omdb_limit=0),
            omdb,
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.side_effect = AssertionError(
            "manual mapping should be attempted before Gemini even when the budget is exhausted"
        )
        scanner.ai_matcher = mock_ai

        stats = scanner.reparse_unfound_entries(
            section_timings={"parse_log_write": 0.0},
        )

        self.assertEqual(omdb.request_count, 0)
        self.assertEqual(stats["retried"], 1)
        self.assertEqual([item.id for item in self.manual_mapping_repo.get_all()], [mapping.id])
        stored_log = self.parse_log_repo.get_all()[0]
        self.assertEqual(stored_log.retry_state, "retryable")
        self.assertEqual(stored_log.attempt_count, 1)

    def test_reparse_terminal_filter_does_not_consume_manual_mapping(self):
        source_log = self.make_retry_log(
            "terminal-filter",
            "Filtered Film (1999)",
            source_feed_id="archive",
            feed_entry_id="filtered-film",
        )
        self.parse_log_repo.add(source_log)
        mapping = ManualMapping(
            id=get_source_item_id(
                "archive",
                "filtered-film",
                "https://example.test/archive/filtered-film",
            ),
            raw_title="Filtered Film",
            imdb_id=self.valid_movie.imdb_id,
            created_at=self.now,
        )
        self.manual_mapping_repo.set(mapping)
        scanner = self.create_scanner(
            ScannerConfig(
                mode="reparse-unfound",
                excluded_countries=["USA"],
            ),
            MockOmdbClient({self.valid_movie.imdb_id: self.valid_movie}),
        )

        stats = scanner.reparse_unfound_entries(
            section_timings={"omdb_api": 0.0, "parse_log_write": 0.0},
        )

        stored_log = self.parse_log_repo.get_all()[0]
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stored_log.retry_state, "terminal")
        self.assertIsNotNone(stored_log.resolution)
        self.assertEqual(stored_log.resolution.outcome, "terminal")
        self.assertEqual([item.id for item in self.manual_mapping_repo.get_all()], [mapping.id])
        self.assertEqual(self.title_repo.list_all(), [])

    def test_duplicate_entries_idempotent(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "tests/fixtures/movies_feed.atom",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({"four rooms": self.valid_movie})


        scanner = self.create_scanner(config, omdb)
        run1 = scanner.run("run1")
        titles1 = len(self.title_repo.list_all())
        occ1 = sum(len(self.occ_repo.list_by_title(t.imdb_id or "tt0133093")) for t in self.title_repo.list_all())

        run2 = scanner.run("run2")
        titles2 = len(self.title_repo.list_all())
        occ2 = sum(len(self.occ_repo.list_by_title(t.imdb_id or "tt0133093")) for t in self.title_repo.list_all())

        self.assertEqual(titles1, titles2)
        self.assertEqual(occ1, occ2)
        self.assertEqual(run2.titles_created, 0)
        self.assertEqual(run2.occurrences_created, 0)

    def test_session_caching_reduces_repository_get_calls(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "tests/fixtures/movies_feed.atom",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({"four rooms": self.valid_movie})

        # Track get calls
        cache_get_count = 0
        original_cache_get = self.cache_repo.get

        def counting_cache_get(key: str):
            nonlocal cache_get_count
            cache_get_count += 1
            return original_cache_get(key)

        self.cache_repo.get = counting_cache_get

        scanner = self.create_scanner(config, omdb)
        run1 = scanner.run("run1")

        entries_count = run1.entries_seen
        self.assertGreater(entries_count, 1)

        # Without session caching, cache_repo.get would be called once per entry.
        # With session caching, unique keys are cached in memory during run, so calls to repository are <= unique keys.
        self.assertLess(cache_get_count, entries_count)

    def test_manual_mapping_processed_and_deleted(self):
        # Pre-seed manual mapping
        mapping = ManualMapping(
            id="manual_1",
            raw_title="Unfound Title (2020)",
            imdb_id="tt0133093",
            created_at=self.now,
            parsed_title="Unfound Title",
            parsed_year=2020
        )
        self.manual_mapping_repo.set(mapping)

        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0">
                    <channel>
                        <item>
                            <title>Unfound Title (2020) [1080p]</title>
                            <link>https://example.com/torrent/1</link>
                            <guid>guid1</guid>
                        </item>
                    </channel>
                </rss>""",
                "type": "movie"
            }
        }
        config = ScannerConfig(
            trigger="manual",
            is_dry_run=False,
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({"tt0133093": self.valid_movie})
        scanner = self.create_scanner(config, omdb)

        run = scanner.run("run_manual_mapping")

        self.assertEqual(run.entries_seen, 1)
        self.assertEqual(run.titles_created, 1)
        # Verify manual mapping was deleted from repository after processing
        remaining_mappings = self.manual_mapping_repo.get_all()
        self.assertEqual(len(remaining_mappings), 0)

    def test_manual_mapping_does_not_call_or_delete_when_budget_is_exhausted(self):
        mapping = ManualMapping(
            id="manual_budget",
            raw_title="Budgeted Title (2020)",
            imdb_id="tt0133093",
            created_at=self.now,
            parsed_title="Budgeted Title",
            parsed_year=2020,
        )
        self.manual_mapping_repo.set(mapping)
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0"><channel><item>
                    <title>Budgeted Title (2020) [1080p]</title>
                    <link>https://example.com/torrent/budget</link>
                    <guid>budget-guid</guid>
                </item></channel></rss>""",
                "type": "movie",
            }
        }
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            mode="rss",
            omdb_limit=0,
        )
        omdb = MockOmdbClient({"tt0133093": self.valid_movie})

        run = self.create_scanner(config, omdb).run("manual_budget")

        self.assertEqual(run.status, "partial")
        self.assertEqual(run.omdb_requests, 0)
        self.assertEqual(omdb.request_count, 0)
        self.assertEqual([item.id for item in self.manual_mapping_repo.get_all()], [mapping.id])


if __name__ == "__main__":
    unittest.main()