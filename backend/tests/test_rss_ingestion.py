import datetime
import unittest
from unittest.mock import patch

try:
    from . import _test_stubs
    from .scanner_test_support import (
        MockOmdbClient,
        ScannerTestMixin,
        make_inline_feed,
        make_multi_entry_feed,
        make_series_result,
    )
except ImportError:
    import _test_stubs
    from scanner_test_support import (
        MockOmdbClient,
        ScannerTestMixin,
        make_inline_feed,
        make_multi_entry_feed,
        make_series_result,
    )

from movies_feed.ids import get_title_id_v2
from movies_feed.models import ParseLog, RssSnapshot, RssSnapshotItem, Title
from movies_feed.omdb_client import OmdbTransportError
from backend.tests.fakes import FakeRssSnapshotRepository
from movies_feed.scanner import ScannerConfig


class TestRssIngestion(ScannerTestMixin, unittest.TestCase):
    def test_successful_rss_run_publishes_movie_first_snapshot_order(self):
        snapshot_repo = FakeRssSnapshotRepository()
        config = ScannerConfig(
            rss_feeds={
                "series-feed": {
                    "name": "Series Feed",
                    "url": make_multi_entry_feed([
                        ("series-1", "Seasoned Show / Сезон 5 [2012]"),
                    ]),
                    "type": "series",
                },
                "movie-feed-1": {
                    "name": "Movie Feed 1",
                    "url": make_multi_entry_feed([
                        ("movie-1", "The Matrix (1999) [1080p]"),
                        ("movie-1-duplicate", "The Matrix (1999) [2160p]"),
                    ]),
                    "type": "movie",
                },
                "movie-feed-2": {
                    "name": "Movie Feed 2",
                    "url": make_multi_entry_feed([
                        ("movie-2", "Filtered Movie (2000) [720p]"),
                    ]),
                    "type": "movie",
                },
            },
            omdb_limit=10,
        )
        scanner = self.scanner_builder.build(
            config=config,
            omdb_client=MockOmdbClient({
                "the matrix": self.valid_movie,
                "filtered movie": self.filtered_movie,
                "seasoned show": make_series_result(),
            }),
            rss_snapshot_repo=snapshot_repo,
        )

        run = scanner.run("snapshot-order")

        self.assertEqual(run.status, "succeeded")
        latest = snapshot_repo.get_latest()
        self.assertIsNotNone(latest)
        snapshot, items = latest
        self.assertEqual(snapshot.run_id, "snapshot-order")
        self.assertEqual([item.title_id for item in items], [
            self.valid_movie.imdb_id,
            self.filtered_movie.imdb_id,
            make_series_result().imdb_id,
        ])
        self.assertEqual([item.source_type for item in items], ["movie", "movie", "series"])
        self.assertEqual([item.rss_position for item in items], [0, 1, 2])
        self.assertEqual(len(self.title_repo.list_all()), 3)

    def test_partial_rss_run_keeps_previous_snapshot_published(self):
        snapshot_repo = FakeRssSnapshotRepository()
        previous_snapshot = RssSnapshot(
            id="previous-snapshot",
            run_id="previous-run",
            created_at=self.now,
            item_count=1,
        )
        previous_item = RssSnapshotItem(
            title_id=self.valid_movie.imdb_id,
            source_type="movie",
            group_order=0,
            feed_order=0,
            entry_order=0,
            rss_position=0,
        )
        snapshot_repo.publish("previous-snapshot", previous_snapshot, [previous_item])
        config = ScannerConfig(
            rss_feeds={
                "working-feed": {
                    "name": "Working Feed",
                    "url": make_inline_feed("The Matrix (1999) [1080p]"),
                    "type": "movie",
                },
                "broken-feed": {
                    "name": "Broken Feed",
                    "url": "tests/fixtures/missing-feed.xml",
                    "type": "movie",
                },
            },
            omdb_limit=10,
        )
        scanner = self.scanner_builder.build(
            config=config,
            omdb_client=MockOmdbClient({"the matrix": self.valid_movie}),
            rss_snapshot_repo=snapshot_repo,
        )

        run = scanner.run("partial-snapshot-run")

        self.assertEqual(run.status, "partial")
        latest = snapshot_repo.get_latest()
        self.assertIsNotNone(latest)
        self.assertEqual(latest[0].id, "previous-snapshot")

    def test_parse_logs_creation_and_pruning(self):
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
        scanner.run("run_logs")

        logs = self.parse_log_repo.list_recent()
        self.assertGreater(len(logs), 0)
        sample_log = logs[0]
        self.assertTrue(sample_log.parsed_successfully)
        self.assertIsNotNone(sample_log.raw_title)

    def test_section_timings_recorded(self):
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
        run = scanner.run("run_timing")

        self.assertIn("feed_fetch", run.section_timings)
        self.assertIn("title_parse", run.section_timings)
        self.assertIn("cache_lookup", run.section_timings)
        self.assertIn("omdb_api", run.section_timings)
        self.assertIn("db_upsert", run.section_timings)
        self.assertIn("parse_log_write", run.section_timings)
        self.assertIn("prune_logs", run.section_timings)

        # Test log pruning
        old_time = self.now - datetime.timedelta(days=10)
        from movies_feed.models import ParseLog
        old_log = ParseLog(
            id="old_log_1",
            raw_title="Old Movie",
            feed_name="test_feed",
            parsed_successfully=True,
            parsed_title="Old Movie",
            parsed_year=2010,
            omdb_status="found",
            ignored=False,
            ignore_reason=None,
            processed_at=old_time
        )
        self.parse_log_repo.add(old_log)
        self.assertIsNotNone(self.parse_log_repo._store.get("old_log_1"))

        # Running scanner again should prune the 10-day-old log
        scanner.run("run_logs_2")
        self.assertIsNone(self.parse_log_repo._store.get("old_log_1"))

    def test_omdb_limit_and_caching(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": "tests/fixtures/movies_feed.atom",
                "type": "movie"
            }
        }
        # First test hard limit
        config = ScannerConfig(
            rss_feeds=rss_feeds,
            video_settings={},
            excluded_countries=[],
            excluded_genres=[],
            omdb_limit=100
        )
        omdb = MockOmdbClient({"four rooms": self.valid_movie})
        omdb.limit_reached_on = 2

        scanner = self.create_scanner(config, omdb)
        run = scanner.run("run1")

        self.assertEqual(run.omdb_requests, 2)
        self.assertIn("OMDb API limit reached", run.error_summary)

        # Now test caching and soft limit
        config.omdb_limit = 0 # No new requests allowed!
        omdb.limit_reached_on = -1
        scanner = self.create_scanner(config, omdb)
        run2 = scanner.run("run2")
        self.assertEqual(run2.omdb_requests, 0) # Should be 0 since limit is 0
        self.assertTrue(run2.cache_hits > 0) # First request should hit cache

    def test_filtering_and_partial_failures(self):
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
            excluded_countries=["Russia"],
            excluded_genres=["Horror"],
            omdb_limit=100
        )
        omdb = MockOmdbClient({
            "four rooms": self.filtered_movie,
            "neige": OmdbTransportError("timeout")
        })

        scanner = self.create_scanner(config, omdb)
        run = scanner.run("run1")

        self.assertEqual(run.titles_created, 0)
        self.assertEqual(run.status, "partial")
        self.assertTrue(any("OMDb Transport Error" in err for err in run.error_summary))

    def test_rss_documentary_series_preserves_source_type_and_range(self):
        raw_title = "Документални / Nature Watch / Сезон 2 [2022, США, WEB-DL 1080p]"
        result = make_series_result(
            title="Nature Watch",
            year=2018,
            broadcast_year="2018-",
            genres=["Documentary", "History"],
        )
        config = ScannerConfig(
            rss_feeds={
                "series_feed": {
                    "name": "series_feed",
                    "url": make_inline_feed(raw_title),
                    "type": "series",
                }
            },
            omdb_limit=10,
        )

        run = self.create_scanner(config, MockOmdbClient({"nature watch": result})).run("series_documentary")

        self.assertEqual(run.status, "succeeded")
        stored = self.title_repo.get(result.imdb_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.media_type, "series")
        self.assertEqual(stored.source_type, "series")
        self.assertEqual(stored.content_kind, "documentary")
        self.assertEqual(stored.broadcast_range.raw, "2018-")

    def test_rss_known_movie_feed_does_not_follow_series_result(self):
        raw_title = "Документални / Nature Watch / Сезон 2 [2022, США, WEB-DL 1080p]"
        result = make_series_result(title="Nature Watch", year=2018)
        config = ScannerConfig(
            rss_feeds={
                "movie_feed": {
                    "name": "movie_feed",
                    "url": make_inline_feed(raw_title),
                    "type": "movie",
                }
            },
            omdb_limit=10,
        )

        run = self.create_scanner(config, MockOmdbClient({"nature watch": result})).run("movie_type_authority")

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(self.title_repo.list_all(), [])
        mismatch = next(log for log in self.parse_log_repo.get_all() if log.ignore_reason == "media_type_mismatch")
        self.assertEqual(mismatch.trace_details["matchReasonCode"], "type_mismatch")
        self.assertEqual(mismatch.trace_details["expectedSourceType"], "movie")

    def test_rss_unknown_feed_infers_series_from_marker(self):
        raw_title = "Документални / Nature Watch / Сезон 2 [2022, США, WEB-DL 1080p]"
        result = make_series_result(title="Nature Watch", year=2018, broadcast_year="2018-")
        config = ScannerConfig(
            rss_feeds={
                "untyped_feed": {
                    "name": "untyped_feed",
                    "url": make_inline_feed(raw_title),
                    "type": None,
                }
            },
            omdb_limit=10,
        )

        run = self.create_scanner(config, MockOmdbClient({"nature watch": result})).run("unknown_feed_type")

        self.assertEqual(run.status, "succeeded")
        stored = self.title_repo.get(result.imdb_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.source_type, "series")

    def test_parse_error_captured_in_parse_logs(self):
        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0">
                    <channel>
                        <item>
                            <title></title>
                            <link>https://example.com/torrent/empty</link>
                            <guid>guid_empty</guid>
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
        omdb = MockOmdbClient({})
        scanner = self.create_scanner(config, omdb)

        run = scanner.run("run_empty_title")
        self.assertEqual(run.ignored_entries, 1)

        logs = self.parse_log_repo.get_all()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].ignore_reason, "empty_title")
        self.assertFalse(logs[0].parsed_successfully)

    def test_parser_exception_logged_in_parse_logs(self):
        from unittest.mock import patch

        rss_feeds = {
            "test_feed": {
                "name": "test_feed",
                "url": """<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0">
                    <channel>
                        <item>
                            <title>Malformed Title (2022)</title>
                            <link>https://example.com/torrent/err</link>
                            <guid>guid_err</guid>
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
        omdb = MockOmdbClient({})
        scanner = self.create_scanner(config, omdb)

        with patch("movies_feed.rss_ingestion.parse_rutracker_title", side_effect=ValueError("Syntax parsing crash")):
            run = scanner.run("run_parse_err")

        self.assertEqual(run.ignored_entries, 1)
        self.assertEqual(run.error_count, 1)
        logs = self.parse_log_repo.get_all()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].ignore_reason, "parse_error")
        self.assertIn("Syntax parsing crash", logs[0].error_message or "")

    def test_parse_log_trace_details_and_diagnostics(self):
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
            excluded_countries=["Russia"],
            excluded_genres=["Horror"],
            omdb_limit=100
        )
        omdb = MockOmdbClient({
            "four rooms": self.filtered_movie,
        })

        scanner = self.create_scanner(config, omdb)
        scanner.run("run_trace_test")

        logs = scanner.parse_log_repo.get_all()
        self.assertTrue(len(logs) > 0)

        # Check that trace_details exist
        logs_with_trace = [l for l in logs if l.trace_details is not None]
        self.assertTrue(len(logs_with_trace) > 0)

        # Find the filtered movie log (Horror genre excluded)
        filtered_logs = [l for l in logs if l.ignore_reason == "excluded_country_or_genre"]
        if filtered_logs:
            f_log = filtered_logs[0]
            self.assertIn("Филтриран жанр", f_log.error_message)
            self.assertIsNotNone(f_log.trace_details)
            self.assertEqual(f_log.trace_details.get("decision"), "ignored_excluded_country_or_genre")
            self.assertEqual(f_log.trace_details.get("parsedTitle"), "Four Rooms")

    def test_single_pass_parsing_and_force_days_skips_parse(self):
        from unittest.mock import patch
        from movies_feed.rutracker_parser import parse_rutracker_title as real_parse

        old_date_str = (self.now - datetime.timedelta(days=10)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        new_date_str = (self.now - datetime.timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")

        feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Стар Филм / Old Movie [1990, САЩ, BDRip 1080p]</title>
                    <link>https://example.com/torrent/old</link>
                    <guid>guid_old</guid>
                    <pubDate>{old_date_str}</pubDate>
                </item>
                <item>
                    <title>Матрица / The Matrix (Вачовски) [1999, САЩ, фантастика, BDRip 1080p]</title>
                    <link>https://example.com/torrent/new</link>
                    <guid>guid_new</guid>
                    <pubDate>{new_date_str}</pubDate>
                </item>
            </channel>
        </rss>"""

        config = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": feed_xml,
                    "type": "movie",
                }
            },
            force_days=3,
            omdb_limit=10,
        )
        omdb = MockOmdbClient({"the matrix": self.valid_movie})
        scanner = self.create_scanner(config, omdb)

        parse_calls = []
        def parse_spy(raw, **kwargs):
            parse_calls.append(raw)
            return real_parse(raw, **kwargs)

        with patch("movies_feed.rss_ingestion.parse_rutracker_title", side_effect=parse_spy):
            run = scanner.run("run_single_pass")

        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.entries_seen, 2)
        self.assertEqual(run.ignored_entries, 1) # old movie ignored
        self.assertEqual(run.titles_created, 1)

        # parse_rutracker_title must be called exactly ONCE for the whole feed, and NOT called for old movie!
        self.assertEqual(len(parse_calls), 1)
        self.assertEqual(parse_calls[0], "Матрица / The Matrix (Вачовски) [1999, САЩ, фантастика, BDRip 1080p]")

    def test_same_parsed_context_used_for_prefetch_and_processing(self):
        raw_title = "Матрица / The Matrix (Вачовски) [1999, САЩ, фантастика, BDRip 1080p]"
        feed_xml = make_inline_feed(raw_title)
        config = ScannerConfig(
            rss_feeds={
                "test_feed": {
                    "name": "test_feed",
                    "url": feed_xml,
                    "type": "movie",
                }
            },
            omdb_limit=10,
        )
        omdb = MockOmdbClient({"the matrix": self.valid_movie})
        scanner = self.create_scanner(config, omdb)

        prefetch_calls = []
        original_prefetch = scanner.metadata_resolver.prefetch
        def prefetch_spy(requests, section_timings=None):
            prefetch_calls.extend(requests)
            return original_prefetch(requests, section_timings=section_timings)

        scanner.metadata_resolver.prefetch = prefetch_spy

        run = scanner.run("run_prefetch_reuse")
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.titles_created, 1)
        # Prefetch received exactly the parsed entry title and year
        self.assertEqual(len(prefetch_calls), 1)
        self.assertEqual(prefetch_calls[0][0], "The Matrix")
        self.assertEqual(prefetch_calls[0][1], 1999)

if __name__ == "__main__":
    unittest.main()