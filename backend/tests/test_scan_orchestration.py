import datetime
import unittest

try:
    from . import _test_stubs
    from .scanner_test_support import (
        MockOmdbClient,
        ScannerTestMixin,
        make_inline_feed,
        make_series_result,
    )
except ImportError:
    import _test_stubs
    from scanner_test_support import (
        MockOmdbClient,
        ScannerTestMixin,
        make_inline_feed,
        make_series_result,
    )

from movies_feed.models import ParseLog, ScanRun, SourceContext
from movies_feed.scanner import ScannerConfig


class TestScanOrchestration(ScannerTestMixin, unittest.TestCase):
    def test_reparse_uses_stored_series_feed_type_and_accepts_later_season(self):
        result = make_series_result()
        source_log = ParseLog(
            id="unmapped-series",
            raw_title="Seasoned Show / Сезон 5 [2012]",
            feed_name="series_feed",
            parsed_successfully=True,
            parsed_title="Seasoned Show",
            parsed_year=2012,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=self.now,
            trace_details={"feedType": "series"},
            source_context=SourceContext(
                source_feed_id="series-feed",
                source_feed_name="Series Feed",
                feed_type="series",
                feed_entry_id="unmapped-series-entry",
                torrent_url="https://example.test/series/unmapped",
                raw_title="Seasoned Show / Сезон 5 [2012]",
                source_published_at=self.now - datetime.timedelta(days=2),
                observed_at=self.now - datetime.timedelta(days=1),
            ),
            event_kind="source",
        )
        self.parse_log_repo.add(source_log)
        config = ScannerConfig(mode="reparse-unfound")
        scanner = self.create_scanner(config, MockOmdbClient({"seasoned show": result}))
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.return_value = {
            0: {"title": "Seasoned Show", "year": 2012, "media_type": "series"}
        }
        scanner.ai_matcher = mock_ai
        run = ScanRun(started_at=self.now, finished_at=None, status="running", trigger="local")
        timings = {"omdb_api": 0.0, "parse_log_write": 0.0}

        stats = scanner.reparse_unfound_entries(run=run, section_timings=timings)

        self.assertEqual(stats["reparsed_succeeded"], 1)
        extract_items = mock_ai.batch_extract_titles.call_args.args[0]
        self.assertEqual(extract_items[0]["feed_type"], "series")
        self.assertIsNotNone(self.title_repo.get(result.imdb_id))

    def test_reparse_paginates_and_deduplicates_by_source_identity(self):
        for index in range(201):
            raw_title = "same title" if index % 2 else "Same Title"
            self.parse_log_repo.add(
                self.make_retry_log(
                    f"retry-page-{index}",
                    raw_title,
                    source_feed_id=f"feed-{index}",
                    feed_entry_id=f"entry-{index}",
                    processed_at=self.now - datetime.timedelta(minutes=index),
                )
            )

        scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound", omdb_limit=10),
            MockOmdbClient({"the matrix": self.valid_movie}),
        )
        from unittest.mock import MagicMock, patch
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.side_effect = lambda items: {
            item["id"]: {
                "title": "The Matrix",
                "year": 1999,
                "media_type": "movie",
            }
            for item in items
        }
        scanner.ai_matcher = mock_ai
        run = ScanRun(started_at=self.now, finished_at=None, status="running", trigger="local")

        with patch("movies_feed.reparse_service.time.sleep") as sleep:
            stats = scanner.reparse_unfound_entries(
                run=run,
                section_timings={"omdb_api": 0.0, "parse_log_write": 0.0},
            )

        self.assertEqual(stats["unmapped_seen"], 201)
        self.assertEqual(stats["resolved"], 201)
        self.assertEqual(stats["reparsed_succeeded"], 201)
        self.assertEqual(stats["reparsed_failed"], 0)
        self.assertEqual(mock_ai.batch_extract_titles.call_count, 15)
        self.assertEqual(sleep.call_count, 14)
        occurrences = self.occ_repo.list_by_title(self.valid_movie.imdb_id)
        self.assertEqual(len(occurrences), 201)
        self.assertEqual(len(self.parse_log_repo.get_all()), 201)

    def test_run_budget_is_shared_from_rss_to_reparse_phase(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": make_inline_feed("The Matrix (1999) [1080p]"),
                "type": "movie",
            }
        }
        self.parse_log_repo.add(ParseLog(
            id="unmapped-after-rss",
            raw_title="Unmapped Film (2020)",
            feed_name="test_feed",
            parsed_successfully=True,
            parsed_title="Unmapped Film",
            parsed_year=2020,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=self.now,
            trace_details={"feedType": "movie"},
            source_context=SourceContext(
                source_feed_id="test-feed",
                source_feed_name="test_feed",
                feed_type="movie",
                feed_entry_id="unmapped-after-rss-entry",
                torrent_url="https://example.test/unmapped-after-rss",
                raw_title="Unmapped Film (2020)",
                source_published_at=self.now - datetime.timedelta(days=2),
                observed_at=self.now - datetime.timedelta(days=1),
            ),
            event_kind="source",
        ))
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            mode="all",
            omdb_limit=1,
        )
        omdb = MockOmdbClient({"the matrix": self.valid_movie})
        scanner = self.create_scanner(config, omdb)
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_recheck_matches.return_value = {0: {"is_valid_match": True}}
        mock_ai.batch_extract_titles.return_value = {
            0: {"title": "Unmapped Film", "year": 2020, "media_type": "movie"}
        }
        scanner.ai_matcher = mock_ai

        run = scanner.run("shared_budget")

        self.assertEqual(run.status, "partial")
        self.assertEqual(run.omdb_requests, 1)
        self.assertEqual(omdb.request_count, 1)
        self.assertTrue(scanner.metadata_resolver.quota_exhausted)

    def test_phase_boundaries_metrics_and_counters(self):
        feed_xml = make_inline_feed("The Matrix (1999) [1080p]")
        config = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": feed_xml,
                    "type": "movie",
                }
            },
            mode="all",
            omdb_limit=10,
        )
        omdb = MockOmdbClient({"the matrix": self.valid_movie})
        scanner = self.create_scanner(config, omdb)

        run = scanner.run("run_phase_metrics")
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.titles_created, 1)
        self.assertEqual(run.occurrences_created, 1)
        self.assertEqual(run.entries_seen, 1)
        self.assertIn("rss", run.phase_metrics)
        self.assertIn("recheck_existing", run.phase_metrics)
        self.assertIn("reparse_unfound", run.phase_metrics)
        self.assertIn("apply_proposals", run.phase_metrics)

        rss_metrics = run.phase_metrics["rss"]
        self.assertEqual(rss_metrics["status"], "succeeded")
        self.assertEqual(rss_metrics["feeds_processed"], 1)
        self.assertEqual(rss_metrics["entries_seen"], 1)
        self.assertEqual(rss_metrics["titles_created"], 1)
        self.assertIsNotNone(rss_metrics["started_at"])
        self.assertIsNotNone(rss_metrics["finished_at"])

        recheck_metrics = run.phase_metrics["recheck_existing"]
        self.assertEqual(recheck_metrics["status"], "succeeded")

    def test_mode_all_phase_isolation_prevents_same_run_auditing_unless_allowed(self):
        feed_xml = make_inline_feed("The Matrix (1999) [1080p]")
        config = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": feed_xml,
                    "type": "movie",
                }
            },
            mode="all",
            omdb_limit=10,
            allow_same_run_chaining=False,
        )
        omdb = MockOmdbClient({"the matrix": self.valid_movie})
        scanner = self.create_scanner(config, omdb)

        recheck_called_with_ids = []

        def spy_recheck(*args, **kwargs):
            excluded = kwargs.get("excluded_title_ids")
            if excluded:
                recheck_called_with_ids.extend(excluded)
            return {
                "titles_checked": 0,
                "mismatches_found": 0,
                "repaired": 0,
                "removed": 0,
                "validated": 0,
                "needs_review": 0,
                "ai_failures": 0,
                "omdb_failures": 0,
                "clusters_checked": 0,
                "valid_clusters": 0,
                "proposals": 0,
                "retryable_failures": 0,
                "orphans": 0,
            }

        scanner.recheck_existing_titles = spy_recheck

        run = scanner.run("run_isolation")
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.titles_created, 1)
        # Verify that newly created title ID was in excluded_title_ids
        self.assertTrue(len(recheck_called_with_ids) > 0)
        created_title_id = list(self.title_repo._store.keys())[0]
        self.assertIn(created_title_id, recheck_called_with_ids)

        # Now test with allow_same_run_chaining=True
        self.title_repo._store.clear()
        self.occ_repo._store.clear()
        recheck_called_with_ids.clear()

        config_chained = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": feed_xml,
                    "type": "movie",
                }
            },
            mode="all",
            omdb_limit=10,
            allow_same_run_chaining=True,
        )
        scanner_chained = self.create_scanner(config_chained, omdb)
        scanner_chained.recheck_existing_titles = spy_recheck

        run_chained = scanner_chained.run("run_chained")
        self.assertEqual(run_chained.status, "succeeded")
        self.assertEqual(len(recheck_called_with_ids), 0)

    def test_scan_run_status_partial_on_error(self):
        config = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": "invalid://not-found",
                    "type": "movie",
                }
            },
            mode="rss",
            omdb_limit=10,
        )
        omdb = MockOmdbClient({})
        scanner = self.create_scanner(config, omdb)

        run = scanner.run("run_error_status")
        self.assertEqual(run.status, "partial")
        self.assertGreater(run.error_count, 0)


if __name__ == "__main__":
    unittest.main()