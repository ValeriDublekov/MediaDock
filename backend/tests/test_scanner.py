import datetime
import unittest
from dataclasses import replace

try:
    from . import _test_stubs
    from .scanner_test_support import MockOmdbClient, ScannerTestMixin, make_inline_feed
except ImportError:
    import _test_stubs
    from scanner_test_support import MockOmdbClient, ScannerTestMixin, make_inline_feed

from movies_feed.models import ManualMapping, ParseLog, SourceContext
from movies_feed.scanner import ScannerConfig
from movies_feed.ids import get_occurrence_id_v1, get_source_item_id, get_title_id_v2


class TestScanner(ScannerTestMixin, unittest.TestCase):
    def test_source_ids_use_stable_feed_key_not_display_name(self):
        raw_title = "Матрица / The Matrix (Вачовски) [1999, США, фантастика, BDRip 1080p]"
        published_at = datetime.datetime(2020, 1, 2, 12, 0, tzinfo=datetime.timezone.utc)
        first_observed_at = self.now
        config = ScannerConfig(
            rss_feeds={
                "stable-feed": {
                    "name": "Original Display Name",
                    "url": make_inline_feed(raw_title, "Thu, 02 Jan 2020 12:00:00 GMT"),
                    "type": "movie",
                }
            },
            omdb_limit=10,
        )
        self.create_scanner(config, MockOmdbClient({"the matrix": self.valid_movie})).run("stable_feed_first")
        config.rss_feeds["stable-feed"]["name"] = "Renamed Display Label"
        self.now = first_observed_at + datetime.timedelta(days=1)
        self.create_scanner(config, MockOmdbClient({"the matrix": self.valid_movie})).run("stable_feed_second")

        expected_id = get_source_item_id("stable-feed", "series-guid-1", None)
        occurrences = self.occ_repo.list_by_title(self.valid_movie.imdb_id)
        source_logs = [log for log in self.parse_log_repo.get_all() if log.event_kind == "source"]
        self.assertEqual(len(occurrences), 1)
        occurrence = self.occ_repo.get(self.valid_movie.imdb_id, expected_id)
        self.assertEqual(occurrence.source_feed_id, "stable-feed")
        self.assertEqual(occurrence.source_feed_name, "Renamed Display Label")
        self.assertEqual(occurrence.first_seen_at, first_observed_at)
        self.assertEqual(occurrence.last_seen_at, self.now)
        self.assertEqual(occurrence.source_context.source_published_at, published_at)
        self.assertEqual(occurrence.source_context.observed_at, self.now)
        self.assertEqual([log.id for log in source_logs], [expected_id])
        self.assertEqual(source_logs[0].source_context.source_feed_id, "stable-feed")
        self.assertEqual(source_logs[0].source_context.source_published_at, published_at)
        self.assertEqual(source_logs[0].source_context.observed_at, self.now)

    def test_equal_guids_from_different_feed_keys_create_distinct_source_items(self):
        raw_title = "Матрица / The Matrix (Вачовски) [1999, США, фантастика, BDRip 1080p]"
        config = ScannerConfig(
            rss_feeds={
                "movies-primary": {
                    "name": "Shared Display Name",
                    "url": make_inline_feed(raw_title),
                    "type": "movie",
                },
                "movies-secondary": {
                    "name": "Shared Display Name",
                    "url": make_inline_feed(raw_title),
                    "type": "movie",
                },
            },
            omdb_limit=10,
        )

        self.create_scanner(config, MockOmdbClient({"the matrix": self.valid_movie})).run("two_feeds")

        occurrence_ids = {
            get_source_item_id("movies-primary", "series-guid-1", None),
            get_source_item_id("movies-secondary", "series-guid-1", None),
        }
        self.assertEqual(len(self.occ_repo.list_by_title(self.valid_movie.imdb_id)), 2)
        self.assertEqual({log.id for log in self.parse_log_repo.get_all()}, occurrence_ids)

    def test_legacy_v1_manual_mapping_id_remains_usable(self):
        legacy_id = get_occurrence_id_v1(
            "series-guid-1",
            "https://example.com/torrent/series-1",
        )
        mapping = ManualMapping(
            id=legacy_id,
            raw_title="No raw-title match",
            imdb_id=self.valid_movie.imdb_id,
            created_at=self.now,
        )
        self.manual_mapping_repo.set(mapping)
        config = ScannerConfig(
            rss_feeds={
                "stable-feed": {
                    "name": "Movies",
                    "url": make_inline_feed(
                        "Матрица / The Matrix (Вачовски) [1999, США, фантастика, BDRip 1080p]"
                    ),
                    "type": "movie",
                }
            },
            omdb_limit=10,
        )

        run = self.create_scanner(config, MockOmdbClient({self.valid_movie.imdb_id: self.valid_movie})).run(
            "legacy_mapping"
        )

        self.assertEqual(run.titles_created, 1)
        self.assertEqual(self.manual_mapping_repo.get_all(), [])

    def test_rss_and_reparse_share_fallback_title_id(self):
        result_without_imdb = replace(
            self.valid_movie,
            imdb_id=None,
            raw_payload={**self.valid_movie.raw_payload, "imdbID": ""},
        )
        raw_title = "Матрица / The Matrix (Вачовски) [1999, США, фантастика, BDRip 1080p]"
        rss_config = ScannerConfig(
            rss_feeds={
                "movies": {
                    "name": "Movies",
                    "url": make_inline_feed(raw_title),
                    "type": "movie",
                }
            },
            omdb_limit=10,
        )
        self.create_scanner(rss_config, MockOmdbClient({"the matrix": result_without_imdb})).run(
            "fallback_rss"
        )
        expected_title_id = get_title_id_v2(None, "The Matrix", 1999, "movie")
        self.assertIsNotNone(self.title_repo.get(expected_title_id))

        retry_log = ParseLog(
            id=get_source_item_id("archive", "archived-entry", None),
            raw_title="Archived Matrix Release",
            feed_name="Archive",
            parsed_successfully=True,
            parsed_title="Archived Matrix",
            parsed_year=2000,
            omdb_status="not_found",
            ignored=True,
            ignore_reason="omdb_not_found",
            processed_at=self.now,
            trace_details={"feedType": "movie"},
            source_context=SourceContext(
                source_feed_id="archive",
                source_feed_name="Archive Display",
                feed_type="movie",
                feed_entry_id="archived-entry",
                torrent_url="https://example.test/archive/1",
                raw_title="Archived Matrix Release",
                source_published_at=self.now - datetime.timedelta(days=10),
                observed_at=self.now - datetime.timedelta(days=2),
            ),
            event_kind="source",
        )
        self.parse_log_repo.add(retry_log)
        reparse_scanner = self.create_scanner(
            ScannerConfig(mode="reparse-unfound"),
            MockOmdbClient({"the matrix": result_without_imdb}),
        )
        from unittest.mock import MagicMock
        mock_ai = MagicMock()
        mock_ai.is_available = True
        mock_ai.batch_extract_titles.return_value = {
            0: {"title": "The Matrix", "year": 1999, "media_type": "movie"}
        }
        reparse_scanner.ai_matcher = mock_ai

        reparse_scanner.reparse_unfound_entries(
            section_timings={"omdb_api": 0.0, "parse_log_write": 0.0}
        )

        self.assertEqual(
            [title_id for title_id, _ in self.title_repo.list_all_ids_and_titles()],
            [expected_title_id],
        )
        self.assertIsNotNone(self.occ_repo.get(expected_title_id, retry_log.id))
        reparsed_occurrence = self.occ_repo.get(expected_title_id, retry_log.id)
        self.assertEqual(reparsed_occurrence.source_feed_id, "archive")
        self.assertEqual(reparsed_occurrence.feed_entry_id, "archived-entry")
        self.assertEqual(reparsed_occurrence.torrent_url, "https://example.test/archive/1")
        self.assertEqual(reparsed_occurrence.source_context, retry_log.source_context)
        reparsed_log = next(log for log in self.parse_log_repo.get_all() if log.id == retry_log.id)
        self.assertEqual(reparsed_log.source_context, retry_log.source_context)





